"""Per-object monthly analytics (views, downloads, share opens, egress)."""
import os
import uuid

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
from api.auth import hash_password  # noqa: E402
from tests.test_transfer_engine import DummyS3  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def _admin():
    username = f"stats-{uuid.uuid4().hex[:10]}"
    main.repo.create_user(username, hash_password("stats-test-password"), role="admin")
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": username, "password": "stats-test-password",
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _object(c, headers, size=1000, ctype="application/pdf"):
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": "cours.pdf", "size_bytes": size, "content_type": ctype,
    }, headers=headers)
    oid = r.json()["id"]
    main.repo.mark_available(oid, size, uuid.uuid4().hex)
    return oid


def test_counts_views_downloads_shares_and_egress(monkeypatch):
    data = b"x" * 1000
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    c, headers = _admin()
    oid = _object(c, headers, size=len(data))
    slug = f"stats-{uuid.uuid4().hex[:8]}"
    assert c.put(f"/api/v1/objects/{oid}/publication",
                 json={"slug": slug, "published": True}, headers=headers).status_code == 200

    assert c.post(f"/api/v1/objects/{oid}/download-intent", headers=headers).status_code == 200
    assert c.post(f"/api/v1/objects/{oid}/preview-intent", headers=headers).status_code == 200
    assert client.get(f"/m/{slug}", follow_redirects=False).status_code == 302
    share = c.post(f"/api/v1/objects/{oid}/share", json={}, headers=headers).json()
    assert client.get(f"/s/{share['token']}", follow_redirects=False).status_code == 302

    body = c.get(f"/api/v1/objects/{oid}/analytics", headers=headers).json()
    assert body["month"]["downloads"] == 1
    assert body["month"]["views"] == 2  # preview + public
    assert body["month"]["share_opens"] == 1
    assert body["month"]["egress_bytes"] == 4 * len(data)
    assert body["totals"]["views"] >= 2
    assert body["last_access_at"] is not None
    assert body["period"] == main._usage_period()


def test_analytics_is_scoped():
    c, headers = _admin()
    oid = _object(c, headers)
    assert c.get(f"/api/v1/objects/{uuid.uuid4()}/analytics",
                 headers=headers).status_code == 404
    assert client.get(f"/api/v1/objects/{oid}/analytics").status_code == 401
