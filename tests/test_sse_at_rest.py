"""Encryption at rest is enforced on the upload path.

SeaweedFS applies SSE-S3 only when the write asks for it, so:
- the presigned PUT signs ``x-amz-server-side-encryption: AES256`` (a PUT
  without it fails the signature check),
- the upload intent tells the client to send that header,
- commit refuses an object the storage does not report as ``AES256``.

Offline: SQLite catalogue and an S3 ops stub.
"""
import os
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402


class FakeBody:
    def __init__(self, data):
        self.data = data

    def iter_chunks(self, chunk_size=1024 * 1024):
        yield self.data


class S3Stub:
    def __init__(self, data: bytes, sse):
        self.data = data
        self.sse = sse
        self.deleted = []

    def head_object(self, Bucket, Key):
        head = {"ContentLength": len(self.data)}
        if self.sse is not None:
            head["ServerSideEncryption"] = self.sse
        return head

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.data)}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()


def _client():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _intent(c, h, size=4):
    r = c.post("/api/v1/objects/upload-intents", headers=h, json={
        "bucket": "aura", "display_name": "sse.bin",
        "content_type": "application/octet-stream", "size_bytes": size,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_intent_requires_and_signs_sse_header():
    c, h = _client()
    intent = _intent(c, h)
    assert intent["headers"]["x-amz-server-side-encryption"] == "AES256"
    query = parse_qs(urlparse(intent["upload_url"]).query)
    signed = query["X-Amz-SignedHeaders"][0].split(";")
    assert "x-amz-server-side-encryption" in signed


def test_idempotent_replay_keeps_sse_header():
    c, h = _client()
    body = {"bucket": "aura", "display_name": "replay.bin",
            "content_type": "application/octet-stream", "size_bytes": 4}
    hk = {**h, "Idempotency-Key": "sse-replay-key"}
    first = c.post("/api/v1/objects/upload-intents", headers=hk, json=body).json()
    again = c.post("/api/v1/objects/upload-intents", headers=hk, json=body).json()
    assert again["idempotent_replay"] is True
    assert again["headers"] == first["headers"]
    assert again["headers"]["x-amz-server-side-encryption"] == "AES256"


@pytest.mark.parametrize("sse", [None, "aws:kms"])
def test_commit_refuses_object_not_encrypted_at_rest(monkeypatch, sse):
    s3 = S3Stub(b"data", sse)
    monkeypatch.setattr(main, "s3ops", s3)
    c, h = _client()
    oid = _intent(c, h)["id"]
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=h)
    assert r.status_code == 422
    assert r.json()["detail"] == "object not encrypted at rest"
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "failed"
    assert len(s3.deleted) == 1


def test_commit_accepts_aes256(monkeypatch):
    monkeypatch.setattr(main, "s3ops", S3Stub(b"data", "AES256"))
    c, h = _client()
    oid = _intent(c, h)["id"]
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "available"


def test_require_sse_can_be_disabled(monkeypatch):
    monkeypatch.setattr(main.settings, "require_sse", False)
    monkeypatch.setattr(main, "s3ops", S3Stub(b"data", None))
    c, h = _client()
    oid = _intent(c, h)["id"]
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=h).status_code == 200


class ReencryptStub:
    """In-memory bucket for api.reencrypt: key -> (sse, content_type, metadata)."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.copies = []

    def get_paginator(self, name):
        stub = self

        class P:
            def paginate(self, Bucket):
                yield {"Contents": [{"Key": k} for k in stub.objects]}

        return P()

    def head_object(self, Bucket, Key):
        sse, ctype, meta = self.objects[Key]
        head = {"ContentType": ctype, "Metadata": meta, "ContentLength": 3}
        if sse:
            head["ServerSideEncryption"] = sse
        return head

    def copy_object(self, **kw):
        self.copies.append(kw)
        self.objects[kw["Key"]] = (kw["ServerSideEncryption"], kw["ContentType"], kw["Metadata"])


def test_reencrypt_dry_run_changes_nothing():
    from api.reencrypt import reencrypt
    stub = ReencryptStub({"a": (None, "application/pdf", {}), "b": ("AES256", "text/plain", {})})
    counts = reencrypt(stub, ["aura"], apply=False)
    assert counts == {"encrypted": 1, "rewritten": 0, "pending": 1, "errors": 0}
    assert stub.copies == []


def test_reencrypt_apply_preserves_type_and_metadata():
    from api.reencrypt import reencrypt
    stub = ReencryptStub({"a": (None, "application/pdf", {"k": "v"}), "b": ("AES256", "text/plain", {})})
    counts = reencrypt(stub, ["aura"], apply=True)
    assert counts == {"encrypted": 1, "rewritten": 1, "pending": 0, "errors": 0}
    (copy,) = stub.copies
    assert copy["MetadataDirective"] == "REPLACE"
    assert copy["ContentType"] == "application/pdf" and copy["Metadata"] == {"k": "v"}
    assert stub.objects["a"][0] == "AES256"
