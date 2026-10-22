"""Optional antivirus hook (D4), shared by the synchronous commit and the
verification worker so no path publishes an object without the scan.

``AURA_AV_SCAN_CMD`` is run as ``cmd <file>``; a non-zero exit means infected.
The object is spooled to a 0600 temp file that is removed in every case, and the
command is bounded by ``AURA_AV_SCAN_TIMEOUT_S`` (a hung scanner must not hold a
request or the worker forever).
"""
from __future__ import annotations

import os
import subprocess
import tempfile

CLEAN = "clean"
INFECTED = "infected"
TIMEOUT = "timeout"


def scan_object(s3ops, bucket: str, key: str, settings) -> str:
    """Return CLEAN, INFECTED or TIMEOUT. Storage/IO errors propagate."""
    if not settings.av_scan_cmd:
        return CLEAN
    fd, path = tempfile.mkstemp(prefix="aura-av-")
    try:
        with os.fdopen(fd, "wb") as tmp:
            body = s3ops.get_object(Bucket=bucket, Key=key)["Body"]
            for chunk in body.iter_chunks(chunk_size=settings.commit_chunk_bytes):
                tmp.write(chunk)
        try:
            proc = subprocess.run(
                [settings.av_scan_cmd, path],
                capture_output=True, text=True, timeout=settings.av_scan_timeout_s,
            )
        except subprocess.TimeoutExpired:
            return TIMEOUT
        return CLEAN if proc.returncode == 0 else INFECTED
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
