"""Phase 0 du portail public : cache, fin de session, slugs restreints, débit.

Ces tests sont volontairement dans un fichier séparé de ``test_public_portal.py``
pour ne pas toucher aux travaux en cours sur ce dernier.
"""
import os
from pathlib import Path

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

OID = "11111111-2222-4333-8444-555555555555"
SLUG = "livre-phase0"
CATALOG = [{
    "id": "col-phase0",
    "title": "Un livre",
    "description": "Roman",
    "items": [{
        "id": OID,
        "title": "Chapitre 1",
        "author": "Auteur Test",
        "duration_seconds": 120,
        "chapters": [{"title": "Chapitre 1", "start": 0}],
    }],
}]


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    main.reset_login_attempts()
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    monkeypatch.setattr(main, "_public_catalog", lambda: CATALOG)
    yield
    main.reset_login_attempts()


def test_anonymous_book_page_is_publicly_cacheable():
    r = TestClient(main.app).get(f"/livre/{OID}")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "public, max-age=60"
    assert r.headers["vary"] == "Cookie"


def test_personalised_book_page_is_never_cached(monkeypatch):
    monkeypatch.setattr(
        main, "authenticate_public",
        lambda request: {"id": "reader-1", "csrf": "csrf-token"},
    )
    r = TestClient(main.app).get(f"/livre/{OID}")
    assert r.status_code == 200, r.text
    assert "private" in r.headers["cache-control"]
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["vary"] == "Cookie"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert 'name="csrf-token"' in r.text


def test_restricted_slug_does_not_resolve(monkeypatch):
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", (SLUG,))
    r = TestClient(main.app).get(f"/m/{SLUG}", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers


def test_hls_and_subtitle_routes_are_rate_limited(monkeypatch):
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "hls", 2)
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "subtitle", 2)
    main.reset_login_attempts()
    client = TestClient(main.app)

    for path in (f"/hls/{SLUG}.m3u8", f"/m/{SLUG}/subtitles.vtt"):
        main.reset_login_attempts()
        assert client.get(path).status_code == 404  # slug inconnu, mais compté
        assert client.get(path).status_code == 404
        limited = client.get(path)
        assert limited.status_code == 429, limited.text
        assert limited.headers.get("retry-after")


def test_service_worker_forgets_pages_on_session_end():
    source = (Path(main.__file__).parent / "portal_assets" / "sw.js").read_text()
    assert "event.data.type === 'forget-pages'" in source
    assert "'/profil/supprimer'" in source
    assert "response.status === 401" in source
