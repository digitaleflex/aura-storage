"""Public object share links (``/s/<token>``).

A share is an unauthenticated, revocable, read-only capability for exactly one
object: the only public way to reach object bytes without a session or a machine
token. These tests pin the properties that make that acceptable:

- the token is stored only as a SHA-256 fingerprint and returned once;
- redemption is a 302 to a short-lived presigned GET (bytes never via the API),
  carrying no-store / no-referrer / noindex headers;
- malformed, unknown, expired, exhausted and revoked links are indistinguishable
  (one 404) so nothing can be enumerated;
- expiry is mandatory and bounded, ``max_uses`` is enforced atomically;
- creation is human-only and CSRF-protected; the object scope is unchanged;
- ``inline`` is refused for types a browser could execute;
- every create/revoke/redeem is audited by share id, never by token.

Offline: SQLite catalogue and local presigning only, no S3 endpoint is contacted.
"""
import json
import os
import time
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
from api import shares  # noqa: E402
from api.auth import hash_password  # noqa: E402
from tests import catalogue_sql  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def _account(role="user"):
    """A fresh account for this test.

    Deliberately *not* the shared ``admin`` login: the suite runs against one
    in-memory catalogue, and other modules list and filter that account's
    objects. Creating objects here as ``admin`` would make their assertions
    depend on test execution order.
    """
    username = f"share-{uuid.uuid4().hex[:10]}"
    password = "share-test-password"
    main.repo.create_user(username, hash_password(password), role=role)
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _admin():
    """A fresh account with the admin role (all capabilities)."""
    return _account(role="admin")


def _user():
    """A fresh plain user account (no admin capability)."""
    return _account(role="user")


def _object(c, headers, name="contrat.pdf", content_type="application/pdf"):
    """Create an object row and mark it available (catalogue-only transition)."""
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": name, "size_bytes": 4096, "content_type": content_type,
    }, headers=headers)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    main.repo.mark_available(oid, 4096, uuid.uuid4().hex)
    return oid


def _share(c, headers, oid, **body):
    r = c.post(f"/api/v1/objects/{oid}/share", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _redeem(token):
    return client.get(f"/s/{token}", follow_redirects=False)


def test_share_round_trip_redirects_to_a_presigned_get():
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid)

    token = created["token"]
    assert shares.is_well_formed(token)
    assert created["url"].endswith(f"/s/{token}")
    assert created["expires_in"] == main.settings.share_ttl_default
    assert created["object_id"] == oid

    # Only the fingerprint is stored; the token itself never reaches the row.
    row = main.repo.get_share(created["id"])
    assert row["token_hash"] == shares.fingerprint(token)
    assert token not in json.dumps(dict(row))

    r = _redeem(token)
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith(main.settings.s3_endpoint)
    assert "X-Amz-Signature" in location
    assert "X-Amz-Expires=60" in location  # share_presign_ttl
    # The redirect target must not be cached, indexed or leak via Referer.
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert main.repo.get_share(created["id"])["use_count"] == 1


def test_unknown_and_malformed_tokens_answer_the_same_404():
    well_formed_but_unknown = shares.new_token()
    assert _redeem(well_formed_but_unknown).status_code == 404
    assert _redeem("short").status_code == 404
    # Same body for both: the route cannot be used to tell them apart.
    assert _redeem(well_formed_but_unknown).json() == _redeem("short").json()


def test_expired_share_is_404():
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid, expires_in=60)
    # Backdate the expiry rather than sleeping for a minute.
    catalogue_sql.execute(
        "UPDATE object_shares SET expires_at = ? WHERE id = ?",
        (int(time.time()) - 1, created["id"]),
    )
    assert _redeem(created["token"]).status_code == 404


def test_revoked_share_is_404_and_revocation_is_idempotent():
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid)

    r = c.delete(f"/api/v1/objects/{oid}/shares/{created['id']}", headers=headers)
    assert r.status_code == 200, r.text
    first_revoked_at = r.json()["revoked_at"]

    assert _redeem(created["token"]).status_code == 404

    # Revoking twice is a no-op that keeps the original timestamp.
    again = c.delete(f"/api/v1/objects/{oid}/shares/{created['id']}", headers=headers)
    assert again.status_code == 200
    assert again.json()["revoked_at"] == first_revoked_at

    listed = c.get(f"/api/v1/objects/{oid}/shares", headers=headers).json()["items"]
    assert [item["active"] for item in listed] == [False]


def test_max_uses_is_enforced():
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid, max_uses=2)

    assert _redeem(created["token"]).status_code == 302
    assert _redeem(created["token"]).status_code == 302
    assert _redeem(created["token"]).status_code == 404
    row = main.repo.get_share(created["id"])
    assert row["use_count"] == 2

    listed = c.get(f"/api/v1/objects/{oid}/shares", headers=headers).json()["items"]
    assert listed[0]["active"] is False


def test_share_of_an_unavailable_object_is_refused():
    c, headers = _admin()
    # A pending intent has a row but no committed bytes: nothing to share yet.
    oid = c.post("/api/v1/objects/upload-intents", json={
        "display_name": "pending.pdf", "size_bytes": 10,
    }, headers=headers).json()["id"]
    r = c.post(f"/api/v1/objects/{oid}/share", json={}, headers=headers)
    assert r.status_code == 409, r.text


def test_service_identity_cannot_mint_a_share():
    c, headers = _admin()
    me = c.get("/api/v1/me", headers=headers).json()
    identity = c.post("/api/v1/admin/identities", json={
        "space_id": me["space_id"], "name": "share-probe",
        "scopes": ["objects:read", "objects:write"],
    }, headers=headers)
    assert identity.status_code == 200, identity.text
    token = identity.json()["token"]

    oid = _object(c, headers, name="service.pdf")
    # A machine token can read its space, but minting a public link is a human
    # action: a leaked token must not be able to create one.
    r = client.post(
        f"/api/v1/objects/{oid}/share", json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text


def test_create_requires_csrf():
    c, headers = _admin()
    oid = _object(c, headers)
    r = c.post(f"/api/v1/objects/{oid}/share", json={})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "csrf validation failed"


def test_share_is_owner_scoped():
    c, headers = _admin()
    oid = _object(c, headers)
    other, other_headers = _user()
    # Another human cannot see the object, so it does not exist for them.
    r = other.post(f"/api/v1/objects/{oid}/share", json={}, headers=other_headers)
    assert r.status_code == 404, r.text
    assert other.get(
        f"/api/v1/objects/{oid}/shares", headers=other_headers
    ).status_code == 404


def test_inline_is_refused_for_active_content():
    c, headers = _admin()
    html = _object(c, headers, name="page.html", content_type="text/html")
    r = c.post(f"/api/v1/objects/{html}/share",
               json={"content_disposition": "inline"}, headers=headers)
    assert r.status_code == 422, r.text
    # Download-only remains available for the same object.
    assert _share(c, headers, html)["content_disposition"] == "attachment"

    svg = _object(c, headers, name="logo.svg", content_type="image/svg+xml")
    assert c.post(f"/api/v1/objects/{svg}/share",
                  json={"content_disposition": "inline"},
                  headers=headers).status_code == 422

    # A renderable, non-scriptable type is allowed inline.
    pdf = _object(c, headers)
    assert _share(c, headers, pdf, content_disposition="inline")[
        "content_disposition"
    ] == "inline"


def test_expires_in_above_the_ceiling_is_refused():
    c, headers = _admin()
    oid = _object(c, headers)
    r = c.post(f"/api/v1/objects/{oid}/share",
               json={"expires_in": main.settings.share_ttl_max + 1}, headers=headers)
    assert r.status_code == 422, r.text
    # The boundary itself is accepted.
    assert _share(c, headers, oid, expires_in=main.settings.share_ttl_max)[
        "expires_in"
    ] == main.settings.share_ttl_max


def test_revocation_by_a_foreign_user_is_forbidden():
    """Defence in depth: a share row that names someone else cannot be revoked."""
    c, headers = _user()
    oid = _object(c, headers)
    created = _share(c, headers, oid)
    catalogue_sql.execute(
        "UPDATE object_shares SET created_by = ? WHERE id = ?",
        (str(uuid.uuid4()), created["id"]),
    )
    r = c.delete(f"/api/v1/objects/{oid}/shares/{created['id']}", headers=headers)
    assert r.status_code == 403, r.text
    assert _redeem(created["token"]).status_code == 302  # still live, untouched


def test_audit_records_share_events_without_the_token():
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid)
    _redeem(created["token"])
    c.delete(f"/api/v1/objects/{oid}/shares/{created['id']}", headers=headers)

    with open(main.audit_path(), encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    related = [e for e in events if e.get("share_id") == created["id"]]
    actions = {e["action"] for e in related}
    assert {"share-create", "share-access", "share-revoke"} <= actions

    # Never the working credential, never the redirect target.
    raw = json.dumps(related)
    assert created["token"] not in raw
    assert "X-Amz-Signature" not in raw


def test_purge_removes_share_rows(monkeypatch):
    class HealthyS3:
        def delete_object(self, Bucket, Key):
            return {}

    monkeypatch.setattr(main, "s3ops", HealthyS3())
    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid)

    assert c.post(f"/api/v1/objects/{oid}/purge", headers=headers).status_code == 200
    # The row is gone, so a still-bookmarked link cannot resolve to anything.
    assert main.repo.get_share(created["id"]) is None
    assert _redeem(created["token"]).status_code == 404


def test_share_url_is_absolute_only_when_a_base_is_configured(monkeypatch):
    c, headers = _admin()
    oid = _object(c, headers)
    # Default (no AURA_SHARE_BASE_URL): a path, never derived from the Host header.
    assert _share(c, headers, oid)["url"].startswith("/s/")
    monkeypatch.setattr(main.settings, "share_base_url", "https://app.example.test")
    created = _share(c, headers, oid)
    assert created["url"] == f"https://app.example.test/s/{created['token']}"


def test_helpers_refuse_bad_tokens_and_sanitize_the_filename():
    # Shape gate: only the 43-char url-safe form can match a stored fingerprint.
    assert shares.is_well_formed(shares.new_token())
    for bad in ("", "short", "a" * 42, "a" * 44, "../" + "a" * 40, "a" * 43 + "\n"):
        assert not shares.is_well_formed(bad)

    # Only non-executable types may render inline; parameters are ignored.
    assert shares.inline_allowed("application/pdf")
    assert shares.inline_allowed("IMAGE/PNG; charset=binary")
    assert not shares.inline_allowed("text/html")
    assert not shares.inline_allowed("image/svg+xml")
    assert not shares.inline_allowed("application/xhtml+xml")

    # The user-controlled name cannot break out of the header: quotes,
    # backslashes and control characters are removed, RFC 5987 carries the rest.
    header = shares.content_disposition_header(
        "attachment", 'evil"; filename="x.sh\r\nInjected: 1'
    )
    assert "\r" not in header and "\n" not in header
    assert header.count('"') == 2  # only the quoted ASCII filename
    assert "Injected" not in header.split('filename=')[0]
    assert header.startswith("attachment; filename=")
    assert "filename*=UTF-8''" in header
    # An empty/garbage name still yields a usable download name.
    assert 'filename="download"' in shares.content_disposition_header("inline", "\x00")


def test_consume_share_is_atomic_under_concurrency():
    """Eight threads race for a single-use link: exactly one may win."""
    import threading

    c, headers = _admin()
    oid = _object(c, headers)
    created = _share(c, headers, oid, max_uses=1)

    results: list[bool] = []
    lock = threading.Lock()

    def take():
        won = main.repo.consume_share(created["id"], int(time.time()))
        with lock:
            results.append(won)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert results.count(True) == 1, results
    assert main.repo.get_share(created["id"])["use_count"] == 1
