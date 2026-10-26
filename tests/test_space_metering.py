"""Per-space monthly quotas and metering.

- storage quota is enforced at upload intent;
- egress is an estimate (issued intents and share redemptions), enforced before
  the transfer is authorised;
- a refused share redemption does not consume a `max_uses` slot;
- quotas are admin-only and explicit null clears them.

Offline: SQLite catalogue, stub S3, local presigning.
"""
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


def _account(role="admin"):
    username = f"meter-{uuid.uuid4().hex[:10]}"
    password = "meter-test-password"
    main.repo.create_user(username, hash_password(password), role=role)
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _admin():
    return _account(role="admin")


def _space_id() -> str:
    return main.repo.list_spaces()[0]["id"]


def _object(c, headers, size=4096, name="doc.bin", content_type="application/pdf"):
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": name, "size_bytes": size, "content_type": content_type,
    }, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    main.repo.mark_available(oid, size, uuid.uuid4().hex)
    return oid


def _quotas(c, headers, sid, storage=None, egress=None):
    return c.put(
        f"/api/v1/admin/spaces/{sid}/quotas",
        json={"storage_bytes": storage, "egress_bytes_monthly": egress},
        headers=headers,
    )


def _clear(c, headers, sid):
    _quotas(c, headers, sid, None, None)


def _month(c, headers, sid):
    """Current-month counters, so tests do not depend on execution order."""
    usage = c.get("/api/v1/admin/usage", headers=headers).json()
    return next(i for i in usage["spaces"] if i["space_id"] == sid)["month"]


def test_storage_quota_blocks_upload_intent(monkeypatch):
    c, headers = _admin()
    sid = _space_id()
    try:
        assert _quotas(c, headers, sid, storage=100).status_code == 200
        refused = c.post("/api/v1/objects/upload-intents", json={
            "display_name": "too-big.bin", "size_bytes": 4096,
        }, headers=headers)
        assert refused.status_code == 429, refused.text
        assert refused.json()["detail"] == "storage quota exceeded"

        # Clearing the quota restores uploads.
        assert _quotas(c, headers, sid, storage=None).status_code == 200
        assert c.post("/api/v1/objects/upload-intents", json={
            "display_name": "ok.bin", "size_bytes": 4096,
        }, headers=headers).status_code == 200
    finally:
        _clear(c, headers, sid)


def test_download_intent_counts_and_blocks_egress(monkeypatch):
    c, headers = _admin()
    sid = _space_id()
    data = b"x" * 4096
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    oid = _object(c, headers, size=len(data))
    base = _month(c, headers, sid)
    try:
        assert _quotas(c, headers, sid, egress=base["egress_bytes"] + 3_000).status_code == 200
        refused = c.post(f"/api/v1/objects/{oid}/download-intent", headers=headers)
        assert refused.status_code == 429, refused.text
        assert refused.json()["detail"] == "monthly egress quota exceeded"

        allowed_quota = base["egress_bytes"] + 10_000
        assert _quotas(c, headers, sid, egress=allowed_quota).status_code == 200
        assert c.post(
            f"/api/v1/objects/{oid}/download-intent", headers=headers
        ).status_code == 200

        usage = c.get("/api/v1/admin/usage", headers=headers).json()
        row = next(i for i in usage["spaces"] if i["space_id"] == sid)
        assert row["month"]["egress_bytes"] == base["egress_bytes"] + 4096
        assert row["month"]["download_intents"] == base["download_intents"] + 1
        assert row["quota"]["egress_bytes_monthly"] == allowed_quota
        assert usage["totals"]["egress_bytes_month"] >= 4096
        assert usage["period"] == row["month"]["period"]

        # The request that would cross the ceiling is refused, not just the next.
        assert _quotas(
            c, headers, sid,
            egress=row["month"]["egress_bytes"] + len(data) - 1,
        ).status_code == 200
        assert c.post(
            f"/api/v1/objects/{oid}/download-intent", headers=headers
        ).status_code == 429
    finally:
        _clear(c, headers, sid)


def test_share_egress_quota_does_not_consume_a_use(monkeypatch):
    c, headers = _admin()
    sid = _space_id()
    data = b"y" * 1000
    monkeypatch.setattr(main, "s3ops", DummyS3(data))
    oid = _object(c, headers, size=len(data))
    r = c.post(f"/api/v1/objects/{oid}/share",
               json={"max_uses": 1, "content_disposition": "inline"},
               headers=headers)
    assert r.status_code == 200, r.text
    share = r.json()
    token = share["token"]
    base = _month(c, headers, sid)
    try:
        assert _quotas(
            c, headers, sid, egress=base["egress_bytes"] + 1
        ).status_code == 200
        denied = client.get(f"/s/{token}", follow_redirects=False)
        assert denied.status_code == 404
        listed = c.get(f"/api/v1/objects/{oid}/shares", headers=headers).json()
        row = next(i for i in listed["items"] if i["id"] == share["id"])
        assert row["use_count"] == 0

        assert _quotas(
            c, headers, sid, egress=base["egress_bytes"] + 10_000
        ).status_code == 200
        ok = client.get(f"/s/{token}", follow_redirects=False)
        assert ok.status_code == 302
        month = _month(c, headers, sid)
        assert month["share_redemptions"] == base["share_redemptions"] + 1
        assert month["egress_bytes"] == base["egress_bytes"] + len(data)
    finally:
        _clear(c, headers, sid)


def test_quotas_are_admin_only_and_space_must_exist():
    c, headers = _account(role="user")
    r = c.put(f"/api/v1/admin/spaces/{_space_id()}/quotas",
              json={"storage_bytes": 1}, headers=headers)
    assert r.status_code == 403, r.text
    admin, admin_headers = _account(role="admin")
    assert admin.put(
        f"/api/v1/admin/spaces/{uuid.uuid4()}/quotas",
        json={"storage_bytes": 1}, headers=admin_headers,
    ).status_code == 404
    # Negative values are refused by the model.
    assert _quotas(admin, admin_headers, _space_id(), storage=-1).status_code == 422


def test_egress_upsert_is_unambiguous_on_postgresql():
    """PostgreSQL rejects a bare RHS column shared with `excluded`."""
    import inspect

    from api import db_pg

    sql = inspect.getsource(db_pg.Repository.record_space_egress)
    assert "space_usage_monthly.egress_bytes + excluded.egress_bytes" in sql
