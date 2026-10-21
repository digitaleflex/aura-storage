"""N5 — asynchronous integrity verification, offline.

Large objects are no longer hashed inside the commit request: commit answers
202 'verifying' and a worker (api/verifier.py) hashes them under a lease. The
storage is an in-process fake; the worker is driven directly with verify_one.
"""
import hashlib
import os
import time

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402
from api.verifier import verify_one  # noqa: E402


class Body:
    def __init__(self, data, on_chunk=None):
        self.data = data
        self.on_chunk = on_chunk

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            if self.on_chunk:
                self.on_chunk()
            yield self.data[i:i + chunk_size]


class Store:
    def __init__(self, data: bytes):
        self.data = data
        self.etag = '"v1"'
        self.down = False
        self.on_chunk = None

    def head_object(self, Bucket, Key):
        if self.down:
            raise ConnectionError("storage down")
        return {"ContentLength": len(self.data), "ETag": self.etag,
                "ServerSideEncryption": "AES256"}

    def get_object(self, Bucket, Key):
        if self.down:
            raise ConnectionError("storage down")
        return {"Body": Body(self.data, self.on_chunk)}

    def delete_object(self, Bucket, Key):
        pass


DATA = os.urandom(3000)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    monkeypatch.setattr(main.settings, "verify_async_threshold_bytes", 1000)
    monkeypatch.setattr(main.settings, "commit_chunk_bytes", 500)
    monkeypatch.setattr(main.settings, "verify_heartbeat_bytes", 1000)
    store = Store(DATA)
    monkeypatch.setattr(main, "s3ops", store)
    # Drain anything a previous test left in 'verifying' so each test sees its own.
    while verify_one(main.repo, store, main.settings) is not None:
        pass
    yield store


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _upload(c, headers, size=len(DATA), idem=None):
    hdrs = dict(headers)
    if idem:
        hdrs["Idempotency-Key"] = idem
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "large.bin", "size_bytes": size}, headers=hdrs)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _sql(sql: str, params: tuple = ()):
    """Run a test-only statement on either catalogue backend (SQLite or the
    PostgreSQL parity job) and return the first row, or None."""
    if main.repo.dialect == "sqlite":
        row = main.repo.conn.execute(sql, params).fetchone()
        main.repo.conn.commit()
        return row
    cur = main.repo.conn.execute(sql.replace("?", "%s"), params)
    return cur.fetchone() if cur.description else None


def _status(oid):
    return _sql("SELECT status FROM objects WHERE id = ?", (oid,))["status"]


def test_large_commit_returns_202_and_the_worker_makes_it_available(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "verifying"
    # Not downloadable while it is checked; a repeated commit stays 202.
    assert c.post(f"/api/v1/objects/{oid}/download-intent", headers=headers).status_code == 409
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 202

    assert verify_one(main.repo, _setup, main.settings) == "available"
    obj = c.get(f"/api/v1/objects/{oid}").json()
    assert obj["status"] == "available"
    assert obj["checksum_sha256"] == hashlib.sha256(DATA).hexdigest()
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 200


def test_small_objects_are_still_verified_inline(_setup, monkeypatch):
    monkeypatch.setattr(main.settings, "verify_async_threshold_bytes", 10_000)
    c, headers = _admin()
    oid = _upload(c, headers)
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "available"


def test_a_crashed_worker_lease_expires_and_the_object_is_taken_again(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    now = int(time.time())
    # A worker claims it, then dies without finishing.
    assert main.repo.claim_verification(now, now + 300)["id"] == oid
    # Nobody else can take it while the lease runs...
    assert main.repo.claim_verification(now + 10, now + 310) is None
    # ...but once it has expired, the next worker does.
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now + 301) == "available"
    assert _status(oid) == "available"


def test_bytes_replaced_during_hashing_fail_the_object(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)

    def overwrite():
        _setup.etag = '"v2"'
    _setup.on_chunk = overwrite
    assert verify_one(main.repo, _setup, main.settings) == "failed"
    assert _status(oid) == "failed"


def test_bytes_replaced_before_hashing_fail_the_object(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    _setup.etag = '"v2"'
    assert verify_one(main.repo, _setup, main.settings) == "failed"


def test_storage_outage_is_retried_later_then_gives_up(_setup, monkeypatch):
    monkeypatch.setattr(main.settings, "verify_max_attempts", 2)
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    _setup.down = True
    now = int(time.time())
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now) == "retry"
    assert _status(oid) == "verifying"
    # The retry waits: nothing to claim right away.
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now + 1) is None
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now + 3600) == "failed"


def test_storage_back_before_the_limit_succeeds(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    _setup.down = True
    now = int(time.time())
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now) == "retry"
    _setup.down = False
    assert verify_one(main.repo, _setup, main.settings, now=lambda: now + 3600) == "available"


def test_the_lease_is_renewed_while_hashing(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    leases = []
    real = main.repo.extend_verification

    def spy(object_id, until):
        leases.append(until)
        real(object_id, until)
    main.repo.extend_verification = spy
    try:
        assert verify_one(main.repo, _setup, main.settings) == "available"
    finally:
        main.repo.extend_verification = real
    assert len(leases) >= 2  # 3000 bytes, heartbeat every 1000


def test_a_reload_after_upload_does_not_send_the_bytes_again(_setup):
    c, headers = _admin()
    oid = _upload(c, headers, idem="same-file-key")
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    # The page reloads while the check runs; the resume asks again with the key.
    hdrs = dict(headers, **{"Idempotency-Key": "same-file-key"})
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "large.bin", "size_bytes": len(DATA)}, headers=hdrs)
    assert r.status_code == 200
    assert r.json()["id"] == oid and r.json()["status"] == "verifying"
    assert r.json()["upload_url"] is None


def test_verifying_objects_cannot_be_deleted_or_aborted(_setup):
    c, headers = _admin()
    oid = _upload(c, headers)
    c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert c.delete(f"/api/v1/objects/{oid}", headers=headers).status_code == 409
    assert c.post(f"/api/v1/objects/{oid}/abort", headers=headers).status_code == 409
    assert c.get("/api/v1/objects?status=verifying", headers=headers).status_code == 200
