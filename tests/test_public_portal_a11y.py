"""Phase 1 du portail public : accessibilité du lecteur et perf du catalogue."""
import os
import time
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
from api import public_ui  # noqa: E402

OID = "22222222-3333-4444-8555-666666666666"
ASSETS = Path(main.__file__).parent / "portal_assets"

CATALOG = [{
    "id": "col-a11y",
    "slug": "livre-a11y",
    "title": "Un livre",
    "description": "",
    "updated_at": int(time.time()),
    "items": [{
        "id": OID,
        "title": "Chapitre 1",
        "display_name": "Auteur - Chapitre 1.mp3",
        "author": "Auteur",
        "duration_seconds": 120,
        "chapters": [{"title": "Chapitre 1", "start": 0}],
        "url": f"/m/livre-a11y",
    }],
}]


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    main.reset_login_attempts()
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    monkeypatch.setattr(main, "_public_catalog", lambda: CATALOG)
    monkeypatch.setattr(main.repo, "get_published_collections_for_object", lambda oid: [
        {"id": "col-a11y", "title": "Un livre", "updated_at": 0},
    ])
    monkeypatch.setattr(main, "_library_items", lambda col, only_published=False: CATALOG[0]["items"])
    monkeypatch.setattr(main.repo, "get_audio_chapters_map", lambda ids: {})
    monkeypatch.setattr(main.repo, "get_object_unscoped", lambda oid: {
        "id": oid, "status": "available", "published_at": int(time.time()),
        "public_slug": "livre-a11y", "bucket": "aura", "object_key": f"aura/{oid}",
        "content_type": "audio/mpeg", "size_bytes": 1000,
        "display_name": "Auteur - Chapitre 1.mp3",
    })
    yield
    main.reset_login_attempts()


def _page(path: str):
    return TestClient(main.app).get(path)


def test_public_pages_have_skip_link_and_main_target():
    landing = _page("/")
    assert landing.status_code == 200, landing.text[:200]
    assert 'class="skip-link" href="#main"' in landing.text
    assert 'id="main"' in landing.text

    book = _page(f"/livre/{OID}")
    assert book.status_code == 200, book.text[:200]
    assert 'class="skip-link" href="#main"' in book.text
    assert '<main class="library book" id="main">' in book.text
    assert 'aria-current="false"' not in book.text


def test_catalog_page_renders_dialogs_and_no_false_aria_current():
    html = public_ui.catalog_page(
        {"id": "reader", "display_name": "Lecteur", "csrf": "tok"},
        CATALOG, query="", view="liste", authors=["Auteur"], sort="titre",
    )
    assert 'id="sleep-dialog"' in html and 'id="note-dialog"' in html
    assert 'aria-current="false"' not in html
    assert 'aria-valuetext="0:00"' in html
    assert '<track' not in html  # attaché côté client quand la piste le porte


def test_catalog_is_paginated_and_embeds_only_visible_chapters():
    items = [{
        "id": f"33333333-0000-4000-8000-{i:012d}",
        "title": f"Livre {i}", "display_name": f"Auteur - Livre {i}.mp3",
        "author": "Auteur", "duration_seconds": 60,
        "chapters": [{"title": f"Ch {i}", "start": 0}],
        "url": f"/m/livre-{i}",
    } for i in range(75)]
    collections = [{"id": "col-pag", "title": "Bibliothèque", "items": items}]
    principal = {"id": "reader", "display_name": "Lecteur", "csrf": "tok"}

    first = public_ui.catalog_page(principal, collections, page=1, page_size=60)
    second = public_ui.catalog_page(principal, collections, page=2, page_size=60)
    assert 'rel="next"' in first and 'rel="prev"' in second
    assert "Page 1" in first and "Page 2" in second
    # Only chapters of rendered items are embedded, not the whole catalogue.
    import json
    import re

    def chapters_in(html):
        match = re.search(r'id="chapters-data">(.*?)</script>', html, re.S)
        return json.loads(match.group(1)) if match else {}

    first_chapters = chapters_in(first)
    second_chapters = chapters_in(second)
    assert len(first_chapters) < 75  # no longer the whole 75-title catalogue
    assert len(second_chapters) < len(first_chapters)
    # Shelves (découvrir/nouveautés) still show a few global picks on page 2,
    # but the paginated browse list itself changed: fewer chapters embedded.
    assert len(second_chapters) < len(first_chapters)


def test_book_page_does_not_rebuild_the_full_catalog(monkeypatch):
    def forbidden():
        raise AssertionError("the book page rebuilt the whole catalogue")

    monkeypatch.setattr(main, "_public_catalog", forbidden)
    monkeypatch.setattr(main.repo, "get_published_collections_for_object", lambda oid: [
        {"id": "col-a11y", "title": "Un livre", "updated_at": 0},
    ])
    monkeypatch.setattr(main, "_library_items", lambda col, only_published=False: CATALOG[0]["items"])
    monkeypatch.setattr(main.repo, "get_object_unscoped", lambda oid: {
        "id": oid, "status": "available", "published_at": int(time.time()),
        "public_slug": "livre-a11y", "bucket": "aura", "object_key": f"aura/{oid}",
        "content_type": "audio/mpeg", "size_bytes": 1000,
        "display_name": "Auteur - Chapitre 1.mp3",
    })
    monkeypatch.setattr(main.repo, "get_audio_chapters_map", lambda ids: {})

    response = _page(f"/livre/{OID}")
    assert response.status_code == 200, response.text[:300]


def test_player_assets_use_accessible_patterns():
    player = (ASSETS / "player.js").read_text()
    bookmarks = (ASSETS / "bookmarks.js").read_text()
    assert "window.prompt" not in player
    assert "window.prompt" not in bookmarks
    assert "showModal()" in player and "showModal()" in bookmarks
    assert "aria-valuetext" in player
    assert "bar.setAttribute('role', 'dialog')" in player
    assert "'BUTTON','A'" in player  # Space n'active pas le bouton focalisé
    assert "createElement('track')" in player
    css = (ASSETS / "portal.css").read_text()
    assert ".skip-link:focus" in css
