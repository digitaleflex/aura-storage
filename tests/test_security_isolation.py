"""Issues #35, #36, #38, #39: isolation, server-side authorization, M2M identity.

All tests are offline (SQLite catalogue, no S3 endpoint). Two independent
applications/spaces are provisioned through the admin API and exercised through
service identities and human users.
"""
import json
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
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz, identity  # noqa: E402
from api.auth import hash_password  # noqa: E402
from api.migrations import DEFAULT_SPACE_ID  # noqa: E402

client = TestClient(main.app)


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


def _login(username, password):
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _make_app_space(c, headers):
    suffix = uuid.uuid4().hex[:8]
    r = c.post("/api/v1/admin/applications", json={"name": f"app-{suffix}"}, headers=headers)
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    r = c.post("/api/v1/admin/spaces", json={
        "application_id": app_id, "name": f"space-{suffix}", "environment": "test",
    }, headers=headers)
    assert r.status_code == 200, r.text
    return app_id, r.json()["id"], r.json()["bucket"]


def _make_identity(c, headers, space_id, scopes, name="svc"):
    r = c.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": name, "scopes": scopes,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _svc(token):
    return {"Authorization": f"Bearer {token}"}


def _ordinary_user():
    name = f"user-{uuid.uuid4().hex[:8]}"
    password = "user-password-123"
    main.repo.create_user(name, hash_password(password), role="user",
                          space_id=DEFAULT_SPACE_ID)
    return name, password


# ---------------------------------------------------------------------------
# #39 scenario: Application A cannot enumerate/read/copy/delete B's objects.
# ---------------------------------------------------------------------------
def test_cross_space_objects_are_invisible():
    c, headers = _admin()
    _, space_a, _ = _make_app_space(c, headers)
    _, space_b, bucket_b = _make_app_space(c, headers)
    token_a = _make_identity(c, headers, space_a, ["objects:read", "objects:write", "objects:delete"])["token"]
    token_b = _make_identity(c, headers, space_b, ["objects:read", "objects:write", "objects:delete"])["token"]

    intent = c.post("/api/v1/objects/upload-intents",
                    json={"display_name": "secret.txt"}, headers=_svc(token_a))
    assert intent.status_code == 200, intent.text
    oid = intent.json()["id"]

    # B lists nothing, and cannot reach A's object by ID with any verb.
    assert c.get("/api/v1/objects", headers=_svc(token_b)).json()["items"] == []
    assert c.get(f"/api/v1/objects/{oid}", headers=_svc(token_b)).status_code == 404
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=_svc(token_b)).status_code == 404
    assert c.post(f"/api/v1/objects/{oid}/download-intent", headers=_svc(token_b)).status_code == 404
    assert c.delete(f"/api/v1/objects/{oid}", headers=_svc(token_b)).status_code == 404

    # A still sees its own pending object.
    assert c.get(f"/api/v1/objects/{oid}", headers=_svc(token_a)).status_code == 200

    # A forged bucket and forged identity headers do not widen B's scope.
    forged = c.post("/api/v1/objects/upload-intents",
                    json={"bucket": bucket_b, "display_name": "x"},
                    headers={**_svc(token_a), "X-Space-Id": space_b, "X-Owner-Id": "admin"})
    assert forged.status_code == 403


def test_client_cannot_choose_object_key_or_owner():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, ["objects:write"])["token"]
    # Unknown/forged fields are rejected outright (extra="forbid").
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "x", "object_key": "aura/other/evil",
                     "owner_id": "admin", "space_id": "forged"},
               headers=_svc(token))
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# #36 scenario: server-side authorization of sensitive routes.
# ---------------------------------------------------------------------------
def test_ordinary_user_is_forbidden_on_admin_and_purge():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    name, password = _ordinary_user()
    u, uheaders = _login(name, password)

    # Ordinary user can create + soft-delete its own object...
    oid = u.post("/api/v1/objects/upload-intents",
                 json={"display_name": "mine.txt"}, headers=uheaders).json()["id"]
    assert u.delete(f"/api/v1/objects/{oid}", headers=uheaders).status_code == 200
    # ...but destructive/maintenance actions are refused even with a valid CSRF.
    assert u.post(f"/api/v1/objects/{oid}/purge", headers=uheaders).status_code == 403
    assert u.post("/api/v1/admin/reconcile", headers=uheaders).status_code == 403
    assert u.get("/api/v1/admin/stats").status_code == 403
    assert u.get("/api/v1/admin/identities").status_code == 403
    assert u.post("/api/v1/admin/applications", json={"name": "nope"},
                  headers=uheaders).status_code == 403
    assert u.post("/api/v1/admin/spaces", json={"application_id": "x", "name": "y",
                                                "environment": "z"},
                  headers=uheaders).status_code == 403
    # An administrator can still reconcile.
    assert c.post("/api/v1/admin/reconcile", headers=headers).status_code == 200


def test_service_identity_scope_is_enforced():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, ["objects:read"])["token"]
    assert c.get("/api/v1/objects", headers=_svc(token)).status_code == 200
    assert c.post("/api/v1/objects/upload-intents", json={"display_name": "x"},
                  headers=_svc(token)).status_code == 403
    assert c.get("/api/v1/admin/stats", headers=_svc(token)).status_code == 403


def test_mutating_routes_require_csrf_for_sessions():
    name, password = _ordinary_user()
    c, _ = _login(name, password)
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"display_name": "csrf.txt"},
                 headers={"X-CSRF-Token": "bogus"}).status_code
    assert oid == 403
    # No CSRF header at all is also refused on mutations.
    assert c.post("/api/v1/objects/upload-intents",
                  json={"display_name": "csrf.txt"}).status_code == 403


# ---------------------------------------------------------------------------
# #38 scenarios: M2M validity, revocation, rotation, expiry, secrecy.
# ---------------------------------------------------------------------------
def test_identity_revocation_and_rotation():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    created = _make_identity(c, headers, space, ["objects:read"])
    token = created["token"]

    assert c.get("/api/v1/me", headers=_svc(token)).status_code == 200

    # Rotation invalidates the old secret immediately.
    rotated = c.post(f"/api/v1/admin/identities/{created['id']}/rotate", headers=headers)
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]
    assert new_token != token
    assert c.get("/api/v1/me", headers=_svc(token)).status_code == 401
    assert c.get("/api/v1/me", headers=_svc(new_token)).status_code == 200

    # Revocation invalidates the current secret.
    assert c.post(f"/api/v1/admin/identities/{created['id']}/revoke",
                  headers=headers).status_code == 200
    assert c.get("/api/v1/me", headers=_svc(new_token)).status_code == 401


def test_expired_identity_is_rejected():
    c, headers = _admin()
    app_id, space, _ = _make_app_space(c, headers)
    iid = main.repo.new_id()
    secret = identity.new_secret()
    main.repo.create_identity(iid, app_id, space, "expired", identity.fingerprint(secret),
                              "objects:read", int(time.time()) - 60)
    token = identity.format_token(iid, secret)
    assert c.get("/api/v1/me", headers=_svc(token)).status_code == 401


def test_invalid_token_is_401_and_secrets_never_leak(monkeypatch, tmp_path):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AURA_AUDIT_LOG", str(audit))
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    created = _make_identity(c, headers, space, ["objects:read"], name="leak-check")
    token = created["token"]

    # Unknown token -> 401, indistinguishable from revoked.
    assert c.get("/api/v1/me", headers=_svc("aura_deadbeef_not-a-real-secret")).status_code == 401

    listed = c.get("/api/v1/admin/identities", headers=headers)
    assert listed.status_code == 200
    blob = listed.text
    assert token not in blob
    assert "secret_hash" not in blob

    # The one-time token must not appear in the audit log.
    log_text = audit.read_text(encoding="utf-8") if audit.exists() else ""
    assert token not in log_text
    secret_part = token.rsplit("_", 1)[1]
    assert secret_part not in log_text
    for line in log_text.strip().splitlines() or ["{}"]:
        json.loads(line)  # every audit line stays valid JSON


def test_unknown_token_scope_is_refused():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    r = c.post("/api/v1/admin/identities", json={
        "space_id": space, "name": "bad", "scopes": ["root:everything"],
    }, headers=headers)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# #36 guard: every unclassified /api/v1 route stays closed to anonymous callers.
# ---------------------------------------------------------------------------
def test_every_sensitive_route_denies_unauthenticated():
    public = {"/api/v1/login"}
    tested = 0
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/api/v1") or path in public:
            continue
        concrete = path.replace("{oid}", "does-not-exist").replace("{iid}", "does-not-exist")
        for method in methods - {"HEAD", "OPTIONS"}:
            resp = client.request(method, concrete, json={})
            assert resp.status_code in (401, 403, 405, 422), (method, path, resp.status_code)
            assert resp.status_code != 200, (method, path)
            tested += 1
    assert tested >= 10  # the guard must actually cover the sensitive surface
