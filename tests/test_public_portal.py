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
from api.google_oauth import verify_id_token as real_verify_id_token  # noqa: E402

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
    assert "id=\"fullscreen\"" in page
    assert "id=\"chapters-toggle\"" in page
    assert "chapters-data" in page
    assert "0,5×" in page and "3×" in page


class _FreshVisitor:
    """Sign in as a brand-new Google subject: no listening progress at all."""

    def __enter__(self):
        self._previous = SUBJECT
        globals()["SUBJECT"] = f"visitor-{uuid.uuid4().hex}"
        return _sign_in(TestClient(main.app))

    def __exit__(self, *exc):
        globals()["SUBJECT"] = self._previous
        return False


def test_catalogue_keeps_the_filters_folded_and_lists_authors_in_a_select():
    import re

    _published_pack()
    with _FreshVisitor() as c:
        page = c.get("/").text
        # Books first: the display/filter controls sit in a folded panel.
        assert '<details class="filters-fold" id="filters-fold">' in page
        assert 'id="author-select"' in page
        assert re.search(r"Auteur Test \(\d+\)", page)
        # No per-author pills, no "show all authors" toggle, no author search box.
        assert 'data-author="*"' not in page
        assert 'class="facet"' not in page
        assert 'id="authors-toggle"' not in page
        assert 'id="author-search"' not in page
        # The collections row no longer repeats the "whole library" shortcut.
        assert 'href="#tous" aria-pressed' not in page
        assert page.count(">Toute la bibliothèque<") == 1
        # Nothing was listened to yet: the card says so instead of "Reprendre".
        assert "Pour commencer" in page
        assert "Reprendre l&#x27;écoute</a>" not in page

        # An active filter opens the panel and keeps its choice.
        filtered = c.get("/?auteur=Auteur%20Test&vue=grille").text
        assert '<details class="filters-fold" id="filters-fold" open>' in filtered
        assert re.search(r'<option value="Auteur Test" selected>', filtered)
        assert 'name="vue" value="grille"' in filtered  # the select keeps the view
        assert "Effacer les filtres" in filtered


def test_resume_card_is_not_repeated_in_the_resume_shelf():
    _published_pack()
    with _FreshVisitor() as c:
        csrf = c.get("/api/public/me").json()["csrf_token"]
        items = c.get("/api/public/library").json()["collections"][0]["items"]
        saved = c.post("/api/public/progress", json={
            "object_id": items[0]["id"], "position_seconds": 321.0,
        }, headers={"X-CSRF-Token": csrf})
        assert saved.status_code == 200, saved.text

        page = c.get("/").text
        assert '<p class="eyebrow">Reprendre l&#x27;écoute</p>' in page
        assert "Pour commencer" not in page
        # Only one book in progress: it is the card, so there is no second shelf
        # and the discovery link points at the card itself.
        assert 'id="resume-card"' in page
        assert 'id="resume"' not in page
        assert 'href="#resume-card"' in page


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


def test_chapters_are_exposed_in_the_player_html():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]
    main.repo.replace_audio_chapters(item["id"], [
        {"index": 0, "title": "Ouverture", "start": 12.5, "end": 90.0},
    ])
    page = c.get("/?vue=grille").text
    assert "Ouverture" in page
    assert '"start_seconds": 12.5' in page or '"start_seconds":12.5' in page


def test_progress_and_logout_require_csrf():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]
    assert c.post("/api/public/progress", json={
        "object_id": item["id"], "position_seconds": 5,
    }).status_code == 403
    assert c.post("/api/public/logout").status_code == 403


def test_id_token_validation_rejects_bad_claims(monkeypatch):
    import io
    class Response:
        def __init__(self, claims):
            self._body = io.BytesIO(__import__("json").dumps(claims).encode())
        def read(self):
            return self._body.read()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    def fake(claims):
        monkeypatch.setattr(google_oauth, "urlopen", lambda *a, **k: Response(claims))

    base = {
        "sub": "s", "email": "a@example.com", "email_verified": True,
        "aud": CLIENT_ID, "iss": "https://accounts.google.com", "exp": 4102444800,
    }
    fake(base)
    assert real_verify_id_token("token")["sub"] == "s"

    for change in (
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"email_verified": False},
        {"email": ""},
    ):
        fake({**base, **change})
        with pytest.raises(google_oauth.OAuthError):
            real_verify_id_token("token")


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


def test_public_profile_page_and_update():
    c = _sign_in(TestClient(main.app))
    me = c.get("/api/public/me").json()
    csrf = me["csrf_token"]

    page = c.get("/profil")
    assert page.status_code == 200
    assert "Mon profil" in page.text
    assert "reader@example.com" in page.text
    assert 'readonly' in page.text

    r = c.post("/profil", data={"csrf_token": csrf, "display_name": "Alice Lectrice"})
    assert r.status_code == 200
    assert "Profil mis à jour" in r.text
    assert "Alice Lectrice" in r.text

    me2 = c.get("/api/public/me").json()
    assert me2["display_name"] == "Alice Lectrice"

    r = c.patch("/api/public/me", json={"display_name": "Alice"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Alice"
    assert c.get("/api/public/me").json()["display_name"] == "Alice"


def test_public_profile_requires_csrf_and_auth():
    c = _sign_in(TestClient(main.app))
    assert c.post("/profil", data={"display_name": "X"}).status_code == 403
    assert c.patch("/api/public/me", json={"display_name": "X"}).status_code == 403
    assert c.post("/profil/supprimer", data={}).status_code == 403
    assert c.delete("/api/public/me").status_code == 403

    anon = TestClient(main.app)
    r = anon.get("/profil", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/"


def test_public_account_delete_clears_portal_data():
    slug = _published_pack()
    c = _sign_in(TestClient(main.app))
    csrf = c.get("/api/public/me").json()["csrf_token"]
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]

    saved = c.post("/api/public/progress", json={
        "object_id": item["id"], "position_seconds": 42.0,
    }, headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200

    r = c.post("/profil/supprimer", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert c.get("/api/public/me").status_code == 401

    # Same Google subject signs in again: fresh public account, no old progress.
    c2 = _sign_in(TestClient(main.app))
    me2 = c2.get("/api/public/me").json()
    assert me2["display_name"] == ""
    item2 = c2.get("/api/public/library").json()["collections"][0]["items"][0]
    assert item2["id"] == item["id"]
    assert item2["progress_seconds"] == 0


def test_chapters_are_loaded_with_one_batched_query_not_one_per_book():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]
    main.repo.replace_audio_chapters(item["id"], [
        {"index": 1, "title": "Deux", "start": 60.0, "end": 120.0},
        {"index": 0, "title": "Un", "start": 0.0, "end": 60.0},
    ])
    got = main.repo.get_audio_chapters_map([item["id"], "absent-id"])
    assert [ch["title"] for ch in got[item["id"]]] == ["Un", "Deux"]  # ordered
    assert got["absent-id"] == []
    assert main.repo.get_audio_chapters_map([]) == {}

    calls = []
    real = main.repo.get_audio_chapters
    main.repo.get_audio_chapters = lambda oid: calls.append(oid) or real(oid)
    try:
        library = c.get("/api/public/library").json()["collections"][0]["items"]
    finally:
        main.repo.get_audio_chapters = real
    assert calls == [], "the per-book query must not be used any more"
    assert [ch["title"] for ch in library[0]["chapters"]] == ["Un", "Deux"]


def test_cover_redirect_may_be_cached_briefly(monkeypatch):
    _published_pack()
    c = _sign_in(TestClient(main.app))
    item = c.get("/api/public/library").json()["collections"][0]["items"][0]
    main.repo.conn.execute(
        "UPDATE objects SET cover_key = ? WHERE id = ?", ("covers/x.jpg", item["id"]))
    main.repo.conn.commit()
    monkeypatch.setattr(main, "presigned_get", lambda *a, **k: "https://s3.example/c.jpg")
    r = c.get(f"/covers/{item['id']}.jpg", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["cache-control"] == "private, max-age=300"


def test_public_endpoints_are_rate_limited_per_client(monkeypatch):
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "media", 3)
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "cover", 2)
    codes = [TestClient(main.app).get("/m/inconnu-slug").status_code for _ in range(5)]
    assert codes[:3] == [404, 404, 404]
    assert codes[3:] == [429, 429]
    blocked = TestClient(main.app).get("/m/inconnu-slug")
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
    oid = str(uuid.uuid4())
    codes = [TestClient(main.app).get(f"/covers/{oid}.jpg").status_code for _ in range(3)]
    assert codes == [404, 404, 429]


def test_progress_is_rate_limited(monkeypatch):
    _published_pack()
    reader = _sign_in(TestClient(main.app))
    csrf = reader.get("/api/public/me").json()["csrf_token"]
    item = reader.get("/api/public/library").json()["collections"][0]["items"][0]
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "progress", 2)
    body = {"object_id": item["id"], "position_seconds": 5}
    codes = [reader.post("/api/public/progress", json=body,
                         headers={"X-CSRF-Token": csrf}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


import re  # noqa: E402


def _assert_strict_markup(html: str) -> None:
    """No inline code: the page must pass a CSP without 'unsafe-inline' scripts/styles."""
    assert "<style" not in html
    for tag in re.findall(r"<script\b[^>]*>", html):
        # Data blocks are not executed, so a CSP without 'unsafe-inline' allows them.
        assert "src=" in tag or 'type="application/json"' in tag \
            or 'type="application/ld+json"' in tag, tag
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"
    assert "javascript:" not in html


def test_portal_pages_ship_a_strict_csp_and_no_inline_code(monkeypatch):
    monkeypatch.setattr(main.settings, "s3_endpoint", "https://s3.example.org:8443/x")
    _published_pack()
    anon = TestClient(main.app)
    login = anon.get("/")
    c = _sign_in(TestClient(main.app))
    for response in (login, c.get("/"), c.get("/?vue=grille"), c.get("/profil")):
        assert response.status_code == 200
        csp = response.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "style-src 'self'" in csp
        assert "'unsafe-inline'" not in csp.split("style-src-attr")[0]
        assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
        assert "media-src 'self' https://s3.example.org:8443" in csp
        assert "img-src 'self' https://s3.example.org:8443" in csp
        _assert_strict_markup(response.text)


def test_portal_assets_are_served_immutable_and_only_from_the_public_host(monkeypatch):
    c = TestClient(main.app)
    page = c.get("/").text
    css_url = re.search(r'href="(/portal-assets/portal\.css\?v=[0-9a-f]+)"', page).group(1)
    js_url = re.search(r'src="(/portal-assets/common\.js\?v=[0-9a-f]+)"', page).group(1)
    css = c.get(css_url)
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "immutable" in css.headers["cache-control"]
    assert css.headers["x-content-type-options"] == "nosniff"
    assert "--bronze" in css.text
    assert c.get(js_url).headers["content-type"].startswith("text/javascript")
    again = c.get(css_url, headers={"If-None-Match": css.headers["etag"]})
    assert again.status_code == 304
    assert c.get("/portal-assets/secret.py").status_code == 404
    assert c.get("/portal-assets/..%2Fmain.py").status_code == 404
    monkeypatch.setattr(main.settings, "public_domain", "portail.example.org")
    assert c.get(css_url).status_code == 404


def test_catalogue_loads_player_scripts_and_hands_over_the_csrf_token():
    _published_pack()
    c = _sign_in(TestClient(main.app))
    page = c.get("/").text
    csrf = c.get("/api/public/me").json()["csrf_token"]
    assert f'id="player-bar" data-csrf="{csrf}"' in page
    for name in ("player.js", "shelf.js", "common.js"):
        assert f"/portal-assets/{name}?v=" in page
    player = c.get(re.search(r'src="(/portal-assets/player\.js\?v=[0-9a-f]+)"', page).group(1))
    assert player.status_code == 200 and "__CSRF__" not in player.text
    assert csrf not in player.text  # the token is never baked into a cacheable file


def test_profile_delete_form_uses_data_confirm_instead_of_onsubmit():
    c = _sign_in(TestClient(main.app))
    html = c.get("/profil").text
    assert 'data-confirm="Supprimer définitivement' in html
    assert "onsubmit" not in html


# --------------------------------------------------------------------------
# Browsing without signing in: landing, book page, free preview, sitemap
# --------------------------------------------------------------------------
class _FakeBody:
    def __init__(self, data):
        self.data = data

    def iter_chunks(self, size):
        for start in range(0, len(self.data), size):
            yield self.data[start:start + size]


def _book(duration=600, size=60000, content_type="audio/mpeg"):
    """A published one-book pack; returns (collection slug, object slug, object id)."""
    slug = _published_pack()
    row = main.repo.get_object_by_slug(f"{slug}-ch1")
    main.repo.conn.execute(
        "UPDATE objects SET duration_seconds = ?, size_bytes = ?, content_type = ? WHERE id = ?",
        (duration, size, content_type, row["id"]))
    main.repo.conn.commit()
    return slug, f"{slug}-ch1", row["id"]


def test_anonymous_landing_lists_books_and_never_exposes_the_media_slug(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "portail.example.org")
    _, media_slug, oid = _book()
    r = TestClient(main.app, base_url="https://portail.example.org").get("/")
    assert r.status_code == 200
    assert f'href="/livre/{oid}"' in r.text
    assert "Continuer avec Google" in r.text
    assert media_slug not in r.text and "/m/" not in r.text  # no direct media link
    assert "noindex" not in r.headers.get("x-robots-tag", "")
    assert r.headers["cache-control"] == "public, max-age=60"
    assert "Un livre audio" in r.text
    _assert_strict_markup(r.text)
    # Filtering works without an account and filtered pages are not indexed.
    none = TestClient(main.app, base_url="https://portail.example.org").get("/?q=zzzz")
    assert "Aucun livre ne correspond" in none.text
    assert none.headers["x-robots-tag"] == "noindex, nofollow"


def test_landing_falls_back_to_sign_in_page_when_browsing_is_disabled(monkeypatch):
    monkeypatch.setattr(main.settings, "public_browse", False)
    _book()
    anon = TestClient(main.app)
    r = anon.get("/")
    assert "Entrez dans votre bibliothèque" in r.text
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert anon.get("/livre/" + str(uuid.uuid4())).status_code == 404
    assert anon.get("/sitemap.xml").status_code == 404


def test_book_page_has_share_metadata_chapters_and_the_right_call_to_action(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    _, media_slug, oid = _book(duration=3725)
    main.repo.replace_audio_chapters(oid, [
        {"index": 0, "title": "Ouverture", "start": 0.0, "end": 60.0},
        {"index": 1, "title": "La rencontre", "start": 65.0, "end": 900.0},
    ])
    main.repo.conn.execute("UPDATE objects SET cover_key = 'c.jpg' WHERE id = ?", (oid,))
    main.repo.conn.commit()
    anon = TestClient(main.app)
    page = anon.get(f"/livre/{oid}")
    assert page.status_code == 200, page.text
    t = page.text
    assert '<meta property="og:title" content="Chapitre 1.mp3 — AURA">' in t or "og:title" in t
    assert 'property="og:image" content="https://testserver/covers/' in t
    assert f'rel="canonical" href="https://testserver/livre/{oid}"' in t
    assert '"@type": "Audiobook"' in t and "Ouverture" in t and "La rencontre" in t
    assert "1 h 02 min" in t and "Extrait gratuit" in t
    assert f'src="/extrait/{oid}"' in t
    assert "Continuer avec Google pour écouter en entier" in t
    assert media_slug not in t and "/m/" not in t
    assert "noindex" not in page.headers.get("x-robots-tag", "")
    assert "wa.me" in t and "data-copy=" in t
    _assert_strict_markup(t)
    # Signed in: the call to action starts the book in the player.
    reader = _sign_in(TestClient(main.app))
    mine = reader.get(f"/livre/{oid}").text
    assert f'href="/?lecture={oid}"' in mine and "Écouter le livre" in mine
    assert "Continuer avec Google pour écouter" not in mine
    # The catalogue exposes the id the player is told to start with.
    assert f'data-object-id="{oid}"' in reader.get("/").text


def test_unknown_or_malformed_book_is_a_404_page_not_a_json_error():
    for bad in (str(uuid.uuid4()), "pas-un-uuid"):
        r = TestClient(main.app).get(f"/livre/{bad}")
        assert r.status_code == 404
        assert "Livre introuvable" in r.text
        assert r.headers["x-robots-tag"] == "noindex, nofollow"


def test_free_preview_streams_only_the_first_part_of_an_mp3(monkeypatch):
    _, _, oid = _book(duration=600, size=60000)  # 10 min, 100 B/s
    asked = {}

    def fake_get_object(**kwargs):
        asked.update(kwargs)
        end = int(kwargs["Range"].split("-")[1]) + 1
        return {"Body": _FakeBody(b"x" * end)}

    monkeypatch.setattr(main.s3ops, "get_object", fake_get_object)
    r = TestClient(main.app).get(f"/extrait/{oid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    # 120 s of 600 s = a fifth of the file (+ a 4 KiB margin), never the whole file.
    assert len(r.content) == 60000 // 5 + 4096 == int(r.headers["content-length"])
    assert asked["Range"] == f"bytes=0-{len(r.content) - 1}"
    assert r.headers["accept-ranges"] == "none"


def test_preview_is_refused_when_it_cannot_be_cut_safely(monkeypatch):
    called = []
    monkeypatch.setattr(main.s3ops, "get_object", lambda **k: called.append(k))
    _, _, m4a = _book(content_type="audio/mp4")
    assert TestClient(main.app).get(f"/extrait/{m4a}").status_code == 404
    _, _, unknown_length = _book(duration=0)
    assert TestClient(main.app).get(f"/extrait/{unknown_length}").status_code == 404
    _, _, mp3 = _book()
    monkeypatch.setattr(main.settings, "public_preview_seconds", 0)
    assert TestClient(main.app).get(f"/extrait/{mp3}").status_code == 404
    assert TestClient(main.app).get(f"/extrait/{uuid.uuid4()}").status_code == 404
    assert called == []
    page = TestClient(main.app).get(f"/livre/{mp3}").text
    assert "Extrait gratuit" not in page  # no player when there is no preview


def test_preview_does_not_serve_unpublished_objects(monkeypatch):
    _, media_slug, oid = _book()
    c, headers = _admin()
    assert c.put(f"/api/v1/objects/{oid}/publication",
                 json={"slug": media_slug, "published": False}, headers=headers).status_code == 200
    monkeypatch.setattr(main.s3ops, "get_object", lambda **k: {"Body": _FakeBody(b"x")})
    assert TestClient(main.app).get(f"/extrait/{oid}").status_code == 404


def test_sitemap_and_robots_describe_only_the_browsable_pages(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "portail.example.org")
    _, media_slug, oid = _book()
    web = TestClient(main.app, base_url="https://portail.example.org")
    sitemap = web.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert f"<loc>https://portail.example.org/livre/{oid}</loc>" in sitemap.text
    assert "<loc>https://portail.example.org/</loc>" in sitemap.text
    assert media_slug not in sitemap.text
    robots = web.get("/robots.txt").text
    assert "Allow: /livre/" in robots and "Disallow: /" in robots
    assert "Sitemap: https://portail.example.org/sitemap.xml" in robots
    assert web.get("/api/public/library").status_code in (401, 403)  # still private


# --------------------------------------------------------------------------
# Favourites and dark mode
# --------------------------------------------------------------------------
def test_favorites_are_private_idempotent_csrf_protected_and_shown_in_the_catalogue():
    _, _, oid = _book()
    reader = _sign_in(TestClient(main.app))
    csrf = reader.get("/api/public/me").json()["csrf_token"]
    hdr = {"X-CSRF-Token": csrf}
    assert reader.put(f"/api/public/favorites/{oid}").status_code == 403  # no CSRF
    for _ in range(2):  # twice: idempotent
        r = reader.put(f"/api/public/favorites/{oid}", headers=hdr)
        assert r.status_code == 200 and r.json() == {"object_id": oid, "favorite": True}
    cols = reader.get("/api/public/library").json()["collections"]
    mine = next(i for col in cols for i in col["items"] if i["id"] == oid)
    assert mine["favorite"] is True
    page = reader.get("/").text
    assert 'id="favoris"' in page and "Mes favoris" in page
    assert f'data-favorite="{oid}" aria-pressed="true"' in page
    _assert_strict_markup(page)
    assert f'data-favorite="{oid}" aria-pressed="true"' in reader.get(f"/livre/{oid}").text

    globals()["SUBJECT"] = "another-favorites-subject"
    try:
        other = _sign_in(TestClient(main.app))
        assert f'data-favorite="{oid}" aria-pressed="false"' in other.get("/").text
        assert 'id="favoris"' not in other.get("/").text
    finally:
        globals()["SUBJECT"] = "google-subject-123456"

    r = reader.delete(f"/api/public/favorites/{oid}", headers=hdr)
    assert r.status_code == 200 and r.json()["favorite"] is False
    assert 'id="favoris"' not in reader.get("/").text


def test_favorites_refuse_unpublished_unknown_and_anonymous():
    _, media_slug, oid = _book()
    reader = _sign_in(TestClient(main.app))
    hdr = {"X-CSRF-Token": reader.get("/api/public/me").json()["csrf_token"]}
    assert reader.put(f"/api/public/favorites/{uuid.uuid4()}", headers=hdr).status_code == 404
    assert reader.put("/api/public/favorites/pas-un-uuid", headers=hdr).status_code in (400, 404, 422)
    assert TestClient(main.app).put(f"/api/public/favorites/{oid}").status_code in (401, 403)
    c, h = _admin()
    assert c.put(f"/api/v1/objects/{oid}/publication",
                 json={"slug": media_slug, "published": False}, headers=h).status_code == 200
    assert reader.put(f"/api/public/favorites/{oid}", headers=hdr).status_code == 404


def test_deleting_the_account_removes_the_favorites():
    _, _, oid = _book()
    reader = _sign_in(TestClient(main.app))
    hdr = {"X-CSRF-Token": reader.get("/api/public/me").json()["csrf_token"]}
    uid = reader.get("/api/public/me").json()["id"]
    reader.put(f"/api/public/favorites/{oid}", headers=hdr)
    assert main.repo.get_favorite_ids(uid, [oid]) == {oid}
    assert reader.delete("/api/public/me", headers=hdr).status_code == 200
    assert main.repo.get_favorite_ids(uid, [oid]) == set()


def test_stylesheet_follows_the_system_dark_setting():
    css = main.public_ui.ASSETS["portal.css"][0].decode()
    assert "color-scheme:light dark" in css
    assert "@media (prefers-color-scheme: dark)" in css
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    assert "--bg:#10171e" in dark and "--ink:#EDE6D8" in dark


# --------------------------------------------------------------------------
# Installable app and offline listening
# --------------------------------------------------------------------------
def test_service_worker_is_served_from_the_root_with_the_right_headers():
    c = TestClient(main.app)
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["service-worker-allowed"] == "/"
    assert r.headers["cache-control"] == "no-cache"  # a new worker must be picked up at once
    body = r.text
    assert "'aura-audio'" in body and "Range" in body.replace("range", "Range")
    assert "/api/public/logout" in body  # personal pages are wiped on sign-out
    off = c.get("/hors-ligne")
    assert off.status_code == 200 and "Vous êtes hors connexion" in off.text
    assert "content-security-policy" in off.headers


def test_service_worker_and_offline_page_follow_the_public_host_rules(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "portail.example.org")
    other = TestClient(main.app)  # Host: testserver
    assert other.get("/sw.js").status_code == 404
    assert other.get("/hors-ligne").status_code == 404
    monkeypatch.setattr(main.settings, "public_domain", "")
    assert TestClient(main.app).get("/sw.js").status_code == 404  # portal not configured


def test_pages_declare_the_manifest_icons_and_theme_colours():
    c = _sign_in(TestClient(main.app))
    for html in (TestClient(main.app).get("/").text, c.get("/").text, c.get("/profil").text):
        assert 'rel="manifest" href="/portal-assets/manifest.webmanifest?v=' in html
        assert 'rel="apple-touch-icon"' in html and 'rel="icon"' in html
        assert 'name="theme-color"' in html and "prefers-color-scheme: dark" in html
    manifest = c.get(re.search(r'href="(/portal-assets/manifest\.webmanifest\?v=[0-9a-f]+)"',
                               c.get("/").text).group(1))
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    data = manifest.json()
    assert data["start_url"] == "/" and data["scope"] == "/" and data["display"] == "standalone"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])
    for icon in data["icons"]:  # every declared icon really is served
        name = icon["src"].rsplit("/", 1)[1]
        assert name in main.public_ui.ASSETS, name
    png = main.public_ui.ASSETS["icon-512.png"][0]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_csp_allows_the_manifest_worker_and_the_download_fetch(monkeypatch):
    monkeypatch.setattr(main.settings, "s3_endpoint", "https://s3.example.org:8443")
    csp = main._portal_csp()
    assert "manifest-src 'self'" in csp and "worker-src 'self'" in csp
    assert "connect-src 'self' https://s3.example.org:8443" in csp


def test_player_offers_the_offline_download_button():
    _published_pack()
    page = _sign_in(TestClient(main.app)).get("/").text
    assert 'id="offline-toggle"' in page and "/portal-assets/offline.js?v=" in page
    _assert_strict_markup(page)
