"""Partner integrations (``/api/v1/admin/partner-sites``).

A partner site is metadata (name, origin, default media TTL, notes) attached to
a dedicated service identity. These tests pin:

- creation returns the identity token exactly once and the token really works
  for ``objects:read``;
- the site URL is normalized to an https origin (no http, credentials, query);
- scopes stay data-plane (administration scopes refused, empty refused);
- names are unique per space;
- metadata can be edited, and revocation is delegated to the identity routes
  (the site row then reports the identity state, never a secret);
- non-admin accounts cannot read or create.

Offline: SQLite catalogue only, no S3 endpoint is contacted.
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

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def _account(role="admin"):
    username = f"partner-{uuid.uuid4().hex[:10]}"
    password = "partner-test-password"
    main.repo.create_user(username, hash_password(password), role=role)
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _admin():
    return _account(role="admin")


def _space_id() -> str:
    spaces = main.repo.list_spaces()
    assert spaces
    return spaces[0]["id"]


def _create(c, headers, **overrides):
    body = {
        "name": f"cours-{uuid.uuid4().hex[:6]}",
        "site_url": "https://cours.example.com/",
        "space_id": _space_id(),
        "scopes": ["objects:read"],
    }
    body.update(overrides)
    return c.post("/api/v1/admin/partner-sites", json=body, headers=headers)


def test_create_returns_a_working_one_time_token():
    c, headers = _admin()
    r = _create(c, headers, name="Cours Next.js")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Cours Next.js"
    # Trailing slash is normalized away: the value is an origin to copy.
    assert body["site_url"] == "https://cours.example.com"
    assert body["identity"]["scopes"] == ["objects:read"]
    assert body["identity"]["revoked_at"] is None
    assert body["token"].startswith("aura_")
    assert "secret" not in json_keys(body)

    # The returned token is a real credential for the chosen scope.
    m2m = TestClient(main.app)
    ok = m2m.get("/api/v1/objects", headers={"Authorization": f"Bearer {body['token']}"})
    assert ok.status_code == 200, ok.text

    # It is never echoed by the list route.
    listed = c.get("/api/v1/admin/partner-sites", headers=headers)
    assert listed.status_code == 200
    rows = [i for i in listed.json()["items"] if i["id"] == body["id"]]
    assert rows and "token" not in rows[0]


def test_site_url_must_be_a_clean_https_origin():
    c, headers = _admin()
    for bad in (
        "http://cours.example.com",
        "https://user:pass@cours.example.com",
        "https://cours.example.com/?x=1",
        "https://cours.example.com/#top",
        "cours.example.com",
    ):
        r = _create(c, headers, site_url=bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    # A base path is allowed (course sites often live under one).
    ok = _create(c, headers, site_url="https://univ.example.com/cours/maths/")
    assert ok.status_code == 200, ok.text
    assert ok.json()["site_url"] == "https://univ.example.com/cours/maths"


def test_scopes_stay_data_plane():
    c, headers = _admin()
    assert _create(c, headers, scopes=["admin:read"]).status_code == 422
    assert _create(c, headers, scopes=[]).status_code == 422
    assert _create(c, headers, scopes=["nope"]).status_code == 422


def test_names_are_unique_per_space():
    c, headers = _admin()
    assert _create(c, headers, name="Portail").status_code == 200
    duplicate = _create(c, headers, name="portail")
    assert duplicate.status_code == 409, duplicate.text


def test_metadata_can_be_edited_and_ttl_cleared():
    c, headers = _admin()
    created = _create(c, headers, default_ttl_seconds=900, notes="v1").json()
    r = c.patch(
        f"/api/v1/admin/partner-sites/{created['id']}",
        json={"name": "Portail v2", "site_url": "https://new.example.com",
              "default_ttl_seconds": 21600, "notes": "v2"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Portail v2"
    assert body["site_url"] == "https://new.example.com"
    assert body["default_ttl_seconds"] == 21600
    assert body["notes"] == "v2"
    # Explicit null clears the recommendation instead of leaving the old value.
    cleared = c.patch(
        f"/api/v1/admin/partner-sites/{created['id']}",
        json={"default_ttl_seconds": None}, headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["default_ttl_seconds"] is None
    assert c.patch(
        f"/api/v1/admin/partner-sites/{uuid.uuid4()}",
        json={"notes": "x"}, headers=headers,
    ).status_code == 404


def test_revoking_the_identity_is_visible_and_cuts_access():
    c, headers = _admin()
    created = _create(c, headers).json()
    assert c.post(
        f"/api/v1/admin/identities/{created['identity_id']}/revoke", headers=headers
    ).status_code == 200
    listed = c.get("/api/v1/admin/partner-sites", headers=headers).json()["items"]
    row = next(i for i in listed if i["id"] == created["id"])
    assert row["identity"]["revoked_at"] is not None
    m2m = TestClient(main.app)
    refused = m2m.get("/api/v1/objects", headers={"Authorization": f"Bearer {created['token']}"})
    assert refused.status_code in (401, 403), refused.text


def test_delete_revokes_the_key_and_removes_the_site():
    c, headers = _admin()
    created = _create(c, headers).json()
    r = c.delete(
        f"/api/v1/admin/partner-sites/{created['id']}", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["identity_revoked"] is True
    rows = c.get("/api/v1/admin/partner-sites", headers=headers).json()["items"]
    assert all(i["id"] != created["id"] for i in rows)
    m2m = TestClient(main.app)
    refused = m2m.get(
        "/api/v1/objects", headers={"Authorization": f"Bearer {created['token']}"}
    )
    assert refused.status_code in (401, 403), refused.text
    # Idempotent from the client's point of view: the row is gone.
    assert c.delete(
        f"/api/v1/admin/partner-sites/{created['id']}", headers=headers
    ).status_code == 404


def test_non_admin_cannot_read_or_create():
    c, headers = _account(role="user")
    assert c.get("/api/v1/admin/partner-sites", headers=headers).status_code == 403
    assert _create(c, headers).status_code == 403


def json_keys(body):
    return set(body.keys())
