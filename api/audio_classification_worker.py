"""In-process worker for P1 audio classification (bac à sable).

Claims queued jobs, downloads the object from S3, runs ffprobe + AI analysis,
and stores suggestions. It never moves/publishes files automatically.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from .audio_ai import analyze_audio_file
from .config import settings
from .s3 import make_clients
from .store import repo

log = logging.getLogger("uvicorn.error")
_s3, _ops = make_clients(
    settings.s3_endpoint, settings.s3_internal_endpoint,
    settings.s3_access_key, settings.s3_secret_key, settings.s3_region,
)
LEASE_S = 300
POLL_S = 5
MAX_ATTEMPTS = 5


def _download_object(bucket: str, key: str, dest: str) -> None:
    obj = _ops.get_object(Bucket=bucket, Key=key)
    body = obj["Body"]
    with open(dest, "wb") as f:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def process_one() -> bool:
    if not settings.ai_classification_enabled:
        return False
    job = repo.claim_audio_classification_job(int(time.time()) + LEASE_S, max_attempts=MAX_ATTEMPTS)
    if job is None:
        return False
    jid = job["id"]
    oid = job["object_id"]
    tmp = None
    try:
        row = repo.get_object_global(oid)
        if row is None or row.get("status") != "available":
            repo.fail_audio_classification_job(jid, "object_not_available")
            return True
        ctype = str(row.get("content_type") or "")
        if not ctype.startswith("audio/"):
            repo.fail_audio_classification_job(jid, f"unsupported_content_type:{ctype}")
            return True
        suffix = Path(str(row.get("display_name") or "audio")).suffix or ".bin"
        fd, tmp = tempfile.mkstemp(prefix="aura-aicls-", suffix=suffix)
        os.close(fd)
        _download_object(row["bucket"], row["object_key"], tmp)
        metadata = {
            "object_id": oid,
            "display_name": row.get("display_name"),
            "content_type": ctype,
            "size_bytes": row.get("size_bytes"),
            "bucket": row.get("bucket"),
            "folder_id": row.get("folder_id"),
        }
        result = analyze_audio_file(tmp, metadata=metadata)
        repo.complete_audio_classification_job(
            jid,
            provider=str(result.get("provider") or ""),
            model=str(result.get("model") or ""),
            confidence=result.get("confidence"),
            suggested_category=result.get("suggested_category"),
            suggested_themes=json.dumps(result.get("suggested_themes") or [], ensure_ascii=False),
            suggested_language=result.get("suggested_language"),
            suggested_folder=result.get("suggested_folder"),
            quality_json=json.dumps(result.get("quality") or {}, ensure_ascii=False),
            transcript_excerpt=result.get("transcript_excerpt"),
            reason=result.get("reason"),
            result_json=json.dumps(result, ensure_ascii=False),
            status="needs_review",
        )
        log.info("audio classification done jid=%s oid=%s provider=%s conf=%s", jid, oid, result.get("provider"), result.get("confidence"))
    except Exception as exc:
        attempts = int(job.get("attempts") or 0) + 1
        requeue = attempts < MAX_ATTEMPTS
        repo.fail_audio_classification_job(jid, str(exc)[:500], requeue=requeue)
        log.warning("audio classification failed jid=%s oid=%s requeue=%s: %s", jid, oid, requeue, exc)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    return True


def loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            worked = process_one()
        except Exception as exc:
            log.warning("audio classification loop error: %s", exc)
            worked = False
        if not worked:
            stop.wait(POLL_S)


def start() -> threading.Event:
    stop = threading.Event()
    if not settings.ai_classification_enabled:
        log.info("audio classification worker disabled")
        return stop
    t = threading.Thread(target=loop, args=(stop,), daemon=True, name="aura-audio-classification")
    t.start()
    log.info("audio classification worker started")
    return stop
