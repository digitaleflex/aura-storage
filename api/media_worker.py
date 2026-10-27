"""Bounded in-process HLS worker.

One job at a time, ffmpeg at low priority and one thread per encoder. Jobs are
claimed with a DB lease so a crash or redeploy does not leave one stuck. This is
deliberately simple: a solo-operator deployment, not a transcoding farm.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import ids
from .config import settings
from .s3 import make_clients, presigned_get
from .store import repo

log = logging.getLogger("uvicorn.error")
_s3, _ops = make_clients(
    settings.s3_endpoint, settings.s3_internal_endpoint,
    settings.s3_access_key, settings.s3_secret_key, settings.s3_region,
)
LEASE_S = 3600
CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
}


def _run(args: list[str], timeout: int) -> None:
    def low_priority():
        try:
            os.nice(10)
        except Exception:
            pass
    result = subprocess.run(
        args, capture_output=True, timeout=timeout, check=False,
        preexec_fn=low_priority,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or b"").decode("utf-8", "replace")[-500:])


def process_one() -> bool:
    job = repo.claim_media_job(int(time.time()) + LEASE_S)
    if job is None:
        return False
    oid = job["object_id"]
    try:
        row = repo.get_object_global(oid)
        if row is None or row["status"] != "available" or not row["content_type"].startswith("video/"):
            repo.set_object_hls(oid, "failed", None)
            repo.finish_media_job(job["id"], "failed", "not an available video")
            return True
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is not installed")
        url = presigned_get(
            _ops, row["bucket"], row["object_key"], 3600,
            content_disposition="inline", content_type=row["content_type"],
        )
        with tempfile.TemporaryDirectory(prefix="aura-hls-") as tmp:
            out = Path(tmp)
            _run([
                "ffmpeg", "-v", "error", "-threads", "1", "-i", url,
                "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "23", "-c:a", "aac", "-b:a", "128k",
                "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
                "-hls_segment_filename", str(out / "seg_%05d.ts"),
                str(out / "index.m3u8"),
            ], timeout=7200)
            prefix = f"{row['object_key']}.hls"
            for path in sorted(out.iterdir()):
                _ops.put_object(
                    Bucket=row["bucket"], Key=f"{prefix}/{path.name}",
                    Body=path.read_bytes(),
                    ContentType=CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
                    **({"ServerSideEncryption": "AES256"} if settings.require_sse else {}),
                )
        repo.set_object_hls(oid, "ready", prefix)
        repo.finish_media_job(job["id"], "done")
        log.info("hls ready oid=%s", oid)
    except Exception as exc:
        log.warning("hls failed oid=%s: %s", oid, exc)
        repo.set_object_hls(oid, "failed", None)
        repo.finish_media_job(job["id"], "failed", str(exc)[:500])
    return True


def loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            worked = process_one()
        except Exception as exc:
            log.warning("media worker loop error: %s", exc)
            worked = False
        if not worked:
            stop.wait(5)


def start() -> threading.Event:
    stop = threading.Event()
    if not settings.media_worker_enabled:
        return stop
    thread = threading.Thread(target=loop, args=(stop,), daemon=True,
                              name="aura-media-worker")
    thread.start()
    return stop
