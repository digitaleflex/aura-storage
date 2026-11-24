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
from tests import catalogue_sql  # noqa: E402
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
    # The fake Google subject is shared by the whole module: never leak a
    # premium promotion from one test into the next one.
    catalogue_sql.execute("UPDATE users SET plan = 'free' WHERE role = 'public'")
    yield
    main.reset_login_attempts()
    catalogue_sql.execute("UPDATE users SET plan = 'free' WHERE role = 'public'")


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


def _make_premium(c):
    """Promote the signed-in public account without going through billing."""
    session = main.repo.get_session(c.cookies["aura_public_session"])
    main.repo.set_user_plan(session["user_id"], "premium")
    return c


def test_google_login_public_role_and_logout():
    slug = _published_pack()
    c = _sign_in(TestClient(main.app))

    me = c.get("/api/public/me")
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "public"
    assert me.json()["plan"] == "free"  # product plan, not an object capability
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


def test_premium_email_allowlist_promotes_the_account(monkeypatch):
    monkeypatch.setattr(main.settings, "premium_emails", ("READER@example.com",))
    c = _sign_in(TestClient(main.app))
    assert c.get("/api/public/me").json()["plan"] == "premium"
    # A promotion is never undone by a later sign-in with a different list.
    monkeypatch.setattr(main.settings, "premium_emails", ())
    assert _sign_in(c).get("/api/public/me").json()["plan"] == "premium"


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
    catalogue_sql.execute(
        "UPDATE objects SET cover_key = ? WHERE id = ?", ("covers/x.jpg", item["id"]))
    monkeypatch.setattr(main, "presigned_get", lambda *a, **k: "https://s3.example/c.jpg")
    r = c.get(f"/covers/{item['id']}.jpg", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["cache-control"] == "private, max-age=300"


def test_public_endpoints_are_rate_limited_per_client(monkeypatch):
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "media", 3)
    monkeypatch.setattr(main.settings, "public_media_require_auth", False)
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
    catalogue_sql.execute(
        "UPDATE objects SET duration_seconds = ?, size_bytes = ?, content_type = ? WHERE id = ?",
        (duration, size, content_type, row["id"]))
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


def test_streaming_is_signed_in_and_explicit_download_is_premium(monkeypatch):
    _, media_slug, _ = _book()
    anon = TestClient(main.app)
    assert anon.get(f"/m/{media_slug}").status_code == 401
    assert anon.get(f"/d/{media_slug}").status_code == 401
    free = _sign_in(TestClient(main.app))
    # Listening is not a paid feature: a free account gets the whole book.
    assert free.get(f"/m/{media_slug}", follow_redirects=False).status_code == 302
    assert free.get(f"/d/{media_slug}").status_code == 403
    premium = _make_premium(free)
    assert premium.get(f"/m/{media_slug}", follow_redirects=False).status_code == 302
    assert premium.get(f"/d/{media_slug}", follow_redirects=False).status_code == 302
    # An allowlisted course embed stays public for listening, never for download.
    monkeypatch.setattr(main.settings, "public_media_open_slugs", (media_slug,))
    assert anon.get(f"/m/{media_slug}", follow_redirects=False).status_code == 302
    assert anon.get(f"/d/{media_slug}").status_code == 401


def test_share_link_for_a_published_book_is_premium_only():
    _, _, oid = _book()
    admin, headers = _admin()
    created = admin.post(f"/api/v1/objects/{oid}/share", json={}, headers=headers)
    assert created.status_code == 200, created.text
    token = created.json()["token"]

    anon = TestClient(main.app)
    assert anon.get(f"/s/{token}", follow_redirects=False).status_code == 404
    free = _sign_in(TestClient(main.app))
    assert free.get(f"/s/{token}", follow_redirects=False).status_code == 404
    premium = _make_premium(free)
    assert premium.get(f"/s/{token}", follow_redirects=False).status_code == 302


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
    catalogue_sql.execute("UPDATE objects SET cover_key = 'c.jpg' WHERE id = ?", (oid,))
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
    assert 'controlsList="nodownload"' in t and "Extrait gratuit · 1 min, sans compte" in t
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
    # 60 s of 600 s = a tenth of the file (+ a 4 KiB margin), never the whole file.
    assert len(r.content) == 60000 // 10 + 4096 == int(r.headers["content-length"])
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


def test_stylesheet_stays_light_regardless_of_the_system_setting():
    css = main.public_ui.ASSETS["portal.css"][0].decode()
    assert "color-scheme:light;" in css
    assert "prefers-color-scheme" not in css
    assert "--bg:#F8F6F1" in css and "--ink:#1D2B39" in css


def test_fallback_cover_shows_the_title_and_author():
    item = {"id": "book-id", "title": "Le Grand Livre", "author": "Alice Auteur"}
    track = main.public_ui._track_html(item)
    assert 'class="cover-fallback"' in track
    assert 'class="cover-title">Le Grand Livre</span>' in track
    assert 'class="cover-author">Alice Auteur</span>' in track
    cover = main.public_book._cover(item)
    assert 'class="cover-title">Le Grand Livre</span>' in cover
    assert 'class="cover-author">Alice Auteur</span>' in cover


def test_track_only_requests_subtitles_when_one_is_linked():
    item = {"id": "book-id", "title": "Livre", "url": "/m/livre"}
    assert 'data-subtitle=""' in main.public_ui._track_html(item)
    item["subtitle_url"] = "/m/livre/subtitles.vtt"
    assert 'data-subtitle="/m/livre/subtitles.vtt"' in main.public_ui._track_html(item)


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
        assert 'name="theme-color" content="#F8F6F1"' in html
        assert "prefers-color-scheme" not in html
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


def test_offline_download_button_is_premium_only():
    _published_pack()
    free = _sign_in(TestClient(main.app))
    page = free.get("/").text
    assert 'id="offline-toggle"' not in page
    assert 'class="premium-hint"' in page
    premium_page = _make_premium(free).get("/").text
    assert 'id="offline-toggle"' in premium_page
    assert 'data-download="/d/' in premium_page
    assert "/portal-assets/offline.js?v=" in premium_page
    _assert_strict_markup(premium_page)


# --------------------------------------------------------------------------
# Sign-in by e-mailed link
# --------------------------------------------------------------------------
from api import magic_link  # noqa: E402

SENT: list[tuple[str, str]] = []


@pytest.fixture
def mail(monkeypatch):
    """Enable the feature and capture mails instead of talking to an SMTP server."""
    SENT.clear()
    monkeypatch.setattr(main.settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(main.settings, "smtp_from", "AURA <no-reply@example.org>")
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    monkeypatch.setattr(magic_link, "send", lambda settings, to, link: SENT.append((to, link)))
    return SENT


def _token_of(link: str) -> str:
    return parse_qs(urlsplit(link).query)["token"][0]


def test_email_sign_in_is_off_until_a_mail_server_is_configured():
    c = TestClient(main.app)
    assert 'name="email"' not in c.get("/").text
    assert c.post("/api/public/auth/email", data={"email": "a@b.fr"}).status_code == 404
    assert c.get("/connexion/lien?token=x").status_code == 404
    assert c.post("/api/public/auth/email/confirm", data={"token": "x"}).status_code == 404


def test_email_link_full_flow_single_use_and_hashed_at_rest(mail):
    anon = TestClient(main.app)
    assert 'action="/api/public/auth/email"' in anon.get("/").text
    r = anon.post("/api/public/auth/email", data={"email": "  Lecteur@Example.ORG "})
    assert r.status_code == 200 and "Vérifiez votre boîte mail" in r.text
    assert len(mail) == 1 and mail[0][0] == "lecteur@example.org"
    link = mail[0][1]
    assert link.startswith("https://testserver/connexion/lien?token=")
    token = _token_of(link)
    stored = catalogue_sql.fetch_all("SELECT * FROM login_links")
    assert token not in str([tuple(x) for x in stored])  # only the hash is stored

    # Opening the link (a mail scanner would too) does NOT use it up.
    for _ in range(2):
        page = anon.get(f"/connexion/lien?token={token}")
        assert page.status_code == 200 and "Me connecter" in page.text
        assert page.headers["referrer-policy"] == "no-referrer"
        _assert_strict_markup(page.text)
    reader = TestClient(main.app)
    done = reader.post("/api/public/auth/email/confirm", data={"token": token}, follow_redirects=False)
    assert done.status_code == 302 and done.headers["location"] == "/"
    assert reader.cookies.get("aura_public_session")
    me = reader.get("/api/public/me").json()
    assert me["email"] == "lecteur@example.org" and me["role"] == "public"
    # Single use: the same token cannot open another session.
    again = TestClient(main.app).post("/api/public/auth/email/confirm", data={"token": token})
    assert again.status_code == 400 and "Lien expiré" in again.text
    assert "Lien expiré" in anon.get(f"/connexion/lien?token={token}").text
    # A second sign-in by link lands on the same account.
    main.reset_login_attempts()
    anon.post("/api/public/auth/email", data={"email": "lecteur@example.org"})
    second = TestClient(main.app)
    second.post("/api/public/auth/email/confirm", data={"token": _token_of(mail[-1][1])})
    assert second.get("/api/public/me").json()["id"] == me["id"]


def test_email_link_expires(mail, monkeypatch):
    anon = TestClient(main.app)
    anon.post("/api/public/auth/email", data={"email": "late@example.org"})
    token = _token_of(mail[0][1])
    real = main.time.time
    monkeypatch.setattr(main.time, "time", lambda: real() + main.settings.email_link_ttl + 5)
    assert anon.get(f"/connexion/lien?token={token}").status_code == 400
    assert anon.post("/api/public/auth/email/confirm", data={"token": token}).status_code == 400


def test_email_request_never_reveals_whether_an_address_is_valid_or_known(mail, monkeypatch):
    anon = TestClient(main.app)
    answers = []
    for value in ("pas-un-mail", "", "a@b", "x@example.org"):
        r = anon.post("/api/public/auth/email", data={"email": value})
        answers.append((r.status_code, r.text))
    assert len({a for a in answers}) == 1  # identical answer, valid or not
    assert [m[0] for m in mail] == ["x@example.org"]
    # Domain restriction applies to the link too, with the same neutral answer.
    monkeypatch.setattr(main.settings, "google_allowed_email_domains", ("ecole.fr",))
    r = anon.post("/api/public/auth/email", data={"email": "intrus@example.org"})
    assert r.status_code == 200 and len(mail) == 1


def test_email_requests_are_rate_limited_per_address_and_per_client(mail):
    anon = TestClient(main.app)
    for _ in range(5):
        assert anon.post("/api/public/auth/email", data={"email": "spam@example.org"}).status_code == 200
    assert len([m for m in mail if m[0] == "spam@example.org"]) == 3  # the rest silently dropped
    blocked = None
    for n in range(12):
        blocked = anon.post("/api/public/auth/email", data={"email": f"u{n}@example.org"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1


def test_email_forms_refuse_another_sites_post(mail):
    anon = TestClient(main.app)
    evil = {"Origin": "https://evil.example"}
    assert anon.post("/api/public/auth/email", data={"email": "a@b.fr"}, headers=evil).status_code == 403
    assert anon.post("/api/public/auth/email/confirm", data={"token": "t"}, headers=evil).status_code == 403
    ok = {"Origin": "https://testserver"}
    assert anon.post("/api/public/auth/email", data={"email": "a@b.fr"}, headers=ok).status_code == 200
    assert mail == [("a@b.fr", mail[0][1])]


def test_wrong_tokens_count_against_the_public_login_budget(mail, monkeypatch):
    monkeypatch.setattr(main.settings, "login_rate_limit", 3)
    anon = TestClient(main.app)
    codes = [anon.post("/api/public/auth/email/confirm", data={"token": f"bad{n}"}).status_code
             for n in range(5)]
    assert codes[:3] == [400, 400, 400] and codes[3:] == [429, 429]


def _google_as(monkeypatch, sub: str, email: str):
    monkeypatch.setattr(google_oauth, "verify_id_token", lambda token: {
        "sub": sub, "email": email, "email_verified": True,
        "aud": CLIENT_ID, "iss": "https://accounts.google.com", "exp": 4102444800})
    return _sign_in(TestClient(main.app))


def test_email_and_google_sign_ins_share_one_account(mail, monkeypatch):
    tag = uuid.uuid4().hex[:8]
    google = _google_as(monkeypatch, f"sub-{tag}", f"lecteur-{tag}@example.org")
    gid = google.get("/api/public/me").json()["id"]
    anon = TestClient(main.app)
    anon.post("/api/public/auth/email", data={"email": f"Lecteur-{tag}@Example.org"})
    via_mail = TestClient(main.app)
    via_mail.post("/api/public/auth/email/confirm", data={"token": _token_of(mail[-1][1])})
    assert via_mail.get("/api/public/me").json()["id"] == gid  # mail -> existing Google account

    # The other way round: e-mail account first, Google afterwards -> same account.
    main.reset_login_attempts()
    anon.post("/api/public/auth/email", data={"email": f"nouveau-{tag}@example.net"})
    first = TestClient(main.app)
    first.post("/api/public/auth/email/confirm", data={"token": _token_of(mail[-1][1])})
    nid = first.get("/api/public/me").json()["id"]
    later = _google_as(monkeypatch, f"new-sub-{tag}", f"nouveau-{tag}@example.net")
    assert later.get("/api/public/me").json()["id"] == nid

    # Two different Google identities are never merged on a shared address.
    other = _google_as(monkeypatch, f"other-sub-{tag}", f"lecteur-{tag}@example.org")
    assert other.get("/api/public/me").json()["id"] not in (None, "")
    assert other.get("/api/public/me").json()["id"] != nid


def test_magic_link_helpers_and_smtp_delivery(monkeypatch):
    assert magic_link.normalize_email(" A@b.fr ") == "a@b.fr"
    for bad in ("", "a@b", "a b@c.fr", "a@@b.fr", "x@y.z", "a@b.fr\nBcc: v@x.fr", "é" * 300 + "@b.fr"):
        assert magic_link.normalize_email(bad) is None, bad
    assert magic_link.hash_token("t") == magic_link.hash_token("t") != magic_link.hash_token("u")
    assert magic_link.new_token() != magic_link.new_token()

    class FakeSMTP:
        instances = []

        def __init__(self, host, port, timeout=None, context=None):
            self.calls = [("connect", host, port)]
            FakeSMTP.instances.append(self)

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): self.calls.append(("starttls",))
        def login(self, user, password): self.calls.append(("login", user))
        def send_message(self, msg): self.calls.append(("send", msg["To"], msg["Subject"], msg.get_content()))

    monkeypatch.setattr(magic_link.smtplib, "SMTP", FakeSMTP)
    cfg = main.settings
    for attr, value in (("smtp_host", "smtp.example.org"), ("smtp_port", 587), ("smtp_user", "u"),
                        ("smtp_password", "p"), ("smtp_from", "no-reply@example.org"), ("smtp_starttls", True)):
        monkeypatch.setattr(cfg, attr, value)
    magic_link.send(cfg, "x@example.org", "https://p.example/connexion/lien?token=abc")
    calls = FakeSMTP.instances[0].calls
    assert [c[0] for c in calls] == ["connect", "starttls", "login", "send"]
    assert calls[-1][1] == "x@example.org" and "https://p.example/connexion/lien?token=abc" in calls[-1][3]
    assert "15 minutes" in calls[-1][3]


# --------------------------------------------------------------------------
# Search, sort, recommendations, 404 page
# --------------------------------------------------------------------------
from api import public_book, public_ui  # noqa: E402


def _item(i, author, title, **kw):
    return {"id": f"id-{i}", "display_name": f"{author} - {title}", "title": title, "author": author,
            "created_at": 1000 + i, "duration_seconds": 600 * (i + 1), "chapters": [], "cover_url": None,
            "url": f"/m/s{i}", "progress_seconds": 0, "favorite": False, **kw}


def test_fold_ignores_accents_and_case_and_sorts_keep_unknown_values_untouched():
    assert public_ui.fold("Éléonore DUPRÉ") == "eleonore dupre"
    items = [_item(0, "Zola", "Germinal"), _item(1, "Éluard", "Capitale"), _item(2, "", "Anonyme", duration_seconds=0)]
    assert [i["id"] for i in public_ui.sort_items(items, "titre")] == ["id-2", "id-1", "id-0"]
    assert [i["id"] for i in public_ui.sort_items(items, "auteur")] == ["id-1", "id-0", "id-2"]  # no author last
    assert [i["id"] for i in public_ui.sort_items(items, "recent")] == ["id-2", "id-1", "id-0"]
    assert [i["id"] for i in public_ui.sort_items(items, "duree")] == ["id-0", "id-1", "id-2"]  # unknown length last
    assert public_ui.sort_items(items, "n-importe-quoi") is items


def test_search_is_accent_insensitive_matches_every_word_and_sort_is_validated(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    _, _, oid = _book()
    catalogue_sql.execute("UPDATE objects SET display_name = ? WHERE id = ?",
                           ("Éléonore Dupré - Le Grand Départ.mp3", oid))
    c = TestClient(main.app)
    assert f'href="/livre/{oid}"' in c.get("/?q=eleonore+depart").text
    assert f'href="/livre/{oid}"' in c.get("/?q=DUPRE").text
    assert f'href="/livre/{oid}"' not in c.get("/?q=eleonore+zzz").text  # every word must match
    page = c.get("/?tri=titre")
    assert 'option value="titre" selected' in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"  # sorted views are not indexed
    assert 'selected' not in c.get("/?tri=hacked%22%3E").text.split('name="tri"')[1].split("</select>")[0].replace('value="" selected', "")


def test_recommendations_follow_the_visitors_own_signals_only():
    books = [_item(0, "Hugo", "Les Misérables", favorite=True), _item(1, "Hugo", "Notre-Dame"),
             _item(2, "Hugo", "Ruy Blas"), _item(3, "Zola", "Germinal", progress_seconds=60),
             _item(4, "Zola", "Nana"), _item(5, "Verne", "Nemo")]
    picks = public_ui.recommend(books)
    assert [b["id"] for b in picks] == ["id-1", "id-2", "id-4"]  # Hugo (3) before Zola (1); Verne: no signal
    assert public_ui.recommend([_item(0, "A", "x"), _item(1, "B", "y")]) == []
    principal = {"id": "u", "csrf": "c", "display_name": "L"}
    html = public_ui.catalog_page(principal, [{"title": "T", "description": "", "items": books}])
    assert 'id="pour-vous"' in html and "Pour vous" in html
    plain = public_ui.catalog_page(principal, [{"title": "T", "description": "", "items": [_item(9, "Q", "r")]}])
    assert 'id="pour-vous"' not in plain


def test_book_page_suggests_what_to_listen_to_next():
    a, b, c = _item(0, "Hugo", "Un"), _item(1, "Hugo", "Deux"), _item(2, "Zola", "Trois")
    html = public_book.book_page(a, "Ma série", [b], None, up_next=[c])
    assert "Du même auteur" in html and "À écouter ensuite" in html and "Ma série" in html
    assert 'href="/livre/id-2"' in html


def test_unknown_portal_address_gets_an_html_404_but_the_api_keeps_json(monkeypatch):
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    c = TestClient(main.app)
    page = c.get("/page-qui-nexiste-pas", headers={"Accept": "text/html"})
    assert page.status_code == 404 and "Page introuvable" in page.text
    assert "content-security-policy" in page.headers
    assert c.get("/page-qui-nexiste-pas").json() == {"detail": "Not Found"}  # no Accept: html -> default
    assert c.get("/api/public/inconnu", headers={"Accept": "text/html"}).json() == {"detail": "Not Found"}
    monkeypatch.setattr(main.settings, "public_domain", "autre.example.org")  # other host: untouched
    assert c.get("/page-qui-nexiste-pas", headers={"Accept": "text/html"}).json() == {"detail": "Not Found"}


def test_player_allows_airplay():
    _published_pack()
    assert 'x-webkit-airplay="allow"' in _sign_in(TestClient(main.app)).get("/").text


# --------------------------------------------------------------------------
# Admin: aggregate portal statistics
# --------------------------------------------------------------------------
def test_portal_stats_count_listeners_completions_and_favorites_without_naming_anyone():
    _, media_slug, oid = _book(duration=1000)
    catalogue_sql.execute("UPDATE objects SET display_name = 'Zola - Germinal.mp3' WHERE id = ?", (oid,))
    readers = []
    for n, position in enumerate((10, 950, 0)):  # started, finished (>=90 %), opened only
        globals()["SUBJECT"] = f"stats-subject-{uuid.uuid4().hex[:6]}-{n}"
        r = _sign_in(TestClient(main.app))
        hdr = {"X-CSRF-Token": r.get("/api/public/me").json()["csrf_token"]}
        r.post("/api/public/progress", json={"object_id": oid, "position_seconds": position}, headers=hdr)
        if n < 2:
            r.put(f"/api/public/favorites/{oid}", headers=hdr)
        readers.append(r)
    globals()["SUBJECT"] = "google-subject-123456"

    c, headers = _admin()
    out = c.get("/api/v1/admin/portal-stats", headers=headers)
    assert out.status_code == 200, out.text
    body = out.json()
    book = next(b for b in body["books"] if b["id"] == oid)
    assert (book["title"], book["author"]) == ("Germinal", "Zola")
    assert book["listeners"] == 2 and book["completed"] == 1 and book["favorites"] == 2
    assert book["completion_rate"] == 0.5
    assert body["totals"]["accounts"] >= 3 and body["totals"]["published_books"] >= 1
    flat = out.text
    assert "reader@example.com" not in flat and media_slug not in flat  # nobody identifiable, no media slug
    assert set(book) == {"id", "title", "author", "listeners", "completed", "completion_rate",
                         "favorites", "views_month"}


def test_portal_stats_require_admin_read():
    assert TestClient(main.app).get("/api/v1/admin/portal-stats").status_code in (401, 403)
    reader = _sign_in(TestClient(main.app))  # a public visitor is not an admin
    assert reader.get("/api/v1/admin/portal-stats").status_code in (401, 403)


# --------------------------------------------------------------------------
# Bookmarks and "resume from your other device"
# --------------------------------------------------------------------------
def _reader_with_book():
    _, _, oid = _book()
    r = _sign_in(TestClient(main.app))
    hdr = {"X-CSRF-Token": r.get("/api/public/me").json()["csrf_token"]}
    return r, hdr, oid


def test_bookmarks_are_added_listed_in_order_and_deleted():
    r, hdr, oid = _reader_with_book()
    later = r.post("/api/public/bookmarks", headers=hdr,
                   json={"object_id": oid, "position_seconds": 300.26, "note": "  Belle citation \n"})
    assert later.status_code == 200, later.text
    r.post("/api/public/bookmarks", headers=hdr, json={"object_id": oid, "position_seconds": 12})
    got = r.get(f"/api/public/bookmarks?object_id={oid}").json()["bookmarks"]
    assert [b["position_seconds"] for b in got] == [12, 300.3]  # ordered by position, rounded
    assert [b["note"] for b in got] == ["", "Belle citation"]
    assert r.delete(f"/api/public/bookmarks/{got[0]['id']}", headers=hdr).status_code == 200
    assert len(r.get(f"/api/public/bookmarks?object_id={oid}").json()["bookmarks"]) == 1
    assert r.delete(f"/api/public/bookmarks/{got[0]['id']}", headers=hdr).status_code == 404  # already gone


def test_bookmarks_are_private_validated_and_capped(monkeypatch):
    r, hdr, oid = _reader_with_book()
    mine = r.post("/api/public/bookmarks", headers=hdr,
                  json={"object_id": oid, "position_seconds": 5}).json()
    assert r.post("/api/public/bookmarks", json={"object_id": oid, "position_seconds": 5}).status_code == 403  # CSRF
    for bad in ({"object_id": oid, "position_seconds": -1}, {"object_id": oid, "position_seconds": 5, "note": "x" * 201},
                {"object_id": oid, "position_seconds": 5, "extra": 1}, {"object_id": "pas-un-uuid", "position_seconds": 5}):
        assert r.post("/api/public/bookmarks", headers=hdr, json=bad).status_code == 422
    assert r.post("/api/public/bookmarks", headers=hdr,
                  json={"object_id": str(uuid.uuid4()), "position_seconds": 5}).status_code == 404
    # Another visitor sees none of it and cannot delete it.
    globals()["SUBJECT"] = "bookmark-other-subject"
    try:
        other = _sign_in(TestClient(main.app))
        ohdr = {"X-CSRF-Token": other.get("/api/public/me").json()["csrf_token"]}
        assert other.get(f"/api/public/bookmarks?object_id={oid}").json()["bookmarks"] == []
        assert other.delete(f"/api/public/bookmarks/{mine['id']}", headers=ohdr).status_code == 404
    finally:
        globals()["SUBJECT"] = "google-subject-123456"
    assert len(r.get(f"/api/public/bookmarks?object_id={oid}").json()["bookmarks"]) == 1
    monkeypatch.setattr(main, "_BOOKMARKS_PER_BOOK", 2)
    assert r.post("/api/public/bookmarks", headers=hdr, json={"object_id": oid, "position_seconds": 6}).status_code == 200
    assert r.post("/api/public/bookmarks", headers=hdr, json={"object_id": oid, "position_seconds": 7}).status_code == 409
    assert TestClient(main.app).get(f"/api/public/bookmarks?object_id={oid}").status_code in (401, 403)


def test_account_deletion_removes_bookmarks():
    r, hdr, oid = _reader_with_book()
    uid = r.get("/api/public/me").json()["id"]
    r.post("/api/public/bookmarks", headers=hdr, json={"object_id": oid, "position_seconds": 5})
    assert main.repo.list_bookmarks(uid, oid)
    assert r.delete("/api/public/me", headers=hdr).status_code == 200
    assert main.repo.list_bookmarks(uid, oid) == []


def test_progress_can_be_read_back_for_the_resume_prompt():
    r, hdr, oid = _reader_with_book()
    assert r.get(f"/api/public/progress?object_id={oid}").json()["position_seconds"] == 0
    r.post("/api/public/progress", headers=hdr, json={"object_id": oid, "position_seconds": 321.5})
    assert r.get(f"/api/public/progress?object_id={oid}").json() == {"object_id": oid, "position_seconds": 321.5}
    assert r.get(f"/api/public/progress?object_id={uuid.uuid4()}").status_code == 404
    assert TestClient(main.app).get(f"/api/public/progress?object_id={oid}").status_code in (401, 403)


def test_player_ships_the_bookmark_panel_and_resume_prompt():
    _book()
    page = _sign_in(TestClient(main.app)).get("/").text
    assert 'id="bookmark-add"' in page and 'id="bookmarks-list"' in page
    assert 'id="sync-prompt"' in page and "/portal-assets/bookmarks.js?v=" in page
    _assert_strict_markup(page)
