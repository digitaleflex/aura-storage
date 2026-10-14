"""Issue #18 tests. Offline by default; live S3 round-trip behind AURA_LIVE_S3=1."""
import hashlib
import json
import os

import pytest

# Test credentials (offline-safe dummies unless live mode reuses the real .env).
os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402

# NOTE: the SigV4 access key *ID* legitimately appears in presigned URLs
# (X-Amz-Credential); it is an identifier, not a secret. Only the secret
# key and the admin password must never appear.
SECRET_MARKERS = [
    os.environ["AURA_S3_SECRET_KEY"],
    os.environ["AURA_API_ADMIN_PASSWORD"],
]

client = TestClient(main.app)


def make_client():
    return TestClient(main.app)


def login(c, username="admin", password=None):
    password = password or os.environ["AURA_API_ADMIN_PASSWORD"]
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def authed_client(username="admin", password=None):
    password = password or os.environ["AURA_API_ADMIN_PASSWORD"]
    c = make_client()
    csrf = login(c, username, password)
    return c, {"X-CSRF-Token": csrf}


client = make_client()


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def test_security_headers_present():
    r = client.get("/health/live")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_login_rate_limit_429_after_window_exhausted():
    c = make_client()
    for _ in range(10):
        r = c.post("/api/v1/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
    r = c.post("/api/v1/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 429


def test_audit_log_records_ids_and_no_secrets(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AURA_AUDIT_LOG", str(log))
    c = make_client()
    secret_pw = os.environ["AURA_API_ADMIN_PASSWORD"]
    c.post("/api/v1/login", json={"username": "admin", "password": "wrong"})
    csrf = login(c)
    c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "audit.txt"},
        headers={"X-CSRF-Token": csrf},
    )
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 3
    records = [json.loads(line) for line in lines]
    for rec in records:
        assert {"ts", "actor", "action", "result"} <= set(rec)
    actions = {(rec["action"], rec["result"]) for rec in records}
    assert ("login", "failure") in actions
    assert ("login", "success") in actions
    assert ("upload-intent", "success") in actions
    blob = log.read_text(encoding="utf-8")
    for marker in SECRET_MARKERS + [secret_pw]:
        assert marker not in blob, "secret material leaked in audit log"
    assert "X-Amz-Signature" not in blob
    assert "upload_url" not in blob
    assert "download_url" not in blob


def test_live_and_open_health():
    assert client.get("/health/live").json() == {"status": "live"}


def test_login_rejects_bad_password():
    r = client.post("/api/v1/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_objects_require_auth():
    assert client.get("/api/v1/objects").status_code == 401


def test_me_endpoint():
    from fastapi.testclient import TestClient as TC

    assert client.get("/api/v1/me").status_code == 401
    c2 = TC(main.app)
    login(c2)
    assert c2.get("/api/v1/me").json()["id"]


def test_mutation_requires_csrf():
    c, _ = authed_client()
    r = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "x.txt"},
        headers={"X-CSRF-Token": ""},
    )
    assert r.status_code == 403
    r = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "x.txt"},
        headers={"X-CSRF-Token": "bogus"},
    )
    assert r.status_code == 403


def test_upload_intent_returns_scoped_url_and_leaks_nothing():
    c, headers = authed_client()
    r = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "hello.txt",
              "content_type": "text/plain"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]
    assert body["upload_url"].startswith("https://")
    assert "X-Amz-Expires=" in body["upload_url"]
    blob = r.text
    for marker in SECRET_MARKERS:
        assert marker not in blob, "secret material leaked in response"
    # object is pending and invisible without auth
    assert make_client().get(f"/api/v1/objects/{body['id']}").status_code == 401
    got = c.get(f"/api/v1/objects/{body['id']}").json()
    assert got["status"] == "pending"


def test_soft_delete_and_purge():
    c, headers = authed_client()
    oid = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "todelete.txt"},
        headers=headers,
    ).json()["id"]
    r = c.delete(f"/api/v1/objects/{oid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"
    # deleted object is no longer downloadable
    r = c.post(f"/api/v1/objects/{oid}/download-intent", headers=headers)
    assert r.status_code == 409
    # purge removes it permanently
    r = c.post(f"/api/v1/objects/{oid}/purge", headers=headers)
    assert r.status_code == 200, r.text
    assert c.get(f"/api/v1/objects/{oid}").status_code == 404
    # purging twice is a clean 404
    assert c.post(f"/api/v1/objects/{oid}/purge", headers=headers).status_code == 404


def test_reconcile_expires_stale_pending():
    from api.lifecycle import reconcile_pending

    c, headers = authed_client()
    oid = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "stale.txt"},
        headers=headers,
    ).json()["id"]
    # backdate the pending row past the grace period
    old = 7200
    if hasattr(main.repo, "conn") and "sqlite3" in type(main.repo.conn).__module__:
        main.repo.conn.execute(
            "UPDATE objects SET created_at = ? WHERE id = ?",
            (main.repo.now() - old, oid),
        )
        main.repo.conn.commit()
    else:
        with main.repo.conn.cursor() as cur:
            cur.execute(
                "UPDATE objects SET created_at = %s WHERE id = %s",
                (main.repo.now() - old, oid),
            )
    # fresh pending objects are untouched; only the stale one expires
    fresh = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "fresh.txt"},
        headers=headers,
    ).json()["id"]
    # stub storage (offline): reconcile must not require real S3
    class DummyS3:
        def __init__(self):
            self.deleted = []

        def delete_object(self, Bucket, Key):
            self.deleted.append((Bucket, Key))

    out = reconcile_pending(main.repo, DummyS3(), expire_after_s=3600)
    assert out == {"expired": 1, "storage_deletes_attempted": 1}
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "expired"
    assert c.get(f"/api/v1/objects/{fresh}").json()["status"] == "pending"


def test_cross_owner_isolation():
    c, headers = authed_client()
    oid = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": "aura", "display_name": "private.txt"},
        headers=headers,
    ).json()["id"]
    # second user, created directly (unique per run: PG persists across runs)
    import uuid as _uuid

    from api.auth import hash_password
    bob_name = f"bob-{_uuid.uuid4().hex[:8]}"
    main.repo.create_user(bob_name, hash_password("bob-pass"))
    bob, _ = authed_client(bob_name, "bob-pass")
    assert bob.get(f"/api/v1/objects/{oid}").status_code == 404
    assert bob.get("/api/v1/objects").json()["items"] == []


LIVE = os.environ.get("AURA_LIVE_S3") == "1"


@pytest.mark.skipif(not LIVE, reason="needs real SeaweedFS (AURA_LIVE_S3=1)")
def test_live_round_trip_with_integrity():
    import httpx

    c, headers = authed_client()
    bucket = os.environ.get("AURA_TEST_BUCKET", "aura-api-test")
    try:
        main.s3.create_bucket(Bucket=bucket)
    except Exception:
        pass
    payload = b"AURA live round-trip %s" % os.urandom(16)
    want = hashlib.sha256(payload).hexdigest()
    intent = c.post(
        "/api/v1/objects/upload-intents",
        json={"bucket": bucket, "display_name": "live.bin",
              "content_type": "application/octet-stream"},
        headers=headers,
    ).json()
    put = httpx.put(
        intent["upload_url"], content=payload,
        headers={"Content-Type": "application/octet-stream"}, timeout=30,
    )
    assert put.status_code == 200, put.text
    committed = c.post(
        f"/api/v1/objects/{intent['id']}/commit",
        headers=headers,
    ).json()
    assert committed["status"] == "available"
    assert committed["checksum_sha256"] == want
    dl = c.post(
        f"/api/v1/objects/{intent['id']}/download-intent",
        headers=headers,
    ).json()
    assert "X-Amz-Expires=" in dl["download_url"]
    get = httpx.get(dl["download_url"], timeout=30)
    assert get.status_code == 200
    assert hashlib.sha256(get.content).hexdigest() == want
    # expired/tampered session is rejected
    bad = make_client().get(
        "/api/v1/objects", headers={"Cookie": "aura_session=bogus"}
    )
    assert bad.status_code == 401
    # a presigned URL past its TTL is rejected by storage (real expiry proof)
    import time as _time

    from api.s3 import presigned_put as _presign
    short_url = _presign(main.s3, bucket, "expiry-probe", "text/plain", 2)
    _time.sleep(4)
    expired = httpx.put(short_url, content=b"x", headers={"Content-Type": "text/plain"}, timeout=30)
    assert expired.status_code == 403, expired.text
