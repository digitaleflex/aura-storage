import os
import uuid

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret456789012345678901234567890")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-revisions-api-audit.jsonl")
os.environ.setdefault("AURA_IMPORT_WORKER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402


class _FakeS3:
    def __init__(self):
        self.deleted = []

    def delete_object(self, **kwargs):
        self.deleted.append((kwargs.get("Bucket"), kwargs.get("Key")))
        return {}


class _FakePresignClient:
    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        bucket = (Params or {}).get("Bucket")
        key = (Params or {}).get("Key")
        return f"https://signed.example/{bucket}/{key}?op={op}&exp={ExpiresIn}"


def _admin_client():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin",
        "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


def _seed_object():
    # Reuse existing seeded/default context: admin belongs to a space; easiest is
    # to create an object row directly in the repo in that space.
    me = main.repo.get_user_by_name("admin")
    space_id = me["space_id"]
    oid = main.repo.new_id()
    now = main.repo.now()
    main.repo.conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, space_id, status, size_bytes, checksum_sha256, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (oid, "aura", f"{space_id}/obj/{oid}", "report.pdf", "application/pdf",
         me["id"], space_id, "available", 123, "ab" * 32, now, now),
    )
    main.repo.conn.commit()
    return oid, me["id"], space_id


def _clear_revisions():
    main.repo.conn.execute("DELETE FROM object_revisions")
    main.repo.conn.commit()


def test_list_and_get_revisions(monkeypatch):
    _clear_revisions()
    c, headers = _admin_client()
    oid, owner_id, _ = _seed_object()
    r1 = main.repo.create_revision(
        object_id=oid, revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=10, checksum_sha256="a" * 64, content_type="application/pdf",
        created_by_id=owner_id, created_by_kind="human",
    )
    r2 = main.repo.create_revision(
        object_id=oid, revision_number=2, bucket="aura", storage_key="rev/2",
        size_bytes=20, checksum_sha256="b" * 64, content_type="application/pdf",
        created_by_id=owner_id, created_by_kind="human",
    )

    r = c.get(f"/api/v1/objects/{oid}/revisions", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object_id"] == oid
    assert [i["revision_number"] for i in body["items"]] == [2, 1]
    assert all("storage_key" not in i for i in body["items"])

    r = c.get(f"/api/v1/objects/{oid}/revisions/{r1}", headers=headers)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["id"] == r1
    assert got["revision_number"] == 1
    assert got["size_bytes"] == 10
    assert "storage_key" not in got


def test_revision_download_intent(monkeypatch):
    _clear_revisions()
    c, headers = _admin_client()
    oid, owner_id, _ = _seed_object()
    rid = main.repo.create_revision(
        object_id=oid, revision_number=3, bucket="aura", storage_key="space/rev/3",
        size_bytes=55, checksum_sha256="c" * 64, content_type="application/pdf",
        created_by_id=owner_id, created_by_kind="human",
    )
    monkeypatch.setattr(main, "s3", _FakePresignClient())

    r = c.get(f"/api/v1/objects/{oid}/revisions/{rid}/download-intent", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object_id"] == oid
    assert body["revision_id"] == rid
    assert body["revision_number"] == 3
    assert body["method"] == "GET"
    assert "download_url" in body and body["download_url"]
    assert "space/rev/3" in body["download_url"]


def test_delete_revision_and_keep_forever(monkeypatch):
    _clear_revisions()
    c, headers = _admin_client()
    oid, owner_id, _ = _seed_object()
    rid = main.repo.create_revision(
        object_id=oid, revision_number=1, bucket="aura", storage_key="rev/del",
        size_bytes=1, checksum_sha256="d" * 64, content_type="application/pdf",
        created_by_id=owner_id, created_by_kind="human",
    )
    fake = _FakeS3()
    monkeypatch.setattr(main, "s3ops", fake)

    r = c.put(f"/api/v1/objects/{oid}/revisions/{rid}/keep-forever", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["keep_forever"] is True

    r = c.delete(f"/api/v1/objects/{oid}/revisions/{rid}", headers=headers)
    assert r.status_code == 409

    r = c.delete(f"/api/v1/objects/{oid}/revisions/{rid}/keep-forever", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["keep_forever"] is False

    r = c.delete(f"/api/v1/objects/{oid}/revisions/{rid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert fake.deleted == [("aura", "rev/del")]
    assert main.repo.get_revision(oid, rid) is None


def test_revision_scoped_to_object():
    _clear_revisions()
    c, headers = _admin_client()
    oid, owner_id, _ = _seed_object()
    rid = main.repo.create_revision(
        object_id=oid, revision_number=1, bucket="aura", storage_key="rev/x",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
        created_by_id=owner_id, created_by_kind="human",
    )
    other = str(uuid.uuid4())
    r = c.get(f"/api/v1/objects/{other}/revisions/{rid}", headers=headers)
    assert r.status_code == 404
