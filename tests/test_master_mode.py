"""Master mode: a password-confirmed, session-bound, short-lived elevation for
bulk purges without a confirmation per item."""
import os
import time

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
from api.auth import hash_password  # noqa: E402

DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
PASSWORD = os.environ["AURA_API_ADMIN_PASSWORD"]


class Store:
    def __init__(self):
        self.deleted = []
        self.down = False

    def delete_object(self, Bucket, Key):
        if self.down:
            raise ConnectionError("storage down")
        self.deleted.append(Key)


@pytest.fixture
def store(monkeypatch):
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    s = Store()
    monkeypatch.setattr(main, "s3ops", s)
    return s


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": "admin", "password": PASSWORD})
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _available(c, headers):
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"display_name": "x.bin", "size_bytes": 1}, headers=headers).json()["id"]
    main.repo.mark_available(oid, 1, DIGEST)
    return oid


def _master(c, headers):
    r = c.post("/api/v1/me/master-mode", json={"password": PASSWORD}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["master_until"]


def test_bulk_actions_need_master_mode(store):
    c, headers = _admin()
    oid = _available(c, headers)
    r = c.post("/api/v1/objects/bulk-purge", json={"ids": [oid]}, headers=headers)
    assert r.status_code == 403 and r.json()["detail"] == "master mode required"
    assert c.post("/api/v1/objects/trash/empty", headers=headers).status_code == 403


def test_the_password_is_required_and_wrong_ones_are_rate_limited(store, monkeypatch):
    monkeypatch.setattr(main.settings, "login_rate_limit", 2)
    c, headers = _admin()
    bad = {"password": "not-it"}
    assert c.post("/api/v1/me/master-mode", json=bad, headers=headers).status_code == 403
    assert c.post("/api/v1/me/master-mode", json=bad, headers=headers).status_code == 403
    assert c.post("/api/v1/me/master-mode", json=bad, headers=headers).status_code == 429
    assert c.get("/api/v1/me").json()["master_until"] is None


def test_master_mode_purges_many_objects_in_one_call(store):
    c, headers = _admin()
    ids = [_available(c, headers) for _ in range(3)]
    until = _master(c, headers)
    assert until > time.time()
    assert c.get("/api/v1/me").json()["master_until"] == until
    r = c.post("/api/v1/objects/bulk-purge", json={"ids": ids + ["not-a-uuid"]}, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["purged"]) == sorted(ids)
    assert out["not_found"] == ["not-a-uuid"] and out["failed"] == []
    assert len(store.deleted) == 3


def test_a_storage_failure_keeps_the_reference(store):
    c, headers = _admin()
    oid = _available(c, headers)
    _master(c, headers)
    store.down = True
    out = c.post("/api/v1/objects/bulk-purge", json={"ids": [oid]}, headers=headers).json()
    assert out["failed"] == [oid]
    assert c.get(f"/api/v1/objects/{oid}").json()["status"] == "available"


def test_empty_trash_purges_only_deleted_objects(store):
    c, headers = _admin()
    kept = _available(c, headers)
    trashed = [_available(c, headers) for _ in range(2)]
    for oid in trashed:
        assert c.delete(f"/api/v1/objects/{oid}", headers=headers).status_code == 200
    _master(c, headers)
    out = c.post("/api/v1/objects/trash/empty", headers=headers).json()
    assert set(trashed) <= set(out["purged"]) and kept not in out["purged"]
    assert out["more"] is False
    assert c.get(f"/api/v1/objects/{kept}").json()["status"] == "available"


def test_master_mode_expires_and_can_be_left(store, monkeypatch):
    c, headers = _admin()
    _master(c, headers)
    assert c.delete("/api/v1/me/master-mode", headers=headers).json()["master_until"] is None
    assert c.post("/api/v1/objects/trash/empty", headers=headers).status_code == 403
    monkeypatch.setattr(main.settings, "master_mode_ttl", -1)
    _master(c, headers)  # already expired the moment it is granted
    assert c.post("/api/v1/objects/trash/empty", headers=headers).status_code == 403


def test_master_mode_is_bound_to_one_session(store):
    c1, h1 = _admin()
    c2, h2 = _admin()
    _master(c1, h1)
    assert c2.get("/api/v1/me").json()["master_until"] is None
    assert c2.post("/api/v1/objects/trash/empty", headers=h2).status_code == 403


def test_too_many_ids_are_refused(store, monkeypatch):
    monkeypatch.setattr(main.settings, "master_bulk_max", 2)
    c, headers = _admin()
    _master(c, headers)
    r = c.post("/api/v1/objects/bulk-purge", json={"ids": ["a", "b", "c"]}, headers=headers)
    assert r.status_code == 422


def test_a_user_without_purge_cannot_enter_master_mode(store):
    c, headers = _admin()
    name = f"plain-{int(time.time() * 1000)}"
    main.repo.create_user(name, hash_password("user-password-123"), role="user")
    u = TestClient(main.app)
    uh = {"X-CSRF-Token": u.post("/api/v1/login", json={
        "username": name, "password": "user-password-123"}).json()["csrf_token"]}
    assert u.post("/api/v1/me/master-mode", json={"password": "user-password-123"},
                  headers=uh).status_code == 403
