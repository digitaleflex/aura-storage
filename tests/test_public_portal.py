"""Public portal: Google sign-in, public role and published catalogue.

Offline: Google is mocked, no network call and no real S3 endpoint.
"""
import os
import uuid
from urllib.parse import parse_qs, urlsplit

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
from api.auth import hash_password  # noqa: E402
from api import google_oauth  # noqa: E402

CLIENT_ID = "test-client.apps.googleusercontent.com"
SUBJECT = "google-subject-123456"
EXCHANGES: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    main.reset_login_attempts()
    EXCHANGES.clear()
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    monkeypatch.setattr(main.settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(main.settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(main.settings, "google_allowed_email_domains", ())

    def fake_exchange(code: str, verifier: str) -> dict:
        EXCHANGES.append((code, verifier))
        return {"id_token": "fake"}

    monkeypatch.setattr(google_oauth, "exchange_code", fake_exchange)
    monkeypatch.setattr(google_oauth, "verify_id_token", lambda token: {
        "sub": SUBJECT, "email": "reader@example.com", "email_verified": True,
        "aud": CLIENT_ID, "iss": "https://accounts.google.com", "exp": 4102444800,
    })
    yield
    main.reset_login_attempts()


def _admin():
    username = f"portal-admin-{uuid.uuid4().hex[:8]}"
    password = "portal-test-password"
    main.repo.create_user(username, hash_password(password), role="admin")
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _published_pack():
    c, headers = _admin()
    oid = c.post("/api/v1/objects/upload-intents", json={
        "display_name": "Auteur Test - Chapitre 1.mp3", "size_bytes": 5000,
        "content_type": "audio/mpeg",
    }, headers=headers).json()["id"]
    main.repo.mark_available(oid, 5000, uuid.uuid4().hex)
    slug = f"livre-{uuid.uuid4().hex[:8]}"
    mark = c.put(f"/api/v1/objects/{oid}/publication", json={
        "slug": f"{slug}-ch1", "published": True,
    }, headers=headers)
    assert mark.status_code == 200, mark.text
    col = c.post("/api/v1/collections", json={
        "slug": slug, "title": "Un livre audio", "description": "Roman",
    }, headers=headers).json()["id"]
    assert c.put(f"/api/v1/collections/{col}/items",
                 json={"object_ids": [oid]}, headers=headers).status_code == 200
    assert c.patch(f"/api/v1/collections/{col}", json={"published": True},
                   headers=headers).status_code == 200
    return slug


def _sign_in(c):
    start = c.get("/api/public/auth/google", follow_redirects=False)
    assert start.status_code == 302, start.text
    assert "accounts.google.com" in start.headers["location"]
    stored = c.cookies.get("aura_public_oauth")
    assert stored
    expected_state, separator, expected_verifier = stored.partition(".")
    assert separator
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    assert state == expected_state
    callback = c.get(
        f"/api/public/auth/callback?code=abc&state={state}", follow_redirects=False
    )
    assert callback.status_code == 302, callback.text
    # The verifier from the cookie must be the one sent to Google (PKCE S256).
    assert EXCHANGES[-1] == ("abc", expected_verifier)
    assert callback.headers["location"] == "/"
    assert c.cookies.get("aura_public_session")
    return c


def test_google_login_public_role_and_logout():
    slug = _published_pack()
    c = _sign_in(TestClient(main.app))

    me = c.get("/api/public/me")
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "public"
    assert me.json()["email"] == "reader@example.com"
    csrf = me.json()["csrf_token"]

    library = c.get("/api/public/library")
    assert library.status_code == 200, library.text
    packs = [p for p in library.json()["collections"] if p["slug"] == slug]
    assert len(packs) == 1
    assert packs[0]["title"] == "Un livre audio"
    assert packs[0]["items"][0]["url"] == f"/m/{slug}-ch1"

    page = c.get("/")
    assert page.status_code == 200, page.text
    assert "<audio" in page.text and f"/m/{slug}-ch1" in page.text
    assert "Un livre audio" in page.text

    # The public role has zero object capability on the private API.
    private = TestClient(main.app)
    private.cookies.set("aura_public_session", c.cookies["aura_public_session"])
    assert private.get("/api/v1/objects").status_code == 401
    assert private.get("/api/v1/admin/stats").status_code == 401

    assert c.post("/api/public/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert c.get("/api/public/me").status_code == 401


def test_view_modes_facets_and_cover_route():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    page = c.get("/").text
    assert "view-liste" in page
    assert "Auteur Test" in page  # facet derived from the file name
    assert "Reprendre l&#x27;écoute" in page or "Reprendre l'écoute" in page
    assert "view-grille" in c.get("/?vue=grille").text
    assert "class=\"hero\"" in c.get("/?vue=immersif").text
    assert "Chapitre 1" in c.get("/?q=chapitre").text
    assert c.get("/?vue=bogus").status_code == 200


def test_cover_route_is_404_without_extracted_art():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]
    assert item["cover_url"] is None
    assert c.get(f"/covers/{item['id']}.jpg").status_code == 404


def test_listening_progress_is_saved_for_the_visitor_only():
    _published_pack()
    reader = _sign_in(TestClient(main.app))
    csrf = reader.get("/api/public/me").json()["csrf_token"]
    item = reader.get("/api/public/library").json()["collections"][0]["items"][0]

    saved = reader.post("/api/public/progress", json={
        "object_id": item["id"], "position_seconds": 123.5,
    }, headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200, saved.text

    fresh = _sign_in(TestClient(main.app))
    fresh_item = fresh.get("/api/public/library").json()["collections"][0]["items"][0]
    assert fresh_item["progress_seconds"] == 123.5

    # The same book is invisible to another Google user.
    monkeypatch_sub = SUBJECT
    globals()["SUBJECT"] = "another-subject"
    try:
        other = _sign_in(TestClient(main.app))
        other_item = other.get("/api/public/library").json()["collections"][0]["items"][0]
        assert other_item["progress_seconds"] == 0
    finally:
        globals()["SUBJECT"] = monkeypatch_sub


def test_progress_rejects_unpublished_objects():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    csrf = c.get("/api/public/me").json()["csrf_token"]
    unknown = "00000000-0000-4000-8000-000000000000"
    r = c.post("/api/public/progress", json={
        "object_id": unknown, "position_seconds": 10,
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 404


def test_callback_rejects_bad_state_and_wrong_domain(monkeypatch):
    c = TestClient(main.app)
    assert c.get("/api/public/auth/callback?code=abc&state=forged").status_code == 401

    monkeypatch.setattr(main.settings, "google_allowed_email_domains", ("allowed.test",))
    c = TestClient(main.app)
    start = c.get("/api/public/auth/google", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    callback = c.get(
        f"/api/public/auth/callback?code=abc&state={state}", follow_redirects=False
    )
    assert callback.status_code == 401
    assert c.cookies.get("aura_public_session") is None


def test_anonymous_and_admin_cookies_cannot_enter_the_portal():
    anonymous = TestClient(main.app)
    page = anonymous.get("/")
    assert page.status_code == 200
    assert "Continuer avec Google" in page.text
    assert "<audio" not in page.text
    assert anonymous.get("/api/public/me").status_code == 401

    admin, _ = _admin()
    assert admin.get("/api/public/me").status_code == 401
    admin_page = admin.get("/")
    assert admin_page.status_code == 200
    assert "Continuer avec Google" in admin_page.text


def test_unconfigured_portal_fails_closed(monkeypatch):
    monkeypatch.setattr(main.settings, "google_client_id", "")
    c = TestClient(main.app)
    assert c.get("/api/public/auth/google").status_code == 503
    assert c.get("/api/public/auth/callback?code=abc&state=x").status_code == 503
