import hashlib
import os
import time

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret456789012345678901234567890")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-replace-intent-audit.jsonl")
os.environ.setdefault("AURA_IMPORT_WORKER_ENABLED", "0")
os.environ.setdefault("AURA_MULTIPART_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402


class FakeBody:
    def __init__(self, data: bytes):
        self.data = data

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


class DummyS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.copies = []
        self.deleted = []

    def head_object(self, Bucket, Key):
        data = self.objects[Key]
        return {"ContentLength": len(data), "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256"}

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))
        self.objects.pop(Key, None)

    def copy_object(self, CopySource, Bucket, Key, **kwargs):
        src_key = CopySource.get("Key") if isinstance(CopySource, dict) else None
        if src_key is None or src_key not in self.objects:
            raise KeyError(src_key)
        self.objects[Key] = self.objects[src_key]
        self.copies.append((src_key, Key))
        return {"CopyObjectResult": {"ETag": '"x"'}}


class _FakePresignClient:
    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        bucket = (Params or {}).get("Bucket")
        key = (Params or {}).get("Key")
        return f"https://signed.example/{bucket}/{key}?op={op}&exp={ExpiresIn}"


def _admin_client():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _sql(sql: str, params: tuple = ()) -> None:
    """Write through the active backend (tests are written with ``?`` placeholders)."""
    if main.repo.dialect == "sqlite":
        main.repo.conn.execute(sql, params)
        main.repo.conn.commit()
    else:  # psycopg connection: go through the repository helper
        main.repo._run(sql.replace("?", "%s"), params)


def _row(sql: str, params: tuple = ()):
    """Read one row through the active backend (``?`` placeholders)."""
    if main.repo.dialect == "sqlite":
        return main.repo.conn.execute(sql, params).fetchone()
    return main.repo._one(sql.replace("?", "%s"), params)


def _seed_available_object(display_name="orig.bin", data=b"old-content"):
    me = main.repo.get_user_by_name("admin")
    space_id = me["space_id"]
    oid = main.repo.new_id()
    now = main.repo.now()
    key = f"aura/{space_id}/seed/{oid}"
    digest = hashlib.sha256(data).hexdigest()
    _sql(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, space_id, status, size_bytes, checksum_sha256, expected_size_bytes, "
        "version, revision_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?, 1, 0, ?, ?)",
        (oid, "aura", key, display_name, "application/octet-stream",
         me["id"], space_id, len(data), digest, len(data), now, now),
    )
    return oid, key, data, digest, space_id


def test_replace_intent_commit_archives_head_and_swaps_target(monkeypatch):
    c, headers = _admin_client()
    old_data = b"old-bytes-v1"
    new_data = b"new-bytes-v2-longer"
    target_id, old_key, _, old_digest, space_id = _seed_available_object(data=old_data)

    r = c.post(f"/api/v1/objects/{target_id}/replace-intents", json={
        "display_name": "replaced.bin",
        "content_type": "application/octet-stream",
        "size_bytes": len(new_data),
    }, headers=headers)
    assert r.status_code == 200, r.text
    intent = r.json()
    intent_id = intent["id"]
    assert intent["replace_target_id"] == target_id
    assert intent["status"] == "pending"

    intent_row = main.repo.get_object(intent_id, space_id=space_id)
    assert intent_row is not None
    intent_key = intent_row["object_key"]
    assert intent_key != old_key

    s3 = DummyS3({old_key: old_data, intent_key: new_data})
    monkeypatch.setattr(main, "s3ops", s3)
    monkeypatch.setattr(main, "s3", _FakePresignClient())

    r = c.post(f"/api/v1/objects/{intent_id}/commit", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == target_id
    assert body["status"] == "available"
    assert body["size_bytes"] == len(new_data)
    assert body["checksum_sha256"] == hashlib.sha256(new_data).hexdigest()

    target = main.repo.get_object(target_id, space_id=space_id)
    assert target["object_key"] == intent_key
    assert target["size_bytes"] == len(new_data)
    assert target["checksum_sha256"] == hashlib.sha256(new_data).hexdigest()
    assert target["status"] == "available"
    assert int((target["revision_count"] if "revision_count" in target.keys() else 0) or 0) >= 1

    revs = main.repo.list_revisions(target_id)
    assert len(revs) == 1
    rev = revs[0]
    assert rev["size_bytes"] == len(old_data)
    assert rev["checksum_sha256"] == old_digest
    assert rev["storage_key"] in s3.objects

    # intent row removed
    assert main.repo.get_object(intent_id, space_id=space_id) is None


def test_replace_intent_commit_idempotent_replay_same_key(monkeypatch):
    c, headers = _admin_client()
    old_data = b"old"
    new_data = b"new-data"
    target_id, old_key, _, _, space_id = _seed_available_object(data=old_data)

    r = c.post(f"/api/v1/objects/{target_id}/replace-intents", json={
        "display_name": "r.bin",
        "content_type": "application/octet-stream",
        "size_bytes": len(new_data),
    }, headers=headers)
    assert r.status_code == 200, r.text
    intent_id = r.json()["id"]
    intent_key = main.repo.get_object(intent_id, space_id=space_id)["object_key"]

    s3 = DummyS3({old_key: old_data, intent_key: new_data})
    monkeypatch.setattr(main, "s3ops", s3)
    idem = {"Idempotency-Key": "replace-commit-1", **headers}

    r1 = c.post(f"/api/v1/objects/{intent_id}/commit", headers=idem)
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["id"] == target_id

    # Replay with same idempotency key after intent deleted: should return cached result.
    r2 = c.post(f"/api/v1/objects/{intent_id}/commit", headers=idem)
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["id"] == target_id
    assert b2["checksum_sha256"] == b1["checksum_sha256"]

    revs = main.repo.list_revisions(target_id)
    assert len(revs) == 1
    # no extra archive copies from replay
    assert len([c for c in s3.copies if c[0] == old_key]) == 1
