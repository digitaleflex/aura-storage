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
import time

CLEAN = "clean"
INFECTED = "infected"
TIMEOUT = "timeout"


def scan_object(s3ops, bucket: str, key: str, settings, deadline=None) -> str:
    """Return CLEAN, INFECTED or TIMEOUT. Storage/IO errors propagate.

    The deadline bounds the *whole* operation (download + scan), not only the
    scanner: a slow or stalled S3 download must not hold the request or the
    verification worker forever. When no deadline is given, the AV scan timeout
    is used as the budget from the moment the download starts.
    """
    if not settings.av_scan_cmd:
        return CLEAN
    if deadline is None:
        deadline = time.monotonic() + settings.av_scan_timeout_s
    fd, path = tempfile.mkstemp(prefix="aura-av-")
    try:
        with os.fdopen(fd, "wb") as tmp:
            body = s3ops.get_object(Bucket=bucket, Key=key)["Body"]
            for chunk in body.iter_chunks(chunk_size=settings.commit_chunk_bytes):
                if time.monotonic() > deadline:
                    return TIMEOUT
                tmp.write(chunk)
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc = subprocess.run(
                [settings.av_scan_cmd, path],
                capture_output=True, text=True, timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return TIMEOUT
        return CLEAN if proc.returncode == 0 else INFECTED
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
