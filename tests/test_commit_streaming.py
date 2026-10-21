"""Issue #37: bounded-memory streaming commit, size/checksum validation, idempotency.

Offline: the S3 client is replaced with a stub that streams bytes in chunks, so
the tests exercise the real commit handler without a live endpoint.
"""
import hashlib
import logging
import os
import re
import time

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402

client = TestClient(main.app)


class FakeBody:
    """Mimics boto3's StreamingBody.iter_chunks and records chunk sizes."""

    def __init__(self, data: bytes):
        self.data = data
        self.chunks: list[int] = []

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            chunk = self.data[i:i + chunk_size]
            self.chunks.append(len(chunk))
            yield chunk


class DummyS3:
    def __init__(self, data: bytes, declared_size=None):
        self.body = FakeBody(data)
        self.declared_size = len(data) if declared_size is None else declared_size
        self.deleted = []

    def head_object(self, Bucket, Key):
        return {"ContentLength": self.declared_size, "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256"}

    def get_object(self, Bucket, Key):
        return {"Body": self.body}

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    from api import authz

    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _admin_headers():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _intent(c, headers, name="stream.bin", size_bytes=1):
    r = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": name,
              "content_type": "application/octet-stream",
              "size_bytes": size_bytes},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _backdate_intent(oid, seconds):
    expired = int(time.time()) - seconds
    if main.repo.dialect == "sqlite":
        conn = main.repo.conn
        conn.execute("UPDATE objects SET intent_expires_at = ? WHERE id = ?", (expired, oid))
        conn.commit()
    else:  # pragma: no cover - offline tests run on SQLite
        main.repo._run("UPDATE objects SET intent_expires_at = %s WHERE id = %s", (expired, oid))


def test_commit_streams_large_object_with_bounded_chunks(monkeypatch):
    monkeypatch.setattr(main.settings, "commit_chunk_bytes", 64 * 1024)
    data = os.urandom(300_000)  # ~4.6 chunks of 64 KiB
    digest = hashlib.sha256(data).hexdigest()
    s3 = DummyS3(data)
    monkeypatch.setattr(main, "s3ops", s3)

    c, headers = _admin_headers()
    oid = _intent(c, headers, "large.bin", size_bytes=len(data))
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "available"
    assert body["size_bytes"] == len(data)
    assert body["checksum_sha256"] == digest
    # Proof of streaming: several chunks, none larger than the configured size.
    assert len(s3.body.chunks) > 1
    assert max(s3.body.chunks) <= 64 * 1024


def test_commit_is_idempotent(monkeypatch):
    data = b"idempotent-payload"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin_headers()
    oid = _intent(c, headers)
    first = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    second = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["checksum_sha256"] == second.json()["checksum_sha256"]


def test_truncated_upload_is_rejected_and_not_available(monkeypatch):
    data = b"short"
    monkeypatch.setattr(main, "s3ops", DummyS3(data, declared_size=len(data) + 50))
    c, headers = _admin_headers()
    oid = _intent(c, headers, "truncated.bin")
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 422, r.text
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "failed"
    # A failed object is never downloadable.
    assert c.post(f"/api/v1/objects/{oid}/download-intent", headers=headers).status_code == 409


def test_oversized_upload_is_rejected(monkeypatch):
    # The intent declares a small size (1 byte) that is within the cap, so the
    # presigned URL is issued; the object that actually lands is bigger, and the
    # commit-time chokepoint must still reject it (defence in depth behind the
    # signed Content-Length, which a real backend enforces).
    monkeypatch.setattr(main.settings, "max_object_bytes", 1024)
    data = os.urandom(4096)
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin_headers()
    oid = _intent(c, headers, "big.bin")
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 413, r.text
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "failed"


def test_expired_intent_is_refused(monkeypatch):
    monkeypatch.setattr(main, "s3ops", DummyS3(b"x"))
    c, headers = _admin_headers()
    oid = _intent(c, headers, "expired.bin")
    _backdate_intent(oid, main.settings.intent_ttl + main.settings.intent_grace_s + 60)
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 410, r.text
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "expired"


def test_pending_object_is_not_visible_as_available(monkeypatch):
    monkeypatch.setattr(main, "s3ops", DummyS3(b"pending"))
    c, headers = _admin_headers()
    oid = _intent(c, headers, "notyet.bin")
    items = c.get("/api/v1/objects").json()["items"]
    entry = next(i for i in items if i["id"] == oid)
    assert entry["status"] == "pending"


def test_commit_emits_server_timing(monkeypatch, caplog):
    """The success path carries the same numbers in a header and one log line."""
    data = b"timed-payload"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin_headers()
    oid = _intent(c, headers, "timed.bin")

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)

    assert r.status_code == 200, r.text
    match = re.fullmatch(
        r"head;dur=(\d+\.\d), hash;dur=(\d+\.\d), total;dur=(\d+\.\d)",
        r.headers["Server-Timing"],
    )
    assert match is not None, r.headers["Server-Timing"]
    head_ms, hash_ms, total_ms = (float(value) for value in match.groups())
    assert head_ms >= 0 and hash_ms >= 0 and total_ms >= 0

    body = r.json()
    assert body["status"] == "available"
    assert body["checksum_algorithm"] == "sha256"

    lines = [
        record.getMessage() for record in caplog.records
        if record.name == "uvicorn.error" and "commit timings oid=" in record.getMessage()
    ]
    assert len(lines) == 1, lines
    assert lines[0] == (
        f"commit timings oid={oid} bytes={len(data)} head_ms={head_ms:.1f} "
        f"hash_ms={hash_ms:.1f} total_ms={total_ms:.1f}"
    )
