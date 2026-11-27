"""Authoritative duplicate-scan endpoint (offline, SQLite catalogue).

The browser used to decide duplicates from a stale client-side folder tree.
These tests pin the server contract: root/folder resolution is owner-scoped and
strict (no same-named-folder fallback), only available objects are returned,
input is bounded/validated, and the audit trail carries counts but no paths.
"""
import hashlib
import json
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

SHA = hashlib.sha256(b"aura-duplicate-scan").hexdigest()
ROW_KEYS = {"id", "display_name", "size_bytes", "checksum_sha256"}


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _login(c, username, password):
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _account(role="user"):
    """Fresh isolated human account, so owner/folder scoping is unambiguous."""
    name = f"dupscan-{uuid.uuid4().hex[:10]}"
    password = "dupscan-password"
    main.repo.create_user(name, hash_password(password), role=role)
    c = TestClient(main.app)
    return c, _login(c, name, password)


def _admin():
    c = TestClient(main.app)
    headers = _login(c, "admin", os.environ["AURA_API_ADMIN_PASSWORD"])
    return c, headers


def _folder(c, headers, name, parent_id=None):
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = c.post("/api/v1/folders", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _intent(c, headers, name, folder_id=None, size=11):
    body = {"display_name": name, "size_bytes": size}
    if folder_id is not None:
        body["folder_id"] = folder_id
    r = c.post("/api/v1/objects/upload-intents", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _available(c, headers, name, folder_id=None, size=11, checksum=SHA):
    oid = _intent(c, headers, name, folder_id=folder_id, size=size)
    main.repo.mark_available(oid, size, checksum)
    return oid


def _scan(c, headers, items):
    return c.post("/api/v1/objects/duplicate-scan", json={"items": items}, headers=headers)


def _item(parent, name="rapport.pdf", size=11, checksum=None):
    item = {"parentPath": parent, "name": name, "sizeBytes": size}
    if checksum is not None:
        item["sha256"] = checksum
    return item


def _ids(rows):
    return {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# Root destination: only available, unfiled objects, with a bounded page walk.
# ---------------------------------------------------------------------------
def test_root_scan_returns_only_available_root_objects(monkeypatch):
    c, headers = _account()
    # Force several pages so the pagination loop is actually exercised.
    monkeypatch.setattr(main, "_DUPLICATE_SCAN_PAGE", 2)

    live = [_available(c, headers, f"root-{n}.pdf", size=n + 1) for n in range(5)]
    pending = _intent(c, headers, "pending.pdf")
    deleted = _available(c, headers, "deleted.pdf")
    main.repo.set_status(deleted, "deleted")
    folder = _folder(c, headers, f"folder-{uuid.uuid4().hex[:8]}")
    filed = _available(c, headers, "filed.pdf", folder_id=folder["id"])

    r = _scan(c, headers, [_item(""), _item("")])  # duplicate paths collapse
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["byParent"]) == {""}
    assert body["unresolved"] == []
    rows = body["byParent"][""]
    assert _ids(rows) == set(live)
    assert {pending, deleted, filed}.isdisjoint(_ids(rows))
    for row in rows:
        assert set(row) == ROW_KEYS
        assert row["size_bytes"] in range(1, 6)
        assert row["checksum_sha256"] == SHA
        assert row["display_name"].startswith("root-")


# ---------------------------------------------------------------------------
# Nested destinations: strict chain, client path normalization, no leaf fallback.
# ---------------------------------------------------------------------------
def test_nested_chain_is_strict_and_paths_are_normalized():
    c, headers = _account()
    parent = _folder(c, headers, "Livres")
    child = _folder(c, headers, "2026", parent_id=parent["id"])
    decoy = _folder(c, headers, "2026")  # same leaf, different chain
    nested_obj = _available(c, headers, "rapport.pdf", folder_id=child["id"])
    decoy_obj = _available(c, headers, "rapport.pdf", folder_id=decoy["id"])
    other = _folder(c, headers, "Archive")
    other_obj = _available(c, headers, "rapport.pdf", folder_id=other["id"])

    r = _scan(c, headers, [
        _item("Livres\\2026"),                  # backslash separator
        _item("Livres/./2026"),                 # "." segment
        _item("Livres/../2026"),                # ".." is dropped, not resolved
        _item("./Livres/2026/"),                # leading "." and trailing separator
        _item("Archive/2026"),                  # parent exists, child does not
        _item("Livres/2026/New"),               # broken below a resolved parent
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["byParent"]) == {"Livres/2026"}
    assert _ids(body["byParent"]["Livres/2026"]) == {nested_obj}
    assert {decoy_obj, other_obj}.isdisjoint(_ids(body["byParent"]["Livres/2026"]))
    assert body["unresolved"] == ["Archive/2026", "Livres/2026/New"]
    assert set(body["unresolved"]).isdisjoint(body["byParent"])


def test_folder_chain_is_owner_scoped():
    alice, alice_h = _account()
    bob, bob_h = _account()
    a_folder = _folder(alice, alice_h, "Partages")
    b_folder = _folder(bob, bob_h, "Partages")
    b_only = _folder(bob, bob_h, "Prive")
    a_obj = _available(alice, alice_h, "a.pdf", folder_id=a_folder["id"])
    b_obj = _available(bob, bob_h, "b.pdf", folder_id=b_folder["id"])

    r = _scan(alice, alice_h, [
        _item("Partages", "a.pdf"),
        _item("Prive", "b.pdf"),
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["byParent"]) == {"Partages"}
    assert _ids(body["byParent"]["Partages"]) == {a_obj}
    assert b_obj not in _ids(body["byParent"]["Partages"])
    assert body["unresolved"] == ["Prive"]  # Bob's folder is invisible to Alice


# ---------------------------------------------------------------------------
# Input validation and authentication.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("item", [
    {"parentPath": "", "name": "", "sizeBytes": 1},
    {"parentPath": "", "name": "   ", "sizeBytes": 1},
    {"parentPath": "", "name": "a.pdf", "sizeBytes": -1},
    {"parentPath": "", "name": "a.pdf", "sizeBytes": 1, "sha256": "abc"},
    {"parentPath": "", "name": "a.pdf", "sizeBytes": 1, "sha256": "a" * 63},
    {"parentPath": "", "name": "a.pdf", "sizeBytes": 1, "sha256": "z" * 64},
    {"parentPath": "", "name": "a.pdf"},                       # missing sizeBytes
    {"parentPath": 12, "name": "a.pdf", "sizeBytes": 1},
    {"parentPath": "", "name": "a.pdf", "sizeBytes": 1, "extra": True},
])
def test_invalid_fingerprints_are_rejected(item):
    c, headers = _account()
    assert _scan(c, headers, [item]).status_code == 422


def test_item_count_limit_and_body_shape_are_enforced():
    c, headers = _account()
    assert _scan(c, headers, [_item("")] * 5001).status_code == 422
    assert c.post("/api/v1/objects/duplicate-scan",
                  json={"wrong": []}, headers=headers).status_code == 422
    # The documented boundary is accepted.
    assert _scan(c, headers, [_item("")] * 5000).status_code == 200


def test_optional_checksum_and_uppercase_hex_are_accepted():
    c, headers = _account()
    r = _scan(c, headers, [
        _item(""),                              # sha256 omitted entirely
        _item("", "b.pdf", 1, "A" * 64),        # uppercase hex
    ])
    assert r.status_code == 200, r.text
    assert set(r.json()["byParent"]) == {""}


def test_duplicate_scan_requires_authentication_and_csrf():
    body = {"items": [_item("")]}
    assert client.post("/api/v1/objects/duplicate-scan", json=body).status_code == 401
    c = TestClient(main.app)
    name = f"dupscan-csrf-{uuid.uuid4().hex[:8]}"
    main.repo.create_user(name, hash_password("dupscan-password"), role="user")
    assert _login(c, name, "dupscan-password")
    # Human POSTs are CSRF-protected like any other mutation, even though this
    # route is a read: the body can be large and is not idempotent in effect.
    assert c.post("/api/v1/objects/duplicate-scan", json=body).status_code == 403


# ---------------------------------------------------------------------------
# Service identities and audit: allowed, with counts only (no names or paths).
# ---------------------------------------------------------------------------
def test_service_identity_scan_and_audit_carry_counts_only(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AURA_AUDIT_LOG", str(log))
    admin, admin_h = _admin()
    suffix = uuid.uuid4().hex[:8]
    app = admin.post("/api/v1/admin/applications",
                     json={"name": f"dupscan-app-{suffix}"}, headers=admin_h)
    assert app.status_code == 200, app.text
    space = admin.post("/api/v1/admin/spaces", json={
        "application_id": app.json()["id"], "name": f"dupscan-space-{suffix}",
        "environment": "test",
    }, headers=admin_h)
    assert space.status_code == 200, space.text
    identity = admin.post("/api/v1/admin/identities", json={
        "space_id": space.json()["id"], "name": f"dupscan-svc-{suffix}",
        "scopes": ["objects:read", "objects:write"],
    }, headers=admin_h)
    assert identity.status_code == 200, identity.text
    svc_h = {"Authorization": f"Bearer {identity.json()['token']}"}

    oid = _available(admin, svc_h, "rapport.pdf")
    r = _scan(admin, svc_h, [
        _item("", "rapport.pdf"),
        _item("Nouveau/Dossier", "rapport.pdf"),
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["byParent"]) == {""}
    assert _ids(body["byParent"][""]) == {oid}
    # Folders are human-owned: a service cannot resolve a folder path at all.
    assert body["unresolved"] == ["Nouveau/Dossier"]

    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    events = [rec for rec in records if rec.get("action") == "duplicate-scan"]
    assert len(events) == 1
    assert events[0]["item_count"] == 2
    assert events[0]["unresolved_count"] == 1
    blob = log.read_text(encoding="utf-8")
    assert "rapport.pdf" not in blob
    assert "Nouveau/Dossier" not in blob
