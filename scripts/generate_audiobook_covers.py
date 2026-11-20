#!/usr/bin/env python3
"""Extract locally embedded cover art from published audiobooks.

No external metadata or cover API is used. ffmpeg reads a short-lived presigned
GET of the audio object, takes its first embedded image stream (ID3 APIC / MP4
cover), resizes it and stores the JPEG next to the object in the same bucket.
The catalogue column `cover_key` is then set so /covers/{oid}.jpg can redirect
to it. Files without embedded art are simply left to the typographic fallback.

Bounded and resumable: only objects with no cover_key are considered, at most
--limit per run. Dry-run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
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
from api.s3 import SSE_ALGORITHM, presigned_get  # noqa: E402
from api.store import repo  # noqa: E402

AUDIO_TYPES = ("audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/flac", "audio/aac")
TIMEOUT_S = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ph = "?" if settings.db_backend == "sqlite" else "%s"
    marks = ",".join(ph for _ in AUDIO_TYPES)
    rows = repo.conn.execute(
        "SELECT * FROM objects WHERE status = 'available' AND published_at IS NOT NULL "
        f"AND cover_key IS NULL AND content_type IN ({marks}) "
        "ORDER BY created_at ASC LIMIT " + ph,
        (*AUDIO_TYPES, args.limit),
    ).fetchall()
    if not rows:
        print("aucun livre audio sans couverture")
        return 0

    s3 = boto3.client(
        "s3", endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    made, skipped = 0, 0
    for row in rows:
        obj = dict(row)
        url = presigned_get(s3, obj["bucket"], obj["object_key"], 300)
        args_ffmpeg = [
            "ffmpeg", "-v", "error", "-i", url,
            "-map", "0:v:0", "-frames:v", "1",
            "-vf", "scale=480:-2", "-f", "mjpeg", "-q:v", "4", "pipe:1",
        ]
        try:
            result = subprocess.run(
                args_ffmpeg, capture_output=True, timeout=TIMEOUT_S, check=False
            )
        except (subprocess.TimeoutExpired, OSError):
            skipped += 1
            continue
        jpeg = result.stdout or b""
        if result.returncode != 0 or len(jpeg) < 1024 or not jpeg.startswith(b"\xff\xd8"):
            skipped += 1
            continue
        key = f"{obj['object_key']}.cover.jpg"
        print(f"  couverture: {obj['display_name']}")
        if not args.apply:
            made += 1
            continue
        extra = {"ServerSideEncryption": SSE_ALGORITHM} if settings.require_sse else {}
        s3.put_object(
            Bucket=obj["bucket"], Key=key, Body=jpeg,
            ContentType="image/jpeg", **extra,
        )
        repo.set_object_cover(obj["id"], key)
        made += 1
    print(f"couvertures: {made} traitees, {skipped} sans art integre "
          f"({'APPLIQUE' if args.apply else 'DRY-RUN'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
