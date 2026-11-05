"""Public folder share links (``/f/<token>``).

A folder share is the object-share capability model applied to a folder tree:
one unauthenticated, expiring, revocable, read-only link. These tests pin the
properties that make it acceptable:

- the token is stored only as a SHA-256 fingerprint and returned once;
- the landing page is safe HTML (escaped names, strict CSP, no-store/noindex);
- each file download is a 302 to a short-lived presigned GET, never a proxy;
- subfolders are included recursively, but nothing outside the shared subtree
  is reachable, even with a guessed id;
- malformed, unknown, expired, exhausted and revoked links are indistinguishable;
- creation/revocation are human-only, CSRF-protected and owner-scoped;
- every event is audited by share id, never by token.

Offline: SQLite catalogue and local presigning only, no S3 endpoint is contacted.
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
from api import shares  # noqa: E402
from api.auth import hash_password  # noqa: E402
from tests import catalogue_sql  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def _account(role="user"):
    """A fresh account, isolated from objects created by other test modules."""
    username = f"folder-share-{uuid.uuid4().hex[:10]}"
    password = "folder-share-test-password"
    main.repo.create_user(username, hash_password(password), role=role)
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _folder(c, headers, name=None, parent_id=None):
    body = {"name": name or f"folder-{uuid.uuid4().hex[:10]}"}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = c.post("/api/v1/folders", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _object(c, headers, folder_id=None, name="contrat.pdf",
            content_type="application/pdf"):
    body = {
        "display_name": name, "size_bytes": 4096, "content_type": content_type,
    }
    if folder_id is not None:
        body["folder_id"] = folder_id
    r = c.post("/api/v1/objects/upload-intents", json=body, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    main.repo.mark_available(oid, 4096, uuid.uuid4().hex)
    return oid


def _share(c, headers, fid, **body):
    r = c.post(f"/api/v1/folders/{fid}/share", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _page(token, **params):
    return client.get(f"/f/{token}", params=params, follow_redirects=False)


def _download(token, oid, **params):
    return client.get(f"/f/{token}/o/{oid}", params=params, follow_redirects=False)


def test_folder_share_round_trip_lists_tree_and_redirects_files():
    c, headers = _account(role="admin")
    root = _folder(c, headers, "Contrats")
    child = _folder(c, headers, "Signés", parent_id=root["id"])
    root_file = _object(c, headers, root["id"], "racine.pdf")
    child_file = _object(c, headers, child["id"], "signe.pdf")
    _object(c, headers, None, "hors-dossier.pdf")  # never part of the share

    created = _share(c, headers, root["id"])
    token = created["token"]
    assert shares.is_well_formed(token)
    assert created["url"].endswith(f"/f/{token}")
    assert created["folder_id"] == root["id"]

    # Only the fingerprint is stored.
    row = main.repo.get_folder_share(created["id"])
    assert row["token_hash"] == shares.fingerprint(token)
    assert token not in json.dumps(dict(row))

    page = _page(token)
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "Contrats" in page.text and "Signés" in page.text
    assert "racine.pdf" in page.text and "hors-dossier.pdf" not in page.text

    # Navigating into the child lists its files, still inside the subtree.
    sub = _page(token, d=child["id"])
    assert sub.status_code == 200
    assert "signe.pdf" in sub.text

    # Both files redirect to a short-lived presigned GET (never proxied).
    for oid in (root_file, child_file):
        r = _download(token, oid)
        assert r.status_code == 302, r.text
        location = r.headers["location"]
        assert location.startswith(main.settings.s3_endpoint)
        assert "X-Amz-Signature" in location
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-robots-tag"] == "noindex, nofollow"

    # A folder or object outside the shared tree is indistinguishable from 404.
    outside = _folder(c, headers, "Privé")
    outside_file = _object(c, headers, outside["id"], "secret.pdf")
    assert _page(token, d=outside["id"]).status_code == 404
    assert _download(token, outside_file).status_code == 404
    assert _download(token, _object(c, headers, None, "unfiled.pdf")).status_code == 404
    assert _page(token, d=str(uuid.uuid4())).status_code == 404


def test_unknown_malformed_expired_and_revoked_links_are_indistinguishable():
    for bad in ("short", "a" * 42, "a" * 44, shares.new_token()):
        r = _page(bad)
        assert r.status_code == 404
        assert "Lien introuvable" in r.text
    # Path traversal never reaches the route at all (client/edge normalises it).
    assert _page("../" + "a" * 40).status_code == 404

    c, headers = _account(role="admin")
    root = _folder(c, headers)
    oid = _object(c, headers, root["id"])
    created = _share(c, headers, root["id"], expires_in=60)

    # A valid link renders the page; the failure body is the same for every
    # failure mode, and a malformed/unknown token gets it too.
    assert _page(created["token"]).status_code == 200
    not_found_page = _page(shares.new_token()).text
    assert "Lien introuvable" in not_found_page

    catalogue_sql.execute(
        "UPDATE folder_shares SET expires_at = ? WHERE id = ?",
        (int(time.time()) - 1, created["id"]),
    )
    expired = _page(created["token"])
    assert expired.status_code == 404
    assert expired.text == not_found_page
    assert _download(created["token"], oid).status_code == 404

    # A fresh link, revoked immediately, is dead for both routes.
    live = _share(c, headers, root["id"])
    r = c.delete(
        f"/api/v1/folders/{root['id']}/shares/{live['id']}", headers=headers
    )
    assert r.status_code == 200, r.text
    assert _page(live["token"]).status_code == 404
    assert _download(live["token"], oid).status_code == 404


def test_max_uses_counts_downloads_not_page_views():
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    a = _object(c, headers, root["id"], "a.pdf")
    b = _object(c, headers, root["id"], "b.pdf")
    created = _share(c, headers, root["id"], max_uses=2)

    # Opening the listing is free.
    assert _page(created["token"]).status_code == 200
    assert _page(created["token"]).status_code == 200

    assert _download(created["token"], a).status_code == 302
    assert _download(created["token"], b).status_code == 302
    # Both uses consumed: the link is now dead, including its listing.
    assert _download(created["token"], a).status_code == 404
    assert _page(created["token"]).status_code == 404
    assert main.repo.get_folder_share(created["id"])["use_count"] == 2


def test_only_available_objects_in_the_subtree_are_downloadable():
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    pending = c.post("/api/v1/objects/upload-intents", json={
        "display_name": "pending.pdf", "size_bytes": 10, "folder_id": root["id"],
    }, headers=headers).json()["id"]
    created = _share(c, headers, root["id"])
    assert _download(created["token"], pending).status_code == 404


def test_navigation_stops_at_the_shared_subtree():
    c, headers = _account(role="admin")
    parent = _folder(c, headers, "Parent")
    child = _folder(c, headers, "Enfant", parent_id=parent["id"])
    grandchild = _folder(c, headers, "Petit-enfant", parent_id=child["id"])
    # Share the middle folder: its parent and siblings must stay unreachable.
    sibling = _folder(c, headers, "Frère", parent_id=parent["id"])
    created = _share(c, headers, child["id"])

    assert _page(created["token"]).status_code == 200
    assert _page(created["token"], d=grandchild["id"]).status_code == 200
    assert _page(created["token"], d=parent["id"]).status_code == 404
    assert _page(created["token"], d=sibling["id"]).status_code == 404


def test_names_are_escaped_in_the_public_page():
    c, headers = _account(role="admin")
    root = _folder(c, headers, '<img src=x onerror=alert(1)>')
    _object(c, headers, root["id"], '<svg onload=alert(2)>.pdf')
    created = _share(c, headers, root["id"])

    body = _page(created["token"]).text
    assert "<img src=x" not in body
    assert "<svg onload" not in body
    assert "&lt;img src=x" in body
    assert "&lt;svg onload" in body


def test_create_requires_csrf_and_is_human_only_and_owner_scoped():
    c, headers = _account(role="admin")
    root = _folder(c, headers)

    assert c.post(f"/api/v1/folders/{root['id']}/share", json={}).status_code == 403

    # A machine token cannot mint a link.
    me = c.get("/api/v1/me", headers=headers).json()
    identity = c.post("/api/v1/admin/identities", json={
        "space_id": me["space_id"], "name": "folder-share-probe",
        "scopes": ["objects:read", "objects:write"],
    }, headers=headers)
    assert identity.status_code == 200, identity.text
    r = client.post(
        f"/api/v1/folders/{root['id']}/share", json={},
        headers={"Authorization": f"Bearer {identity.json()['token']}"},
    )
    assert r.status_code == 403, r.text

    # Another human cannot see the folder at all.
    other, other_headers = _account()
    assert other.post(
        f"/api/v1/folders/{root['id']}/share", json={}, headers=other_headers
    ).status_code == 404
    assert other.get(
        f"/api/v1/folders/{root['id']}/shares", headers=other_headers
    ).status_code == 404


def test_expiry_above_the_ceiling_is_refused():
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    r = c.post(f"/api/v1/folders/{root['id']}/share",
               json={"expires_in": main.settings.share_ttl_max + 1}, headers=headers)
    assert r.status_code == 422, r.text
    assert _share(c, headers, root["id"],
                  expires_in=main.settings.share_ttl_max)["expires_in"] == \
        main.settings.share_ttl_max


def test_revocation_is_idempotent_and_creator_only():
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    created = _share(c, headers, root["id"])

    r = c.delete(f"/api/v1/folders/{root['id']}/shares/{created['id']}", headers=headers)
    assert r.status_code == 200
    first = r.json()["revoked_at"]
    again = c.delete(
        f"/api/v1/folders/{root['id']}/shares/{created['id']}", headers=headers
    )
    assert again.status_code == 200 and again.json()["revoked_at"] == first

    # A share row that names someone else cannot be revoked through this route.
    other = _share(c, headers, root["id"])
    catalogue_sql.execute(
        "UPDATE folder_shares SET created_by = ? WHERE id = ?",
        (str(uuid.uuid4()), other["id"]),
    )
    assert c.delete(
        f"/api/v1/folders/{root['id']}/shares/{other['id']}", headers=headers
    ).status_code == 403


def test_folder_deletion_leaves_an_inert_link():
    """Deleting a folder must never be blocked by a link; the link then 404s."""
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    created = _share(c, headers, root["id"])
    assert c.delete(f"/api/v1/folders/{root['id']}", headers=headers).status_code == 200
    assert _page(created["token"]).status_code == 404
    # The row survives so the audit trail still resolves; it is just inert.
    assert main.repo.get_folder_share(created["id"]) is not None


def test_audit_records_folder_events_without_the_token():
    c, headers = _account(role="admin")
    root = _folder(c, headers)
    oid = _object(c, headers, root["id"])
    created = _share(c, headers, root["id"])
    _page(created["token"])
    _download(created["token"], oid)
    c.delete(f"/api/v1/folders/{root['id']}/shares/{created['id']}", headers=headers)

    with open(main.audit_path(), encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    related = [e for e in events if e.get("folder_share_id") == created["id"]]
    actions = {e["action"] for e in related}
    assert {
        "folder-share-create", "folder-share-open",
        "folder-share-access", "folder-share-revoke",
    } <= actions

    raw = json.dumps(related)
    assert created["token"] not in raw
    assert "X-Amz-Signature" not in raw
