#!/usr/bin/env python3
"""Probe published audiobooks locally for duration and chapter markers.

ffprobe reads the object through a short-lived presigned GET. Nothing is fetched
from an external metadata service. Results are stored in `objects.duration_seconds`
and `audio_chapters`, then exposed through /api/public/library and the player.

Bounded and resumable: only objects with no duration are considered, at most
--limit per run. Dry-run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("AURA_REPO_ROOT", str(Path(__file__).resolve().parents[1])))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_env_file = ROOT / ".env"
for _line in (_env_file.read_text(encoding="utf-8").splitlines() if _env_file.exists() else []):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", os.environ.get("AURA_API_ADMIN_PASSWORD", ""))
if os.environ.get("S3_API_ACCESS_KEY"):
    os.environ.setdefault("AURA_S3_ACCESS_KEY", os.environ["S3_API_ACCESS_KEY"])
    os.environ.setdefault("AURA_S3_SECRET_KEY", os.environ["S3_API_SECRET_KEY"])
if os.environ.get("S3_DOMAIN"):
    os.environ.setdefault("AURA_S3_ENDPOINT", f"https://{os.environ['S3_DOMAIN']}")
if not os.environ.get("AURA_API_BACKEND") and os.environ.get("POSTGRES_USER"):
    from urllib.parse import quote_plus
    os.environ["AURA_API_BACKEND"] = "postgres"
    os.environ["AURA_API_DSN"] = "postgresql://{u}:{p}@localhost:5432/{db}".format(
        u=quote_plus(os.environ["POSTGRES_USER"]),
        p=quote_plus(os.environ.get("POSTGRES_PASSWORD", "")),
        db=os.environ.get("POSTGRES_DB", "aura"),
    )

import boto3  # noqa: E402

from api.config import settings  # noqa: E402
from api.s3 import presigned_get  # noqa: E402
from api.store import repo  # noqa: E402

AUDIO_TYPES = ("audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/flac", "audio/aac")
TIMEOUT_S = 90


def parse_probe(raw: bytes) -> tuple[float | None, list[dict]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, []
    duration = None
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    chapters = []
    for i, chapter in enumerate(data.get("chapters") or []):
        try:
            start = float(chapter["start_time"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            end = float(chapter["end_time"])
        except (KeyError, TypeError, ValueError):
            end = None
        title = (chapter.get("tags") or {}).get("title") or f"Chapitre {i + 1}"
        chapters.append({"index": i, "title": str(title)[:200], "start": start, "end": end})
    return duration, chapters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ph = "?" if settings.db_backend == "sqlite" else "%s"
    marks = ",".join(ph for _ in AUDIO_TYPES)
    rows = repo.conn.execute(
        "SELECT * FROM objects WHERE status = 'available' AND published_at IS NOT NULL "
        f"AND duration_seconds IS NULL AND content_type IN ({marks}) "
        "ORDER BY created_at ASC LIMIT " + ph,
        (*AUDIO_TYPES, args.limit),
    ).fetchall()
    if not rows:
        print("aucun livre audio à analyser")
        return 0

    s3 = boto3.client(
        "s3", endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    done, failed = 0, 0
    for row in rows:
        obj = dict(row)
        url = presigned_get(s3, obj["bucket"], obj["object_key"], 300)
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_chapters", "-show_format",
                 "-of", "json", url],
                capture_output=True, timeout=TIMEOUT_S, check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            failed += 1
            continue
        duration, chapters = parse_probe(result.stdout)
        if result.returncode != 0 or duration is None or duration <= 0:
            failed += 1
            continue
        print(f"  {obj['display_name']} | {duration:.0f} s | {len(chapters)} chapitres")
        if args.apply:
            repo.set_object_duration(obj["id"], duration)
            repo.replace_audio_chapters(obj["id"], chapters)
        done += 1
    print(f"analysés: {done}, ignorés: {failed} ({'APPLIQUE' if args.apply else 'DRY-RUN'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
