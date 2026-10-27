"""Stable publication slugs, public media redirects and content replacement.

A published slug is a permanent URL: replacing the bytes keeps the same slug, so
course sites never change. Unpublishing (or a missing object) answers 404.
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


def _admin():
    username = f"pub-{uuid.uuid4().hex[:10]}"
    password = "pub-test-password"
    main.repo.create_user(username, hash_password(password), role="admin")
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _object(c, headers, size=1000, name="cours.pdf", content_type="application/pdf"):
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": name, "size_bytes": size, "content_type": content_type,
    }, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    main.repo.mark_available(oid, size, uuid.uuid4().hex)
    return oid


def _publish(c, headers, oid, slug, published=True):
    return c.put(
        f"/api/v1/objects/{oid}/publication",
        json={"slug": slug, "published": published}, headers=headers,
    )


def test_publish_redirects_and_unpublish_404():
    c, headers = _admin()
    oid = _object(c, headers)
    slug = f"cours-{uuid.uuid4().hex[:8]}"
    r = _publish(c, headers, oid, slug)
    assert r.status_code == 200, r.text
    assert r.json()["public_slug"] == slug
    assert r.json()["published_at"] is not None

    redirect = client.get(f"/m/{slug}", follow_redirects=False)
    assert redirect.status_code == 302
    assert "X-Amz-Signature=" in redirect.headers["location"]
    assert redirect.headers["cache-control"] == "no-store"

    assert _publish(c, headers, oid, slug, published=False).status_code == 200
    assert client.get(f"/m/{slug}", follow_redirects=False).status_code == 404

    # Republishing reuses the reserved slug.
    assert _publish(c, headers, oid, slug).status_code == 200
    assert client.get(f"/m/{slug}", follow_redirects=False).status_code == 302


def test_slug_is_unique_validated_and_human_only():
    c, headers = _admin()
    a, b = _object(c, headers), _object(c, headers)
    slug = f"unique-{uuid.uuid4().hex[:8]}"
    assert _publish(c, headers, a, slug).status_code == 200
    duplicate = _publish(c, headers, b, slug)
    assert duplicate.status_code == 409, duplicate.text
    assert _publish(c, headers, a, "Bad Slug!").status_code == 422
    assert _publish(c, headers, a, "x").status_code == 422
    assert _publish(c, headers, a, None).status_code == 422  # publishing needs a slug

    # A machine identity may not publish (human-only).
    token = c.post("/api/v1/admin/identities", json={
        "space_id": main.repo.list_spaces()[0]["id"],
        "name": "pub-service", "scopes": ["objects:write"],
    }, headers=headers)
    assert token.status_code == 200, token.text
    bearer = {"Authorization": f"Bearer {token.json()['token']}"}
    assert c.put(f"/api/v1/objects/{a}/publication",
                 json={"slug": "machine-slug", "published": True},
                 headers=bearer).status_code == 403


def test_replacing_content_keeps_the_published_url(monkeypatch):
    c, headers = _admin()
    monkeypatch.setattr(main, "s3ops", DummyS3(b"x"))
    target = _object(c, headers, size=1000, name="cours.pdf")
    source = _object(c, headers, size=2048, name="cours-v2.pdf")
    slug = f"stable-{uuid.uuid4().hex[:8]}"
    assert _publish(c, headers, target, slug).status_code == 200

    r = c.post(f"/api/v1/objects/{target}/replace",
               json={"source_object_id": source}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["public_slug"] == slug
    assert r.json()["size_bytes"] == 2048

    # Same URL, new bytes; the source row is gone.
    assert client.get(f"/m/{slug}", follow_redirects=False).status_code == 302
    assert c.get(f"/api/v1/objects/{source}", headers=headers).status_code == 404
    # The display name belongs to the stable object, not to the new upload.
    assert r.json()["display_name"] == "cours.pdf"


def test_replacement_refuses_a_published_source_and_self():
    c, headers = _admin()
    target = _object(c, headers)
    source = _object(c, headers)
    assert _publish(c, headers, source, f"other-{uuid.uuid4().hex[:8]}").status_code == 200
    refused = c.post(f"/api/v1/objects/{target}/replace",
                     json={"source_object_id": source}, headers=headers)
    assert refused.status_code == 409
    assert c.post(f"/api/v1/objects/{target}/replace",
                  json={"source_object_id": target}, headers=headers).status_code == 422


def test_thumbnail_route_404_without_generated_poster():
    c, headers = _admin()
    oid = _object(c, headers, content_type="application/pdf")
    assert c.get(f"/api/v1/objects/{oid}/thumbnail", headers=headers).status_code == 404
    assert c.get(f"/api/v1/objects/{uuid.uuid4()}/thumbnail",
                 headers=headers).status_code == 404
