"""Issue #61: logical folder CRUD (offline, SQLite catalogue, no S3 endpoint).

Folders are human-owned catalogue metadata, never host directories. These tests
cover the CRUD surface, name/parent validation, duplicate and cycle refusal,
owner isolation, the human-only rule for service identities, and the folder
reference check on upload intents.
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
    # The default space id is a generated UUID v4, not a constant, so resolve it
    # from the seeded catalogue (see api/migrations.py).
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


def _make_identity(c, headers, space_id, scopes):
    r = c.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": "svc", "scopes": scopes,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _mk(c, headers, name, parent_id=None):
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = c.post("/api/v1/folders", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _names(items):
    return {i["name"] for i in items}


# ---------------------------------------------------------------------------
# CRUD lifecycle
# ---------------------------------------------------------------------------
def test_folder_crud_lifecycle():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    parent = _mk(c, headers, f"root-{tag}")
    child = _mk(c, headers, f"child-{tag}", parent_id=parent["id"])

    assert child["parent_id"] == parent["id"]
    assert parent["parent_id"] is None
    assert "id" in parent and "created_at" in parent

    # Root listing is owner-scoped and contains the parent, not the child.
    root = c.get("/api/v1/folders", headers=headers)
    assert root.status_code == 200
    assert parent["id"] in {i["id"] for i in root.json()["items"]}
    assert child["id"] not in {i["id"] for i in root.json()["items"]}

    # Children listing.
    kids = c.get("/api/v1/folders", params={"parent_id": parent["id"]}, headers=headers)
    assert kids.status_code == 200
    assert _names(kids.json()["items"]) == {f"child-{tag}"}

    # Metadata fetch.
    got = c.get(f"/api/v1/folders/{parent['id']}", headers=headers)
    assert got.status_code == 200 and got.json()["id"] == parent["id"]

    # Rename.
    r = c.patch(f"/api/v1/folders/{child['id']}", json={"name": f"renamed-{tag}"},
                headers=headers)
    assert r.status_code == 200 and r.json()["name"] == f"renamed-{tag}"

    # Delete refuses while children remain, then succeeds once empty.
    assert c.delete(f"/api/v1/folders/{parent['id']}", headers=headers).status_code == 409
    assert c.delete(f"/api/v1/folders/{child['id']}", headers=headers).status_code == 200
    assert c.get(f"/api/v1/folders/{child['id']}", headers=headers).status_code == 404
    assert c.delete(f"/api/v1/folders/{parent['id']}", headers=headers).status_code == 200


def test_missing_parent_and_missing_folder():
    c, headers = _admin()
    r = c.post("/api/v1/folders", json={"name": "x", "parent_id": str(uuid.uuid4())},
               headers=headers)
    assert r.status_code == 404
    assert c.get(f"/api/v1/folders/{uuid.uuid4()}", headers=headers).status_code == 404
    assert c.patch(f"/api/v1/folders/{uuid.uuid4()}", json={"name": "y"},
                   headers=headers).status_code == 404
    assert c.delete(f"/api/v1/folders/{uuid.uuid4()}", headers=headers).status_code == 404
    assert c.get("/api/v1/folders", params={"parent_id": str(uuid.uuid4())},
                 headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Uniqueness and name validation
# ---------------------------------------------------------------------------
def test_duplicate_name_is_refused_per_parent():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    a = _mk(c, headers, f"a-{tag}")
    b = _mk(c, headers, f"b-{tag}")
    # Same name under a different parent is fine.
    _mk(c, headers, f"dup-{tag}", parent_id=a["id"])
    _mk(c, headers, f"dup-{tag}", parent_id=b["id"])
    # Same name under the same parent is refused.
    assert c.post("/api/v1/folders", json={"name": f"dup-{tag}", "parent_id": a["id"]},
                  headers=headers).status_code == 409
    # Root-level duplicate is refused too.
    assert c.post("/api/v1/folders", json={"name": f"a-{tag}"},
                  headers=headers).status_code == 409


def test_rename_to_existing_sibling_is_refused():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    a = _mk(c, headers, f"a-{tag}")
    b = _mk(c, headers, f"b-{tag}")
    r = c.patch(f"/api/v1/folders/{b['id']}", json={"name": f"a-{tag}"}, headers=headers)
    assert r.status_code == 409


@pytest.mark.parametrize("bad", ["", "   ", ".", "..", "a/b", "a\\b", "a\x00b", "a\nb"])
def test_invalid_folder_names_are_rejected(bad):
    c, headers = _admin()
    r = c.post("/api/v1/folders", json={"name": bad}, headers=headers)
    assert r.status_code == 422, r.text


def test_patch_requires_a_field_and_non_null_name():
    c, headers = _admin()
    fid = _mk(c, headers, f"f-{uuid.uuid4().hex[:8]}")["id"]
    assert c.patch(f"/api/v1/folders/{fid}", json={}, headers=headers).status_code == 422
    assert c.patch(f"/api/v1/folders/{fid}", json={"name": None},
                   headers=headers).status_code == 422


# ---------------------------------------------------------------------------
# Cycle and depth guards
# ---------------------------------------------------------------------------
def test_move_into_own_subtree_is_refused():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    a = _mk(c, headers, f"a-{tag}")
    b = _mk(c, headers, f"b-{tag}", parent_id=a["id"])
    # a cannot become a child of its own descendant b...
    assert c.patch(f"/api/v1/folders/{a['id']}", json={"parent_id": b["id"]},
                   headers=headers).status_code == 409
    # ...nor of itself.
    assert c.patch(f"/api/v1/folders/{a['id']}", json={"parent_id": a["id"]},
                   headers=headers).status_code == 409
    # Moving b back to the root is allowed.
    r = c.patch(f"/api/v1/folders/{b['id']}", json={"parent_id": None}, headers=headers)
    assert r.status_code == 200 and r.json()["parent_id"] is None


def test_folder_depth_is_capped():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    created = [_mk(c, headers, f"d0-{tag}")["id"]]
    for i in range(main.MAX_FOLDER_DEPTH - 1):
        created.append(_mk(c, headers, f"d{i + 1}-{tag}", parent_id=created[-1])["id"])
    # One level deeper than the cap is refused.
    r = c.post("/api/v1/folders", json={"name": f"too-deep-{tag}", "parent_id": created[-1]},
               headers=headers)
    assert r.status_code == 409
    # Moving another folder under the deepest node would also exceed the cap.
    other = _mk(c, headers, f"other-{tag}")
    assert c.patch(f"/api/v1/folders/{other['id']}",
                   json={"parent_id": created[-1]}, headers=headers).status_code == 409
    # ...but under the node one level higher it fits exactly.
    ok = c.patch(f"/api/v1/folders/{other['id']}",
                 json={"parent_id": created[-2]}, headers=headers)
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------------------
# Owner isolation and the human-only rule
# ---------------------------------------------------------------------------
def test_folders_are_owner_scoped():
    c, headers = _admin()
    n1, p1 = _ordinary_user()
    n2, p2 = _ordinary_user()
    u1, h1 = _login(n1, p1)
    u2, h2 = _login(n2, p2)

    fid = _mk(u1, h1, f"mine-{uuid.uuid4().hex[:8]}")["id"]

    # The other user sees nothing of it.
    assert u2.get("/api/v1/folders", headers=h2).json()["items"] == []
    assert u2.get(f"/api/v1/folders/{fid}", headers=h2).status_code == 404
    assert u2.patch(f"/api/v1/folders/{fid}", json={"name": "x"}, headers=h2).status_code == 404
    assert u2.delete(f"/api/v1/folders/{fid}", headers=h2).status_code == 404
    assert u2.post("/api/v1/folders", json={"name": "x", "parent_id": fid},
                   headers=h2).status_code == 404
    # Even an administrator does not own the user's folder.
    assert c.get(f"/api/v1/folders/{fid}", headers=headers).status_code == 404


def test_service_identity_cannot_manage_folders():
    c, headers = _admin()
    token = _make_identity(c, headers, _default_space_id(),
                           ["objects:read", "objects:write", "objects:delete"])
    auth = {"Authorization": f"Bearer {token}"}
    assert c.get("/api/v1/folders", headers=auth).status_code == 403
    assert c.post("/api/v1/folders", json={"name": "x"}, headers=auth).status_code == 403
    assert c.get(f"/api/v1/folders/{uuid.uuid4()}", headers=auth).status_code == 403
    assert c.patch(f"/api/v1/folders/{uuid.uuid4()}", json={"name": "x"},
                   headers=auth).status_code == 403
    assert c.delete(f"/api/v1/folders/{uuid.uuid4()}", headers=auth).status_code == 403


def test_anonymous_and_missing_csrf_are_refused():
    anon = TestClient(main.app)
    assert anon.get("/api/v1/folders").status_code == 401
    assert anon.post("/api/v1/folders", json={"name": "x"}).status_code == 401

    n, p = _ordinary_user()
    u, _ = _login(n, p)
    # A valid session without the CSRF token cannot mutate.
    assert u.post("/api/v1/folders", json={"name": "x"}).status_code == 403


# ---------------------------------------------------------------------------
# Folder reference on upload intents
# ---------------------------------------------------------------------------
def test_upload_intent_validates_folder_ownership():
    c, headers = _admin()
    n1, p1 = _ordinary_user()
    n2, p2 = _ordinary_user()
    u1, h1 = _login(n1, p1)
    u2, h2 = _login(n2, p2)

    fid = _mk(u1, h1, f"mine-{uuid.uuid4().hex[:8]}")["id"]

    # The owner can target their own folder.
    ok = u1.post("/api/v1/objects/upload-intents",
                 json={"display_name": "a.txt", "size_bytes": 1, "folder_id": fid},
                 headers=h1)
    assert ok.status_code == 200, ok.text
    # Deleting a folder that still holds an object is refused.
    assert u1.delete(f"/api/v1/folders/{fid}", headers=h1).status_code == 409

    # Another user cannot target it, and an unknown folder is refused.
    assert u2.post("/api/v1/objects/upload-intents",
                   json={"display_name": "b.txt", "size_bytes": 1, "folder_id": fid},
                   headers=h2).status_code == 403
    assert u1.post("/api/v1/objects/upload-intents",
                   json={"display_name": "c.txt", "size_bytes": 1,
                         "folder_id": str(uuid.uuid4())},
                   headers=h1).status_code == 403
    # A service identity never owns folders.
    token = _make_identity(c, headers, _default_space_id(), ["objects:write"])
    assert c.post("/api/v1/objects/upload-intents",
                  json={"display_name": "d.txt", "size_bytes": 1, "folder_id": fid},
                  headers={"Authorization": f"Bearer {token}"}).status_code == 403
