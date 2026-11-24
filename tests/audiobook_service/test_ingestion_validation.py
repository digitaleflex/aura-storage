from __future__ import annotations

import hashlib
import zipfile

import pytest

from audiobook.errors import ValidationError
from audiobook.ingestion import validate_file
from audiobook.storage import FakeStoragePort


def test_validate_audio_uses_magic_bytes_and_streaming_hash(tmp_path):
    payload = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 2048
    path = tmp_path / "livre.mp3"
    path.write_bytes(payload)
    result = validate_file(
        path, "../unsafe/nom.mp3", max_bytes=1_000_000, duration_ms=600_000
    )
    assert result.detected_content_type == "audio/mpeg"
    assert result.safe_filename == "nom.mp3"
    assert result.size_bytes == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.duration_ms == 600_000


def test_validate_epub_reads_mimetype_without_trusting_extension(tmp_path):
    path = tmp_path / "book.bin"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OEBPS/chapter.xhtml", "<p>Test</p>")
    result = validate_file(path, "book.epub", max_bytes=1_000_000)
    assert result.detected_content_type == "application/epub+zip"


def test_validate_rejects_empty_and_unknown_files(tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    with pytest.raises(ValidationError, match="empty"):
        validate_file(empty, "empty.mp3", max_bytes=1000)
    unknown = tmp_path / "unknown.bin"
    unknown.write_bytes(b"not a known format")
    with pytest.raises(ValidationError, match="content type"):
        validate_file(unknown, "unknown.bin", max_bytes=1000)


def test_validate_refuses_infected_file(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    scanner = tmp_path / "scan.sh"
    scanner.write_text("#!/bin/sh\nexit 1\n")
    scanner.chmod(0o755)
    with pytest.raises(ValidationError) as excinfo:
        validate_file(path, "song.mp3", max_bytes=1000, av_command=str(scanner))
    assert excinfo.value.code == "AV_INFECTED"


def test_fake_storage_commit_is_idempotent_and_verifies_actual_bytes(tmp_path):
    path = tmp_path / "audio.mp3"
    payload = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"x" * 128
    path.write_bytes(payload)
    storage = FakeStoragePort()
    intent = storage.create_upload_intent(
        display_name="audio.mp3",
        content_type="audio/mpeg",
        size_bytes=len(payload),
        idempotency_key="idem-1",
    )
    replay = storage.create_upload_intent(
        display_name="audio.mp3",
        content_type="audio/mpeg",
        size_bytes=len(payload),
        idempotency_key="idem-1",
    )
    assert replay.object_id == intent.object_id
    storage.upload_bytes(intent, path)
    first = storage.commit_upload(intent.object_id, idempotency_key="idem-1")
    second = storage.commit_upload(intent.object_id, idempotency_key="idem-1")
    assert first.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert second.checksum_sha256 == first.checksum_sha256
