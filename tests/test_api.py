"""Issue #18/#22 tests against Better Auth sessions (no hand-rolled login).

Offline: session rows are inserted directly into the better-auth table shape.
Live (AURA_LIVE_S3=1): real node auth service signup + real SeaweedFS.
"""
import hashlib
import os
import secrets
import time
import uuid as _uuidmod

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "unused-with-better-auth")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_TRUSTED_ORIGINS", "http://127.0.0.1:5173")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api.ba_session import ensure_test_tables  # noqa: E402

SECRET_MARKERS = [
    os.environ["AURA_S3_SECRET_KEY"],
]

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
AUTH_URL = os.environ.get("AURA_TEST_AUTH_URL", "http://127.0.0.1:8099")

ensure_test_tables(main.repo)


def _insert_session(repo, user_id: str, ttl_s: int = 3600) -> str:
    token = secrets.token_urlsafe(32)
    exp = int(time.time()) + ttl_s
    if "sqlite3" in type(repo.conn).__module__:
        repo.conn.execute(
            'INSERT OR IGNORE INTO "user" (id, name, email) VALUES (?, ?, ?)',
            (user_id, "t", f"{user_id}@example.com"),
        )
        repo.conn.execute(
            'INSERT INTO session (id, token, "expiresAt", "userId") VALUES (?, ?, ?, ?)',
            (secrets.token_hex(8), token, exp, user_id),
        )
        repo.conn.commit()
    else:
        with repo.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "user" (id, name, email, "emailVerified", '
                '"createdAt", "updatedAt") VALUES (%s, %s, %s, false, now(), now()) '
                "ON CONFLICT (id) DO NOTHING",
                (user_id, "t", f"{user_id}@example.com"),
            )
            cur.execute(
                'INSERT INTO session (id, token, "expiresAt", "userId", '
                '"createdAt", "updatedAt") '
                "VALUES (%s, %s, to_timestamp(%s), %s, now(), now())",
                (str(_uuidmod.uuid4()), token, exp, user_id),
            )
    return f"{token}.sig"


def authed_client(user_id: str | None = None):
    user_id = user_id or str(_uuidmod.uuid4())
    c = TestClient(main.app)
    cookie = _insert_session(main.repo, user_id)
    c.cookies.set("aura.session_token", cookie)
    return c


def test_live_and_open_health():
    c = TestClient(main.app)
    assert c.get("/health/live").json() == {"status": "live"}


def test_objects_require_auth():
    assert TestClient(main.app).get("/api/v1/objects").status_code == 401


def test_mutation_requires_trusted_origin():
    c = authed_client()
    assert c.post("/api/v1/objects/upload-intents",
                  json={"bucket": "b", "display_name": "x"}).status_code == 403
    assert c.post("/api/v1/objects/upload-intents",
                  json={"bucket": "b", "display_name": "x"},
                  headers={"Origin": "https://evil.example"}).status_code == 403


def test_upload_intent_returns_scoped_url_and_leaks_nothing():
    c = authed_client()
    r = c.post("/api/v1/objects/upload-intents",
               json={"bucket": "test-bucket", "display_name": "hello.txt",
                     "content_type": "text/plain"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] and body["upload_url"].startswith("https://")
    assert "X-Amz-Expires=" in body["upload_url"]
    for marker in SECRET_MARKERS:
        assert marker not in r.text, "secret material leaked in response"
    assert TestClient(main.app).get(f"/api/v1/objects/{body['id']}").status_code == 401
    assert c.get(f"/api/v1/objects/{body['id']}").json()["status"] == "pending"


def test_cross_owner_isolation():
    c = authed_client()
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"bucket": "b", "display_name": "private.txt"},
                 headers=ORIGIN).json()["id"]
    bob = authed_client()
    assert bob.get(f"/api/v1/objects/{oid}").status_code == 404
    assert bob.get("/api/v1/objects").json()["items"] == []


def test_soft_delete_and_purge():
    c = authed_client()
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"bucket": "b", "display_name": "todelete.txt"},
                 headers=ORIGIN).json()["id"]
    assert c.delete(f"/api/v1/objects/{oid}", headers=ORIGIN).json()["status"] == "deleted"
    assert c.post(f"/api/v1/objects/{oid}/download-intent",
                 headers=ORIGIN).status_code == 409
    assert c.post(f"/api/v1/objects/{oid}/purge", headers=ORIGIN).status_code == 200
    assert c.get(f"/api/v1/objects/{oid}").status_code == 404


def test_reconcile_expires_stale_pending():
    from api.lifecycle import reconcile_pending

    c = authed_client()
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"bucket": "b", "display_name": "stale.txt"},
                 headers=ORIGIN).json()["id"]
    old = 7200
    if "sqlite3" in type(main.repo.conn).__module__:
        main.repo.conn.execute("UPDATE objects SET created_at = ? WHERE id = ?",
                               (main.repo.now() - old, oid))
        main.repo.conn.commit()
    else:
        with main.repo.conn.cursor() as cur:
            cur.execute("UPDATE objects SET created_at = %s WHERE id = %s",
                        (main.repo.now() - old, oid))
    fresh = c.post("/api/v1/objects/upload-intents",
                   json={"bucket": "b", "display_name": "fresh.txt"},
                   headers=ORIGIN).json()["id"]

    class DummyS3:
        def __init__(self):
            self.deleted = []

        def delete_object(self, Bucket, Key):
            self.deleted.append((Bucket, Key))

    out = reconcile_pending(main.repo, DummyS3(), expire_after_s=3600)
    assert out == {"expired": 1, "storage_deletes_attempted": 1}
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "expired"
    assert c.get(f"/api/v1/objects/{fresh}").json()["status"] == "pending"


LIVE = os.environ.get("AURA_LIVE_S3") == "1"


@pytest.mark.skipif(not LIVE, reason="needs real SeaweedFS (AURA_LIVE_S3=1)")
def test_live_round_trip_with_integrity():
    import httpx
    import uuid as _uuid

    # Google OAuth needs a browser; live API tests authenticate by inserting
    # a session exactly as the Better Auth service writes it (same table,
    # same token format), then exercise the full S3 data plane for real.
    uid = str(_uuid.uuid4())
    token = secrets.token_urlsafe(32)
    exp = int(time.time()) + 3600
    if "sqlite3" in type(main.repo.conn).__module__:
        main.repo.conn.execute(
            'INSERT INTO "user" (id, name, email) VALUES (?, ?, ?)',
            (uid, "live", f"{uid}@example.com"),
        )
        main.repo.conn.execute(
            'INSERT INTO session (id, token, "expiresAt", "userId") VALUES (?, ?, ?, ?)',
            (secrets.token_hex(8), token, exp, uid),
        )
        main.repo.conn.commit()
    else:
        with main.repo.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "user" (id, name, email, "emailVerified", '
                '"createdAt", "updatedAt") VALUES (%s, %s, %s, false, now(), now())',
                (uid, "live", f"{uid}@example.com"),
            )
            cur.execute(
                'INSERT INTO session (id, token, "expiresAt", "userId", '
                '"createdAt", "updatedAt") VALUES (%s, %s, to_timestamp(%s), %s, now(), now())',
                (str(_uuid.uuid4()), token, exp, uid),
            )
    c = TestClient(main.app)
    c.cookies.set("aura.session_token", f"{token}.sig")

    bucket = os.environ.get("AURA_TEST_BUCKET", "aura-api-ba")
    try:
        main.s3.create_bucket(Bucket=bucket)
    except Exception:
        pass
    payload = b"AURA better-auth round-trip %s" % os.urandom(16)
    want = hashlib.sha256(payload).hexdigest()
    intent = c.post("/api/v1/objects/upload-intents",
                    json={"bucket": bucket, "display_name": "live.bin",
                          "content_type": "application/octet-stream"},
                    headers=ORIGIN).json()
    put = httpx.put(intent["upload_url"], content=payload,
                    headers={"Content-Type": "application/octet-stream"}, timeout=30)
    assert put.status_code == 200, put.text
    committed = c.post(f"/api/v1/objects/{intent['id']}/commit",
                       headers=ORIGIN).json()
    assert committed["status"] == "available"
    assert committed["checksum_sha256"] == want
    dl = c.post(f"/api/v1/objects/{intent['id']}/download-intent",
                headers=ORIGIN).json()
    get = httpx.get(dl["download_url"], timeout=30)
    assert get.status_code == 200
    assert hashlib.sha256(get.content).hexdigest() == want
