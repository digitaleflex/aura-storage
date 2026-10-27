"""Tags, ordered packs and their public JSON manifest."""
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


def _admin():
    username = f"pack-{uuid.uuid4().hex[:10]}"
    password = "pack-test-password"
    main.repo.create_user(username, hash_password(password), role="admin")
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _object(c, headers, size=100, name="cours.pdf"):
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": name, "size_bytes": size, "content_type": "application/pdf",
    }, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    main.repo.mark_available(oid, size, uuid.uuid4().hex)
    return oid


def _tags(c, headers, oid, tags):
    return c.put(f"/api/v1/objects/{oid}/tags", json={"tags": tags}, headers=headers)


def test_tags_are_normalized_filterable_and_validated():
    c, headers = _admin()
    a, b = _object(c, headers, name="algebre.pdf"), _object(c, headers, name="autre.pdf")
    r = _tags(c, headers, a, ["Maths", "L1", "maths", "  "])
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["l1", "maths"]

    filtered = c.get("/api/v1/objects?tag=maths", headers=headers).json()["items"]
    assert [i["id"] for i in filtered] == [a]
    assert c.get("/api/v1/objects?tag=nope", headers=headers).json()["items"] == []
    assert c.get(f"/api/v1/objects/{a}", headers=headers).json()["tags"] == ["l1", "maths"]

    for bad in (["Has Space"], ["é"], ["x" * 33], [f"t{i}" for i in range(21)]):
        assert _tags(c, headers, a, bad).status_code == 422, bad
    # A service identity may not tag (human-only).
    token = c.post("/api/v1/admin/identities", json={
        "space_id": main.repo.list_spaces()[0]["id"],
        "name": "tag-service", "scopes": ["objects:write"],
    }, headers=headers).json()
    assert _tags(
        TestClient(main.app), {"Authorization": f"Bearer {token['token']}"}, a, ["x"]
    ).status_code == 403


def test_pack_order_publication_and_manifest():
    c, headers = _admin()
    a, b = _object(c, headers, name="intro.pdf"), _object(c, headers, name="suite.pdf")
    slug = f"pack-{uuid.uuid4().hex[:8]}"
    created = c.post("/api/v1/collections", json={
        "slug": slug, "title": "Maths L1", "description": "Semestre 1",
    }, headers=headers)
    assert created.status_code == 200, created.text
    cid = created.json()["id"]

    # Publish requires at least one item.
    assert c.patch(f"/api/v1/collections/{cid}", json={"published": True},
                   headers=headers).status_code == 422
    ordered = c.put(f"/api/v1/collections/{cid}/items",
                    json={"object_ids": [b, a]}, headers=headers)
    assert ordered.status_code == 200, ordered.text
    assert ordered.json()["item_count"] == 2

    # Publish the first object so the manifest exposes exactly one URL.
    assert c.put(f"/api/v1/objects/{b}/publication",
                 json={"slug": f"{slug}-b", "published": True},
                 headers=headers).status_code == 200
    assert c.patch(f"/api/v1/collections/{cid}", json={"published": True},
                   headers=headers).status_code == 200

    manifest = client.get(f"/p/{slug}.json")
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["title"] == "Maths L1"
    assert [i["id"] for i in body["items"]] == [b, a]
    assert body["items"][0]["url"] == f"/m/{slug}-b"
    assert body["items"][1]["url"] is None

    # Unpublishing hides the manifest.
    assert c.patch(f"/api/v1/collections/{cid}", json={"published": False},
                   headers=headers).status_code == 200
    assert client.get(f"/p/{slug}.json").status_code == 404

    # Deleting the pack removes it from the owner's list.
    assert c.delete(f"/api/v1/collections/{cid}", headers=headers).status_code == 200
    assert all(i["id"] != cid for i in c.get("/api/v1/collections", headers=headers).json()["items"])


def test_pack_slug_is_unique_and_items_must_be_owned_available():
    c, headers = _admin()
    oid = _object(c, headers)
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    assert c.post("/api/v1/collections", json={"slug": slug, "title": "A"},
                  headers=headers).status_code == 200
    assert c.post("/api/v1/collections", json={"slug": slug, "title": "B"},
                  headers=headers).status_code == 409

    second = c.post("/api/v1/collections", json={
        "slug": f"ok-{uuid.uuid4().hex[:8]}", "title": "C",
    }, headers=headers).json()
    assert c.put(f"/api/v1/collections/{second['id']}/items",
                 json={"object_ids": [str(uuid.uuid4())]},
                 headers=headers).status_code == 404
    assert c.put(f"/api/v1/collections/{second['id']}/items",
                 json={"object_ids": [oid]}, headers=headers).status_code == 200
