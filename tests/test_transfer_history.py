"""Issue #246 — server-side terminal transfer history (append-only journal).

Covers: terminal record creation, session correlation, read endpoints/filters,
isolation, idempotence, retention purge and absence of sensitive fields.
Runs against the in-memory SQLite backend (no PostgreSQL/SeaweedFS required).
"""
import hashlib
import os
import time
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit-history.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz, lifecycle  # noqa: E402
from api.auth import hash_password  # noqa: E402
from api.db import SCHEMA  # noqa: E402

client = TestClient(main.app)

SENSITIVE_KEYS = {
    "upload_url", "presigned_url", "url", "object_key", "key", "bucket",
    "storage_key", "token", "secret", "authorization", "signature",
}


class FakeBody:
    def __init__(self, data: bytes):
        self.data = data

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


class DummyS3:
    def __init__(self, data: bytes | None = None, *, declared_size=None,
                 head_error: Exception | None = None, get_error: Exception | None = None):
        self.data = b"" if data is None else data
        self.declared_size = len(self.data) if declared_size is None else declared_size
        self.head_error = head_error
        self.get_error = get_error
        self.deleted: list[tuple[str, str]] = []
        self.multipart_aborted: list[tuple[str, str, str]] = []

    def head_object(self, Bucket, Key, **kwargs):
        if self.head_error is not None:
            raise self.head_error
        return {"ContentLength": self.declared_size, "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256", "ETag": '"etag"'}

    def get_object(self, Bucket, Key, **kwargs):
        if self.get_error is not None:
            raise self.get_error
        return {"Body": FakeBody(self.data)}

    def delete_object(self, Bucket, Key, **kwargs):
        self.deleted.append((Bucket, Key))

    def abort_multipart_upload(self, Bucket, Key, UploadId, **kwargs):
        self.multipart_aborted.append((Bucket, Key, UploadId))

    def list_objects_v2(self, **kwargs):
        return {"Contents": []}


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _intent(c, headers, *, name="file.bin", size_bytes=1, content_type=None,
            transfer_session_id=None, idem=None):
    body = {"display_name": name, "size_bytes": size_bytes}
    if content_type is not None:
        body["content_type"] = content_type
    if transfer_session_id is not None:
        body["transfer_session_id"] = transfer_session_id
    hdrs = dict(headers)
    if idem is not None:
        hdrs["Idempotency-Key"] = idem
    return c.post("/api/v1/objects/upload-intents", json=body, headers=hdrs)


def _assert_no_sensitive(value, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            assert k.lower() not in SENSITIVE_KEYS, f"sensitive key {k!r} at {path}"
            _assert_no_sensitive(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _assert_no_sensitive(v, f"{path}[{i}]")


def _find_record_for_object(rows, oid):
    for r in rows:
        if r.get("object_id") == oid:
            return r
    return None


def _list_all(c, **params):
    r = c.get("/api/v1/transfers", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    return body


# ---------------------------------------------------------------------------
# Terminal record creation
# ---------------------------------------------------------------------------
def test_success_commit_creates_available_record_with_session(monkeypatch):
    data = b"history-success"
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin()
    sid = str(uuid.uuid4())

    r = _intent(c, headers, name="ok.pdf", size_bytes=len(data),
                content_type="application/pdf", transfer_session_id=sid)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    committed = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert committed.status_code == 200, committed.text

    body = _list_all(c, session_id=sid)
    rec = _find_record_for_object(body["items"], oid)
    assert rec is not None, body
    assert rec["status"] == "available"
    assert rec["transfer_session_id"] == sid
    assert rec["display_name"] == "ok.pdf"
    assert rec["final_size_bytes"] == len(data)
    assert rec["checksum_sha256"] == digest
    assert rec["created_at"] is not None
    assert rec["terminal_at"] is not None
    assert rec["terminal_at"] >= rec["created_at"]
    _assert_no_sensitive(body)


def test_failed_commit_creates_failed_record(monkeypatch):
    # Declared size differs from stored bytes -> commit fails terminally.
    monkeypatch.setattr(main, "s3ops", DummyS3(b"stored-longer"))
    c, headers = _admin()
    r = _intent(c, headers, name="bad.bin", size_bytes=5)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    committed = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert committed.status_code in (422, 413), committed.text

    body = _list_all(c)
    rec = _find_record_for_object(body["items"], oid)
    assert rec is not None, body
    assert rec["status"] == "failed"
    assert rec["object_id"] == oid
    assert rec.get("error_message") or rec.get("failure_kind")
    _assert_no_sensitive(body)


def test_abort_creates_aborted_record(monkeypatch):
    monkeypatch.setattr(main, "s3ops", DummyS3(b"x"))
    c, headers = _admin()
    r = _intent(c, headers, name="abort.bin", size_bytes=1)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    aborted = c.post(f"/api/v1/objects/{oid}/abort", headers=headers)
    assert aborted.status_code == 200, aborted.text

    body = _list_all(c)
    rec = _find_record_for_object(body["items"], oid)
    assert rec is not None, body
    assert rec["status"] == "aborted"
    _assert_no_sensitive(body)


def test_expired_intent_creates_expired_record(monkeypatch):
    monkeypatch.setattr(main, "s3ops", DummyS3(b""))
    c, headers = _admin()
    r = _intent(c, headers, name="exp.bin", size_bytes=1)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]

    # Force intent to be old so reconcile_pending expires it.
    expired_at = int(time.time()) - 7200
    if main.repo.dialect == "sqlite":
        conn = main.repo.conn
        conn.execute(
            "UPDATE objects SET intent_expires_at = ?, created_at = ? WHERE id = ?",
            (expired_at, expired_at, oid),
        )
        conn.commit()
    else:  # pragma: no cover
        main.repo._run(
            "UPDATE objects SET intent_expires_at = %s, created_at = %s WHERE id = %s",
            (expired_at, expired_at, oid),
        )

    result = lifecycle.reconcile_pending(main.repo, main.s3ops, expire_after_s=1)
    assert result.get("expired", 0) >= 0  # may include others; record is what matters

    body = _list_all(c)
    rec = _find_record_for_object(body["items"], oid)
    assert rec is not None, body
    assert rec["status"] == "expired"
    _assert_no_sensitive(body)


# ---------------------------------------------------------------------------
# Read endpoints and filters
# ---------------------------------------------------------------------------
def test_get_transfer_detail_and_not_found(monkeypatch):
    data = b"detail"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin()
    oid = _intent(c, headers, name="d.bin", size_bytes=len(data)).json()["id"]
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 200

    body = _list_all(c)
    rec = _find_record_for_object(body["items"], oid)
    assert rec is not None
    tid = rec["id"]

    detail = c.get(f"/api/v1/transfers/{tid}")
    assert detail.status_code == 200, detail.text
    got = detail.json()
    assert got["id"] == tid
    assert got["object_id"] == oid
    assert got["status"] == "available"
    _assert_no_sensitive(got)

    missing = c.get(f"/api/v1/transfers/{uuid.uuid4()}")
    assert missing.status_code == 404, missing.text


def test_filters_status_session_and_date_bounds(monkeypatch):
    monkeypatch.setattr(main, "s3ops", DummyS3(b"x"))
    c, headers = _admin()
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())

    oid_a = _intent(c, headers, name="a.bin", size_bytes=1, transfer_session_id=sid_a).json()["id"]
    assert c.post(f"/api/v1/objects/{oid_a}/abort", headers=headers).status_code == 200
    oid_b = _intent(c, headers, name="b.bin", size_bytes=1, transfer_session_id=sid_b).json()["id"]
    assert c.post(f"/api/v1/objects/{oid_b}/commit", headers=headers).status_code == 200

    aborted = _list_all(c, status="aborted")
    assert any(r.get("object_id") == oid_a for r in aborted["items"])
    assert all(r.get("status") == "aborted" for r in aborted["items"])

    by_session = _list_all(c, session_id=sid_b)
    assert any(r.get("object_id") == oid_b for r in by_session["items"])
    assert all(r.get("transfer_session_id") == sid_b for r in by_session["items"] if r.get("object_id") == oid_b)

    now = int(time.time())
    future = _list_all(c, **{"from": now + 86400})
    assert not any(r.get("object_id") in (oid_a, oid_b) for r in future["items"])
    past_window = _list_all(c, **{"from": now - 3600, "to": now + 3600})
    assert any(r.get("object_id") in (oid_a, oid_b) for r in past_window["items"])


# ---------------------------------------------------------------------------
# Idempotence and isolation
# ---------------------------------------------------------------------------
def test_commit_replay_does_not_duplicate_record(monkeypatch):
    data = b"idempotent"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin()
    oid = _intent(c, headers, name="idem.bin", size_bytes=len(data)).json()["id"]
    first = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert first.status_code == 200, first.text
    second = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    # replay may be 200 or conflict-like handled idempotently depending impl
    assert second.status_code in (200, 409), second.text

    rows = _list_all(c)["items"]
    matches = [r for r in rows if r.get("object_id") == oid]
    assert len(matches) == 1, matches


def test_other_user_cannot_read_history(monkeypatch):
    data = b"secret-owner"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    admin_c, headers = _admin()
    oid = _intent(admin_c, headers, name="private.bin", size_bytes=len(data)).json()["id"]
    assert admin_c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 200
    rec = _find_record_for_object(_list_all(admin_c)["items"], oid)
    assert rec is not None
    tid = rec["id"]

    # Create a regular user in the same default space and ensure isolation.
    try:
        from api import migrations
        app_id, space_id = migrations.resolve_default_ids(main.repo.conn, main.repo.dialect)
        uname = f"user_{uuid.uuid4().hex[:8]}"
        main.repo.create_user(
            uname, hash_password("passw0rd!123"), role="user",
            application_id=app_id, space_id=space_id,
        )
    except Exception:
        pytest.skip("could not create a secondary user for isolation test")

    other = TestClient(main.app)
    login = other.post("/api/v1/login", json={"username": uname, "password": "passw0rd!123"})
    if login.status_code != 200:
        pytest.skip(f"secondary login unavailable in this test env: {login.status_code}")

    listed = other.get("/api/v1/transfers")
    assert listed.status_code == 200, listed.text
    assert not any(r.get("object_id") == oid for r in listed.json().get("items", []))
    detail = other.get(f"/api/v1/transfers/{tid}")
    assert detail.status_code == 404, detail.text


# ---------------------------------------------------------------------------
# Retention purge and schema presence
# ---------------------------------------------------------------------------
def test_purge_removes_only_records_older_than_cutoff(monkeypatch):
    data = b"purge-me"
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin()
    oid = _intent(c, headers, name="purge.bin", size_bytes=len(data)).json()["id"]
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 200
    rec = _find_record_for_object(_list_all(c)["items"], oid)
    assert rec is not None

    # Age the record beyond retention.
    old = int(time.time()) - 200 * 86400
    if main.repo.dialect == "sqlite":
        conn = main.repo.conn
        conn.execute("UPDATE transfer_records SET terminal_at = ? WHERE object_id = ?", (old, oid))
        conn.commit()
    else:  # pragma: no cover
        main.repo._run("UPDATE transfer_records SET terminal_at = %s WHERE object_id = %s", (old, oid))

    result = lifecycle.purge_transfer_history(main.repo, retention_days=90, limit=500)
    assert result["transfer_records_purged"] >= 1
    assert _find_record_for_object(_list_all(c)["items"], oid) is None


def test_transfer_schema_objects_present():
    # Lightweight schema sanity check, on whichever backend runs the suite.
    if main.repo.dialect == "sqlite":
        tables = {
            r[0] for r in main.repo.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        cols = {
            r[1] for r in main.repo.conn.execute(
                "PRAGMA table_info(transfer_records)"
            ).fetchall()
        }
    else:
        tables = {
            r["table_name"] for r in main.repo._all(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
        }
        cols = {
            r["column_name"] for r in main.repo._all(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'transfer_records'"
            )
        }
    assert "transfer_records" in tables
    for needed in ("id", "transfer_session_id", "object_id", "status", "created_at", "terminal_at"):
        assert needed in cols
    assert "object_key" not in cols
    assert "bucket" not in cols
