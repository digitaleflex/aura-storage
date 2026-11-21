import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret456789012345678901234567890")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-revisions-restore-audit.jsonl")
os.environ.setdefault("AURA_IMPORT_WORKER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402


class _FakeS3Ops:
    def __init__(self):
        self.copies = []

    def copy_object(self, **kwargs):
        self.copies.append(kwargs)
        return {}

    def delete_object(self, **kwargs):
        return {}


def _admin_client():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin",
        "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


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


def _seed_object():
    me = main.repo.get_user_by_name("admin")
    oid = main.repo.new_id()
    now = main.repo.now()
    _sql(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, space_id, status, size_bytes, checksum_sha256, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (oid, "aura", f"{me['space_id']}/obj/{oid}", "file.txt", "text/plain",
         me["id"], me["space_id"], "available", 5, "aa" * 32, now, now),
    )
    return oid, me["id"], me["space_id"]


def test_restore_revision_creates_archive_and_updates_head(monkeypatch):
    _sql("DELETE FROM object_revisions")
    c, headers = _admin_client()
    oid, owner_id, _ = _seed_object()
    rid = main.repo.create_revision(
        object_id=oid, revision_number=1, bucket="aura", storage_key="rev/src",
        size_bytes=9, checksum_sha256="bb" * 32, content_type="text/plain",
        created_by_id=owner_id, created_by_kind="human",
    )
    monkeypatch.setattr(main, "s3ops", _FakeS3Ops())
    r = c.post(f"/api/v1/objects/{oid}/revisions/{rid}/restore", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object_id"] == oid
    assert body["restored_revision_id"] == rid
    assert body["status"] == "available"
    obj = _row("SELECT * FROM objects WHERE id = ?", (oid,))
    assert int(obj["size_bytes"]) == 9
    assert obj["checksum_sha256"] == "bb" * 32
    revs = main.repo.list_revisions(oid)
    assert len(revs) >= 1
