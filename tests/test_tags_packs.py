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


def test_multiple_tags_support_all_and_any_modes():
    a = f"a{uuid.uuid4().hex[:8]}"
    b = f"b{uuid.uuid4().hex[:8]}"
    c, headers = _admin()
    only_a = _object(c, headers, name="only-a.pdf")
    only_b = _object(c, headers, name="only-b.pdf")
    both = _object(c, headers, name="both.pdf")
    assert _tags(c, headers, only_a, [a]).status_code == 200
    assert _tags(c, headers, only_b, [b]).status_code == 200
    assert _tags(c, headers, both, [a, b]).status_code == 200

    def ids(url):
        return [item["id"] for item in c.get(url, headers=headers).json()["items"]]

    assert ids(f"/api/v1/objects?tags={a},{b}&tag_mode=all") == [both]
    assert set(ids(f"/api/v1/objects?tags={a},{b}&tag_mode=any")) == {only_a, only_b, both}
    # Normalization and de-duplication mirror the single-tag shorthand.
    assert ids(f"/api/v1/objects?tags={a.upper()},{a},{b}&tag_mode=all") == [both]
    assert set(ids(f"/api/v1/objects?tag={a}")) == {only_a, both}


def test_tag_filters_treat_user_input_literally():
    c, headers = _admin()
    oid = _object(c, headers)
    assert _tags(c, headers, oid, ["safe"]).status_code == 200
    # Tags are bound as SQL parameters: a wildcard or a quote cannot widen the
    # filter into an "everything" match or an injection.
    for hostile in ("%", "_", "safe' OR '1'='1", "safe,%"):
        result = c.get("/api/v1/objects", params={"tag": hostile}, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["items"] == [], hostile


def test_tag_vocabulary_counts_only_visible_objects():
    # Unique tags: the test catalogue is shared with the other tests in this file.
    shared = f"v{uuid.uuid4().hex[:8]}"
    single = f"w{uuid.uuid4().hex[:8]}"
    c, headers = _admin()
    a = _object(c, headers, name="a.pdf")
    b = _object(c, headers, name="b.pdf")
    assert _tags(c, headers, a, [shared.upper(), single]).status_code == 200
    assert _tags(c, headers, b, [shared]).status_code == 200

    items = c.get("/api/v1/objects/tags", headers=headers).json()["items"]
    assert {"tag": shared, "count": 2} in items
    assert {"tag": single, "count": 1} in items
    assert items == sorted(items, key=lambda e: (-e["count"], e["tag"]))

    # A soft-deleted object is hidden from the default list and from the counts.
    main.repo.set_status(b, "deleted")
    items = c.get("/api/v1/objects/tags", headers=headers).json()["items"]
    assert {"tag": shared, "count": 1} in items
    assert {"tag": single, "count": 1} in items


def test_tag_vocabulary_is_owner_scoped():
    secret = f"z{uuid.uuid4().hex[:8]}"
    c, headers = _admin()
    oid = _object(c, headers)
    assert _tags(c, headers, oid, [secret]).status_code == 200

    name = f"user-{uuid.uuid4().hex[:8]}"
    password = "user-password-123"
    main.repo.create_user(
        name, hash_password(password), role="user",
        space_id=main.repo.list_spaces()[0]["id"],
    )
    other = TestClient(main.app)
    login = other.post("/api/v1/login", json={"username": name, "password": password})
    assert login.status_code == 200, login.text
    headers_other = {"X-CSRF-Token": login.json()["csrf_token"]}
    items = other.get("/api/v1/objects/tags", headers=headers_other).json()["items"]
    assert all(entry["tag"] != secret for entry in items)


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
