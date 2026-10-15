"""Flat folder listing (#62 follow-up): ``GET /api/v1/folders?all=true``.

The per-level endpoint stays the default; ``all=true`` returns the caller's whole
tree as a flat list (each item still carries ``parent_id``) so a client rebuilds
the hierarchy from one request instead of walking levels. Offline (SQLite); no S3
endpoint is contacted.
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
from api import authz  # noqa: E402
from api.auth import hash_password  # noqa: E402

client = TestClient(main.app)


def _default_space_id():
    return main.repo.default_scope()[1]


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


def _ordinary_user():
    name = f"user-{uuid.uuid4().hex[:8]}"
    password = "user-password-123"
    main.repo.create_user(name, hash_password(password), role="user",
                          space_id=_default_space_id())
    return name, password


def _mk(c, headers, name, parent_id=None):
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = c.post("/api/v1/folders", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_all_returns_the_whole_tree_flat():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    root = _mk(c, headers, f"root-{tag}")
    child = _mk(c, headers, f"child-{tag}", parent_id=root["id"])
    grand = _mk(c, headers, f"grand-{tag}", parent_id=child["id"])

    r = c.get("/api/v1/folders", params={"all": "true"}, headers=headers)
    assert r.status_code == 200, r.text
    by_id = {f["id"]: f for f in r.json()["items"]}
    # Every level is present in the single response, with parent_id intact.
    assert by_id[root["id"]]["parent_id"] is None
    assert by_id[child["id"]]["parent_id"] == root["id"]
    assert by_id[grand["id"]]["parent_id"] == child["id"]

    # Ordering is deterministic (by name), so the payload is stable across calls.
    names = [f["name"] for f in r.json()["items"]]
    assert names == sorted(names)


def test_per_level_listing_is_unchanged():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    parent = _mk(c, headers, f"p-{tag}")
    child = _mk(c, headers, f"c-{tag}", parent_id=parent["id"])

    root = c.get("/api/v1/folders", headers=headers)
    assert root.status_code == 200
    root_ids = {i["id"] for i in root.json()["items"]}
    assert parent["id"] in root_ids and child["id"] not in root_ids

    kids = c.get("/api/v1/folders", params={"parent_id": parent["id"]}, headers=headers)
    assert {i["id"] for i in kids.json()["items"]} == {child["id"]}

    # all=false behaves like the default (root level only).
    explicit = c.get("/api/v1/folders", params={"all": "false"}, headers=headers)
    assert {i["id"] for i in explicit.json()["items"]} == root_ids


def test_all_combined_with_parent_id_is_refused():
    c, headers = _admin()
    r = c.get(
        "/api/v1/folders",
        params={"all": "true", "parent_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 422


def test_all_is_owner_scoped():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    admin_folder = _mk(c, headers, f"admin-{tag}")

    name, password = _ordinary_user()
    u, uh = _login(name, password)
    r = u.get("/api/v1/folders", params={"all": "true"}, headers=uh)
    assert r.status_code == 200
    assert admin_folder["id"] not in {f["id"] for f in r.json()["items"]}


def test_service_identity_and_anonymous_are_refused():
    c, headers = _admin()
    r = c.post("/api/v1/admin/identities", json={
        "space_id": _default_space_id(), "name": "svc", "scopes": ["objects:read"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.get("/api/v1/folders", params={"all": "true"}, headers=auth).status_code == 403

    anon = TestClient(main.app)
    assert anon.get("/api/v1/folders", params={"all": "true"}).status_code == 401
