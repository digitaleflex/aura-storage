"""AV hook (all paths, timeout), daily quota ordering/atomicity, commit cache."""
import os
import stat
import threading

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402
from api.verifier import verify_one  # noqa: E402


class Body:
    def __init__(self, data):
        self.data = data

    def iter_chunks(self, chunk_size=1024 * 1024):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


class Store:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[Key]), "ETag": '"e"', "ServerSideEncryption": "AES256"}

    def get_object(self, Bucket, Key):
        return {"Body": Body(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)


def _sql(sql, params=()):
    if main.repo.dialect == "sqlite":
        row = main.repo.conn.execute(sql, params).fetchone()
        main.repo.conn.commit()
        return row
    cur = main.repo.conn.execute(sql.replace("?", "%s"), params)
    return cur.fetchone() if cur.description else None


@pytest.fixture
def store(monkeypatch):
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    s = Store()
    monkeypatch.setattr(main, "s3ops", s)
    monkeypatch.setattr(main.settings, "verify_async_threshold_bytes", 10 ** 12)
    _sql("UPDATE objects SET status = 'aborted' WHERE status IN ('pending', 'verifying')")
    main._QUOTA.clear()
    return s


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _intent(c, headers, data=b"payload", store=None):
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "f.bin", "size_bytes": len(data)}, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    if store is not None:
        key = _sql("SELECT object_key FROM objects WHERE id = ?", (oid,))["object_key"]
        store.objects[key] = data
    return oid


def _scanner(tmp_path, body):
    path = tmp_path / "scan.sh"
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_infected_object_is_refused_and_deleted(store, monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "av_scan_cmd", _scanner(tmp_path, "grep -q EICAR \"$1\" && exit 1; exit 0"))
    c, headers = _admin()
    bad = _intent(c, headers, b"EICAR test", store)
    assert c.post(f"/api/v1/objects/{bad}/commit", headers=headers).status_code == 422
    assert c.get(f"/api/v1/objects/{bad}").json()["status"] == "failed"
    assert len(store.deleted) == 1
    good = _intent(c, headers, b"harmless", store)
    assert c.post(f"/api/v1/objects/{good}/commit", headers=headers).status_code == 200


def test_a_hung_scanner_times_out_without_deleting(store, monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "av_scan_cmd", _scanner(tmp_path, "sleep 5"))
    monkeypatch.setattr(main.settings, "av_scan_timeout_s", 1)
    c, headers = _admin()
    oid = _intent(c, headers, b"slow scan", store)
    assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 504
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "pending"
    assert store.deleted == []


def test_the_scan_also_runs_on_the_async_verification_path(store, monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "av_scan_cmd", _scanner(tmp_path, "grep -q EICAR \"$1\" && exit 1; exit 0"))
    monkeypatch.setattr(main.settings, "verify_async_threshold_bytes", 1)
    c, headers = _admin()
    bad = _intent(c, headers, b"EICAR big", store)
    ok = _intent(c, headers, b"fine big", store)
    for oid in (bad, ok):
        assert c.post(f"/api/v1/objects/{oid}/commit", headers=headers).status_code == 202
    while verify_one(main.repo, store, main.settings) is not None:
        pass
    assert c.get(f"/api/v1/objects/{bad}").json()["status"] == "failed"
    assert c.get(f"/api/v1/objects/{ok}").json()["status"] == "available"


def test_a_refused_intent_does_not_consume_the_daily_quota(store, monkeypatch):
    monkeypatch.setattr(main.settings, "quota_files_per_day", 2)
    monkeypatch.setattr(main.settings, "max_pending_intents", 10 ** 6)
    c, headers = _admin()
    # Refused for a bad folder: must not be debited.
    for _ in range(5):
        r = c.post("/api/v1/objects/upload-intents",
                   json={"display_name": "x", "size_bytes": 5, "folder_id": "nope"}, headers=headers)
        assert r.status_code in (403, 404, 422)
    assert _intent(c, headers)
    assert _intent(c, headers)
    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "x", "size_bytes": 5}, headers=headers)
    assert r.status_code == 429


def test_quota_check_and_debit_is_atomic(monkeypatch):
    monkeypatch.setattr(main.settings, "quota_files_per_day", 5)
    main._QUOTA.clear()
    ok, refused = [], []

    def charge():
        try:
            main._charge_quota("space-x", 1)
            ok.append(1)
        except main.HTTPException:
            refused.append(1)

    threads = [threading.Thread(target=charge) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 5 and len(refused) == 35


def test_commit_cache_is_scoped_to_the_caller_and_bounded(monkeypatch):
    assert main._cache_key("commit", "o", "k", "alice") != main._cache_key("commit", "o", "k", "bob")
    assert main._cache_key("commit", "o", None, "alice") is None
    monkeypatch.setattr(main, "_RESP_CACHE_MAX", 3)
    main._RESP_CACHE.clear()
    for i in range(10):
        main._cache_set(f"k{i}", 200, {"i": i})
    assert len(main._RESP_CACHE) <= 3
    assert main._cache_get("k9") == (200, {"i": 9})


def test_a_retried_commit_with_the_same_key_is_served_from_the_cache(store):
    c, headers = _admin()
    oid = _intent(c, headers, b"cache me", store)
    h = {**headers, "Idempotency-Key": "commit-key-1"}
    first = c.post(f"/api/v1/objects/{oid}/commit", headers=h)
    assert first.status_code == 200
    store.objects.clear()  # a second real check would now fail
    second = c.post(f"/api/v1/objects/{oid}/commit", headers=h)
    assert second.status_code == 200 and second.json() == first.json()
