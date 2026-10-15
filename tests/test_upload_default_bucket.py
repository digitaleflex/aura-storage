"""Upload-intent bucket selection (#36/#62 behaviour change).

The frontend no longer hard-codes ``bucket: "aura"``; the intent omits the field
and the server files the object in the caller's **space default bucket**. This test
pins that behaviour at the catalogue level (no S3 endpoint is contacted: presigning
is local signing, the object row is read back from the repository).

Also covers the allow-list: an explicit bucket is honoured only when registered to
the caller's space, otherwise the intent is refused (403).
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


def _upload(c, headers, name, bucket=None):
    body = {"display_name": name, "size_bytes": 1}
    if bucket is not None:
        body["bucket"] = bucket
    return c.post("/api/v1/objects/upload-intents", json=body, headers=headers)


def _object_row(oid):
    # The caller's scope filters reads; the admin owns the object, so read back by
    # its space and owner id.
    space_id = main.repo.get_user_by_name("admin")["space_id"]
    return main.repo.get_object(oid, space_id=space_id)


def test_omitting_bucket_uses_the_space_default():
    c, headers = _admin()
    default = main.repo.get_default_bucket(_default_space_id())
    assert default is not None, "the seeded default space must have a default bucket"

    r = _upload(c, headers, f"no-bucket-{uuid.uuid4().hex[:8]}.txt")
    assert r.status_code == 200, r.text
    # The presigned URL is bound to the default bucket...
    assert f"/{default['name']}/" in r.json()["upload_url"]
    # ...and the catalogue row records that same bucket.
    row = _object_row(r.json()["id"])
    assert row is not None and row["bucket"] == default["name"]


def test_explicit_unregistered_bucket_is_refused():
    c, headers = _admin()
    r = _upload(c, headers, "x.txt", bucket=f"not-registered-{uuid.uuid4().hex[:8]}")
    assert r.status_code == 403


def test_explicit_registered_bucket_is_honoured():
    c, headers = _admin()
    name = f"aura-test-{uuid.uuid4().hex[:8]}"
    main.repo.create_bucket(_default_space_id(), name, is_default=False)

    r = _upload(c, headers, "y.txt", bucket=name)
    assert r.status_code == 200, r.text
    row = _object_row(r.json()["id"])
    assert row is not None and row["bucket"] == name
