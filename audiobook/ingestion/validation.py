"""Content validation for staged files before any AURA import."""
from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import ValidationError

_CHUNK_BYTES = 1024 * 1024
_SCAN_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ValidationResult:
    original_filename: str
    safe_filename: str
    size_bytes: int
    sha256: str
    detected_content_type: str
    duration_ms: int | None


def safe_filename(filename: str) -> str:
    """Keep a display-only name; never a path or control characters."""
    base = Path(str(filename)).name
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return cleaned[:200] or "import.bin"


def detect_content_type(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(32)
    if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "audio/mp4"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                mimetype = archive.read("mimetype").decode("ascii", "ignore").strip()
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            return "application/zip"
        if mimetype == "application/epub+zip":
            return "application/epub+zip"
        return "application/zip"
    return ""


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _run(command: str, args: list[str]) -> subprocess.CompletedProcess | None:
    parts = shlex.split(command)
    if not parts:
        return None
    try:
        return subprocess.run(
            [*parts, *args],
            capture_output=True,
            timeout=_SCAN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def validate_file(
    path: Path,
    filename: str,
    *,
    max_bytes: int,
    av_command: str = "",
    ffprobe_command: str = "",
    duration_ms: int | None = None,
) -> ValidationResult:
    """Validate one staged file without transferring or publishing it."""
    if max_bytes <= 0:
        raise ValidationError("invalid maximum ingest size")
    if not path.is_file() or path.is_symlink():
        raise ValidationError("staged file is not a regular file", code="INGEST_FILE_INVALID")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise ValidationError("empty files cannot be ingested", code="INGEST_FILE_EMPTY")
    if size_bytes > max_bytes:
        raise ValidationError("file exceeds the ingest size limit", code="INGEST_FILE_TOO_LARGE")
    content_type = detect_content_type(path)
    if not content_type:
        raise ValidationError(
            "content type could not be determined", code="INGEST_CONTENT_TYPE_UNKNOWN"
        )
    if av_command:
        scan = _run(av_command, [str(path)])
        if scan is not None:
            if scan.returncode == 1:
                raise ValidationError("infected file rejected", code="AV_INFECTED")
            if scan.returncode != 0:
                raise ValidationError("antivirus scan unavailable", code="AV_UNAVAILABLE")
    detected_duration = duration_ms
    if content_type.startswith("audio/") and detected_duration is None and ffprobe_command:
        probe = _run(
            ffprobe_command,
            [
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
        )
        if probe is not None and probe.returncode == 0:
            try:
                seconds = float(probe.stdout.decode("utf-8").strip())
                detected_duration = max(0, int(seconds * 1000))
            except (ValueError, UnicodeDecodeError):
                detected_duration = None
    digest, actual_size = _sha256_and_size(path)
    if actual_size != size_bytes:
        raise ValidationError("file changed while being validated", code="INGEST_FILE_CHANGED")
    return ValidationResult(
        original_filename=str(filename),
        safe_filename=safe_filename(filename),
        size_bytes=actual_size,
        sha256=digest,
        detected_content_type=content_type,
        duration_ms=detected_duration,
    )
