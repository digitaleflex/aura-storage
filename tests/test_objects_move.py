"""Issue #62 follow-up: file/unfile an object in a logical folder.

``PATCH /api/v1/objects/{oid}`` sets ``folder_id`` (null = root) as catalogue
metadata. It is human-only (folders are human-owned) and owner-scoped: an object or
target folder outside the caller's scope is a 404, never a 403. Offline (SQLite);
upload intents only create a pending row and presign a URL against a dummy endpoint.
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


def _new_folder(c, headers, name):
    r = c.post("/api/v1/folders", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(c, headers, name):
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": name, "size_bytes": 1}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _folder_of(c, headers, folder_id):
    if folder_id is None:
        params = {"folder_id": "root"}
    else:
        params = {"folder_id": folder_id}
    r = c.get("/api/v1/objects", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {i["id"] for i in r.json()["items"]}


def test_move_object_into_folder_and_back():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    fid = _new_folder(c, headers, f"dest-{tag}")
    oid = _upload(c, headers, f"obj-{tag}.txt")

    assert oid in _folder_of(c, headers, None)
    assert oid not in _folder_of(c, headers, fid)

    # File it.
    r = c.patch(f"/api/v1/objects/{oid}", json={"folder_id": fid}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["folder_id"] == fid
    assert oid in _folder_of(c, headers, fid)
    assert oid not in _folder_of(c, headers, None)

    # Unfile it (explicit null back to the root level).
    r = c.patch(f"/api/v1/objects/{oid}", json={"folder_id": None}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["folder_id"] is None
    assert oid in _folder_of(c, headers, None)


def test_move_validation_and_missing_targets():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    oid = _upload(c, headers, f"obj-{tag}.txt")

    # A malformed folder id is a client error.
    assert c.patch(f"/api/v1/objects/{oid}", json={"folder_id": "not-a-uuid"},
                   headers=headers).status_code == 422
    # An empty body changes nothing.
    assert c.patch(f"/api/v1/objects/{oid}", json={}, headers=headers).status_code == 422
    # Unknown object.
    assert c.patch(f"/api/v1/objects/{uuid.uuid4()}", json={"folder_id": None},
                   headers=headers).status_code == 404
    # Unknown folder.
    assert c.patch(f"/api/v1/objects/{oid}", json={"folder_id": str(uuid.uuid4())},
                   headers=headers).status_code == 404


def test_move_is_owner_scoped():
    c, headers = _admin()
    n1, p1 = _ordinary_user()
    n2, p2 = _ordinary_user()
    u1, h1 = _login(n1, p1)
    u2, h2 = _login(n2, p2)

    tag = uuid.uuid4().hex[:8]
    my_folder = _new_folder(u1, h1, f"mine-{tag}")
    my_object = _upload(u1, h1, f"mine-{tag}.txt")

    # A user cannot see or move another user's object.
    assert u2.patch(f"/api/v1/objects/{my_object}", json={"folder_id": None},
                    headers=h2).status_code == 404
    # ...nor file their own object into another user's folder.
    their_object = _upload(u2, h2, f"theirs-{tag}.txt")
    assert u2.patch(f"/api/v1/objects/{their_object}", json={"folder_id": my_folder},
                    headers=h2).status_code == 404
    # The owner can target their own folder.
    ok = u1.patch(f"/api/v1/objects/{my_object}", json={"folder_id": my_folder},
                  headers=h1)
    assert ok.status_code == 200 and ok.json()["folder_id"] == my_folder


def test_move_is_human_only_and_needs_csrf():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    oid = _upload(c, headers, f"obj-{tag}.txt")

    # A service identity cannot file objects: folders are human-owned.
    r = c.post("/api/v1/admin/identities", json={
        "space_id": _default_space_id(), "name": "svc",
        "scopes": ["objects:write"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.patch(f"/api/v1/objects/{oid}", json={"folder_id": None},
                   headers=auth).status_code == 403

    # A valid human session without the CSRF header cannot mutate.
    n, p = _ordinary_user()
    u, _ = _login(n, p)
    assert u.patch(f"/api/v1/objects/{oid}", json={"folder_id": None}).status_code == 403
    # An anonymous caller is refused outright.
    assert TestClient(main.app).patch(
        f"/api/v1/objects/{oid}", json={"folder_id": None}
    ).status_code == 401
