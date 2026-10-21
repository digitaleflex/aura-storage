"""Session storage and login hardening.

- The catalogue stores only the SHA-256 digest of the session cookie token, so a
  database or backup leak does not yield usable sessions.
- Expired session rows are pruned when a new session is created.
- An unknown username still runs one argon2 verification (no timing oracle).

Offline: disposable SQLite catalogue, no S3 endpoint.
"""
import os
import time

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api.auth import session_key  # noqa: E402
from api.db import Repository  # noqa: E402


def test_session_token_is_stored_hashed(tmp_path):
    repo = Repository(str(tmp_path / "sessions.db"))
    uid = repo.create_user("session-user", "hash", role="user")
    token = repo.create_session(uid, "csrf", int(time.time()) + 3600)

    ids_in_db = [r["id"] for r in repo.conn.execute("SELECT id FROM sessions")]
    assert ids_in_db == [session_key(token)]
    assert token not in ids_in_db
    assert repo.get_session(token)["user_id"] == uid
    # The stored digest is not itself a valid cookie value.
    assert repo.get_session(session_key(token)) is None


def test_delete_session_by_row_id(tmp_path):
    repo = Repository(str(tmp_path / "sessions.db"))
    uid = repo.create_user("session-user", "hash", role="user")
    token = repo.create_session(uid, "csrf", int(time.time()) + 3600)
    repo.delete_session(repo.get_session(token)["id"])
    assert repo.get_session(token) is None


def test_expired_sessions_are_pruned_on_create(tmp_path):
    repo = Repository(str(tmp_path / "sessions.db"))
    uid = repo.create_user("session-user", "hash", role="user")
    repo.create_session(uid, "csrf", int(time.time()) - 10)
    repo.create_session(uid, "csrf", int(time.time()) + 3600)
    (count,) = repo.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
    assert count == 1


def test_login_cookie_is_not_the_stored_id():
    main.reset_login_attempts()
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200
    token = c.cookies.get("aura_session")
    assert token
    assert main.repo.get_session(token) is not None
    assert main.repo.get_session(token)["id"] == session_key(token)
    assert c.get("/api/v1/me").status_code == 200


def test_unknown_username_still_verifies_a_hash(monkeypatch):
    main.reset_login_attempts()
    verified = []
    real_verify = main.verify_password

    def spy(stored_hash, password):
        verified.append(stored_hash)
        return real_verify(stored_hash, password)

    monkeypatch.setattr(main, "verify_password", spy)
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": "no-such-user", "password": "x"})
    assert r.status_code == 401
    # Exactly one verification, against the throwaway hash: an unknown username
    # costs the same argon2 work as a known one and no stored hash is touched.
    assert verified == [main._DUMMY_PASS_HASH]
    main.reset_login_attempts()
