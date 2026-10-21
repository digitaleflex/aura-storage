"""#72 — multipart upload with part-level resume, offline.

The S3 data plane is an in-process fake that keeps parts per upload session,
so the real route handlers run end to end: intent -> part URLs -> (simulated)
part PUTs -> status/resume -> commit (complete + full-object SHA-256). Part
limits are shrunk so the payloads stay tiny.

NOT covered here (compatibility gate, docs/MULTIPART-UPLOAD-PLAN.md): the
pinned SeaweedFS image, signed part lengths enforced by the gateway, SSE on
parts and part PUTs through Traefik. Those need a live disposable bucket.
"""
import hashlib
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
import api.s3 as s3mod  # noqa: E402
from api import authz  # noqa: E402
from api.lifecycle import reconcile_pending  # noqa: E402


class NoSuchUpload(Exception):
    def __init__(self):
        super().__init__("NoSuchUpload")
        self.response = {"Error": {"Code": "NoSuchUpload"}}


class Body:
    def __init__(self, data: bytes):
        self.data = data

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


class FakeMultipartS3:
    """Sessions of parts, assembled into an object on complete."""

    def __init__(self, page_size: int = 1000):
        self.sessions: dict[str, dict[int, bytes]] = {}
        self.objects: dict[str, bytes] = {}
        self.aborted: list[str] = []
        self.completed: list[str] = []
        self.page_size = page_size
        self._n = 0

    # Browser side (a presigned part PUT), simulated directly.
    def put_part(self, upload_id: str, number: int, data: bytes) -> None:
        self.sessions[upload_id][number] = data

    def create_multipart_upload(self, Bucket, Key, ContentType, ServerSideEncryption):
        assert ServerSideEncryption == "AES256"
        self._n += 1
        upload_id = f"up-{self._n}"
        self.sessions[upload_id] = {}
        return {"UploadId": upload_id}

    def list_parts(self, Bucket, Key, UploadId, MaxParts, PartNumberMarker=0):
        if UploadId not in self.sessions:
            raise NoSuchUpload()
        numbers = sorted(n for n in self.sessions[UploadId] if n > PartNumberMarker)
        page = numbers[: min(MaxParts, self.page_size)]
        return {
            "Parts": [
                {"PartNumber": n, "Size": len(self.sessions[UploadId][n]), "ETag": f'"e{n}"'}
                for n in page
            ],
            "IsTruncated": len(numbers) > len(page),
            "NextPartNumberMarker": page[-1] if page else 0,
        }

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        if UploadId not in self.sessions:
            raise NoSuchUpload()
        parts = self.sessions.pop(UploadId)
        numbers = [p["PartNumber"] for p in MultipartUpload["Parts"]]
        assert numbers == sorted(parts)
        self.objects[Key] = b"".join(parts[n] for n in numbers)
        self.completed.append(UploadId)

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        if UploadId not in self.sessions:
            raise NoSuchUpload()
        del self.sessions[UploadId]
        self.aborted.append(UploadId)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key]), "ServerSideEncryption": "AES256"}

    def get_object(self, Bucket, Key):
        return {"Body": Body(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


PART = 8  # bytes, once the S3 minimum is shrunk for the test


@pytest.fixture(autouse=True)
def _multipart(monkeypatch):
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    monkeypatch.setattr(s3mod, "MIN_PART_BYTES", 1)
    monkeypatch.setattr(s3mod, "_MIB", 1)
    monkeypatch.setattr(main.settings, "multipart_enabled", True)
    monkeypatch.setattr(main.settings, "multipart_threshold_bytes", 16)
    monkeypatch.setattr(main.settings, "multipart_part_bytes", PART)
    monkeypatch.setattr(main.settings, "multipart_max_object_bytes", 10_000)
    monkeypatch.setattr(main.settings, "max_object_bytes", 20)
    fake = FakeMultipartS3()
    monkeypatch.setattr(main, "s3ops", fake)
    yield fake
    main.reset_login_attempts()


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _intent(c, headers, size, idem=None, name="big.bin"):
    hdrs = dict(headers)
    if idem:
        hdrs["Idempotency-Key"] = idem
    return c.post("/api/v1/objects/upload-intents",
                  json={"display_name": name, "size_bytes": size}, headers=hdrs)


def _sql(sql: str, params: tuple = ()):
    """Run a test-only statement on either catalogue backend (SQLite or the
    PostgreSQL parity job) and return the first row, or None."""
    if main.repo.dialect == "sqlite":
        row = main.repo.conn.execute(sql, params).fetchone()
        main.repo.conn.commit()
        return row
    cur = main.repo.conn.execute(sql.replace("?", "%s"), params)
    return cur.fetchone() if cur.description else None


def _upload_id(oid: str) -> str:
    return _sql("SELECT multipart_upload_id FROM objects WHERE id = ?", (oid,))[
        "multipart_upload_id"
    ]


def _object_status(oid: str) -> str:
    return _sql("SELECT status FROM objects WHERE id = ?", (oid,))["status"]


def _send(fake, oid, data, numbers):
    upload_id = _upload_id(oid)
    for n in numbers:
        fake.put_part(upload_id, n, data[(n - 1) * PART: n * PART])


DATA = bytes(range(37))  # 37 bytes -> 5 parts of 8 (last 5)


def test_plan_parts_respects_minimum_and_part_count(monkeypatch):
    assert s3mod.plan_parts(37, 8) == (8, 5)
    # Real S3 limits: a tiny preference is raised to 5 MiB, and 1 TiB stays
    # within 10 000 parts of a whole number of MiB.
    monkeypatch.setattr(s3mod, "MIN_PART_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(s3mod, "_MIB", 1024 * 1024)
    assert s3mod.plan_parts(1, 1)[0] == 5 * 1024 * 1024
    part, count = s3mod.plan_parts(1024 ** 4, 16 * 1024 * 1024)
    assert count <= s3mod.MAX_PARTS and part % (1024 * 1024) == 0
    assert s3mod.part_length(count, part, 1024 ** 4) > 0
    assert sum(s3mod.part_length(n, part, 1024 ** 4) for n in range(1, count + 1)) == 1024 ** 4


def test_small_files_keep_the_single_put_path(_multipart):
    c, headers = _admin()
    r = _intent(c, headers, 10)
    assert r.status_code == 200, r.text
    assert r.json()["upload_url"] and "upload_mode" not in r.json()


def test_disabled_flag_keeps_the_single_put_ceiling(monkeypatch, _multipart):
    monkeypatch.setattr(main.settings, "multipart_enabled", False)
    c, headers = _admin()
    assert _intent(c, headers, 37).status_code == 422


def test_full_multipart_upload_is_assembled_and_verified(_multipart):
    fake = _multipart
    c, headers = _admin()
    r = _intent(c, headers, len(DATA))
    assert r.status_code == 200, r.text
    intent = r.json()
    assert intent["upload_mode"] == "multipart" and intent["upload_url"] is None
    assert intent["multipart"] == {"part_size_bytes": PART, "part_count": 5}
    oid = intent["id"]

    urls = c.post(f"/api/v1/objects/{oid}/multipart/parts",
                  json={"part_numbers": [5, 1]}, headers=headers).json()["parts"]
    assert [(p["part_number"], p["size_bytes"]) for p in urls] == [(1, 8), (5, 5)]
    query = parse_qs(urlparse(urls[0]["url"]).query)
    assert query["partNumber"] == ["1"] and query["uploadId"] == [_upload_id(oid)]

    _send(fake, oid, DATA, range(1, 6))
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["checksum_sha256"] == hashlib.sha256(DATA).hexdigest()
    assert r.json()["size_bytes"] == len(DATA)
    assert _upload_id(oid) is None
    # Idempotent repeat.
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).json()["status"] == "available"


def test_missing_parts_block_commit_and_status_lists_what_is_held(_multipart):
    fake = _multipart
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    _send(fake, oid, DATA, [1, 2, 4])
    # A part with the wrong size does not count as held.
    fake.put_part(_upload_id(oid), 5, b"short")
    fake.put_part(_upload_id(oid), 3, b"x" * 3)

    status = c.get(f"/api/v1/objects/{oid}/multipart", headers=headers).json()
    assert status["uploaded_parts"] == [1, 2, 4, 5]
    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 409 and "1 part(s) missing" in r.json()["detail"]

    _send(fake, oid, DATA, [3])
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 200


def test_resume_with_the_same_key_reuses_the_session(_multipart):
    fake = _multipart
    c, headers = _admin()
    first = _intent(c, headers, len(DATA), idem="resume-key-1").json()
    _send(fake, first["id"], DATA, [1, 2])

    # The page reloads: same Idempotency-Key, same object, parts kept.
    again = _intent(c, headers, len(DATA), idem="resume-key-1").json()
    assert again["id"] == first["id"] and again["idempotent_replay"] is True
    assert again["upload_mode"] == "multipart"
    status = c.get(f"/api/v1/objects/{again['id']}/multipart", headers=headers).json()
    assert status["uploaded_parts"] == [1, 2]


def test_part_numbers_are_validated(_multipart):
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    bad = c.post(f"/api/v1/objects/{oid}/multipart/parts",
                 json={"part_numbers": [6]}, headers=headers)
    assert bad.status_code == 422
    too_many = c.post(f"/api/v1/objects/{oid}/multipart/parts",
                      json={"part_numbers": list(range(1, 102))}, headers=headers)
    assert too_many.status_code == 422


def test_single_put_objects_have_no_multipart_routes(_multipart):
    c, headers = _admin()
    oid = _intent(c, headers, 10).json()["id"]
    assert c.get(f"/api/v1/objects/{oid}/multipart", headers=headers).status_code == 409


def test_abort_frees_the_parts(_multipart):
    fake = _multipart
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    upload_id = _upload_id(oid)
    _send(fake, oid, DATA, [1])
    assert c.post(f"/api/v1/objects/{oid}/abort", headers=headers).status_code == 200
    assert fake.aborted == [upload_id] and upload_id not in fake.sessions


def test_commit_after_a_crash_between_complete_and_record(_multipart):
    fake = _multipart
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    _send(fake, oid, DATA, range(1, 6))
    # The storage completed the upload but the API died before clearing it.
    row = dict(_sql("SELECT * FROM objects WHERE id = ?", (oid,)))
    parts = s3mod.list_uploaded_parts(fake, row["bucket"], row["object_key"], _upload_id(oid))
    s3mod.complete_multipart(fake, row["bucket"], row["object_key"], _upload_id(oid), parts)

    r = c.post(f"/api/v1/objects/{oid}/commit", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["checksum_sha256"] == hashlib.sha256(DATA).hexdigest()


def test_status_pages_through_many_parts(_multipart, monkeypatch):
    fake = _multipart
    fake.page_size = 2
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    _send(fake, oid, DATA, range(1, 6))
    status = c.get(f"/api/v1/objects/{oid}/multipart", headers=headers).json()
    assert status["uploaded_parts"] == [1, 2, 3, 4, 5]


def test_reconcile_keeps_a_live_session_and_sweeps_an_expired_one(_multipart):
    fake = _multipart
    c, headers = _admin()
    oid = _intent(c, headers, len(DATA)).json()["id"]
    upload_id = _upload_id(oid)
    # Created long ago, but its multipart session has not expired yet.
    _sql("UPDATE objects SET created_at = ? WHERE id = ?", (int(time.time()) - 86_400, oid))
    reconcile_pending(main.repo, fake, expire_after_s=3600, limit=5000)
    assert _object_status(oid) == "pending"

    _sql("UPDATE objects SET intent_expires_at = ? WHERE id = ?", (int(time.time()) - 10, oid))
    reconcile_pending(main.repo, fake, expire_after_s=3600, limit=5000)
    assert _object_status(oid) == "expired"
    assert upload_id in fake.aborted
