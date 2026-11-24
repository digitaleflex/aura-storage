"""Phase 3 du portail public : playlists, stats, récap et recherche naturelle."""
import os
import secrets
import time
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import portal_search  # noqa: E402
from api.auth import hash_password  # noqa: E402

OID = "55555555-6666-4777-8777-888888888888"
NEXT_OID = "66666666-7777-4888-8888-999999999999"


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    main.reset_login_attempts()
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    yield
    main.reset_login_attempts()


def _public_client():
    uid = main.repo.create_user(
        f"p3-{uuid.uuid4().hex[:8]}", hash_password("unused"), role="public"
    )
    csrf = secrets.token_hex(16)
    token = main.repo.create_session(uid, csrf, int(time.time()) + 3600)
    client = TestClient(main.app)
    client.cookies.set("aura_public_session", token)
    return client, {"X-CSRF-Token": csrf}, uid


def _published_book(name="Auteur - Livre.mp3"):
    placeholder = str(uuid.uuid4())
    oid = main.repo.create_pending_object(
        space_id=main.repo.default_scope()[1],
        application_id=main.repo.default_scope()[0],
        environment="test", bucket="aura", object_key=f"aura/{placeholder}",
        display_name=name, content_type="audio/mpeg", owner_id=None,
        actor_id="tester", actor_kind="user",
        intent_expires_at=int(time.time()) + 900,
    )
    main.repo.mark_available(oid, 1000, "checksum")
    main.repo.conn.execute(
        "UPDATE objects SET published_at = ?, public_slug = ?, duration_seconds = 600 "
        "WHERE id = ?", (int(time.time()), f"slug-{oid[:8]}", oid),
    )
    main.repo.conn.commit()
    return oid


def _seed_published_books():
    return _published_book(), _published_book("Autre auteur - Suite.mp3")


def test_private_playlist_crud_and_ownership():
    client, headers, _ = _public_client()
    oid, _ = _seed_published_books()

    created = client.post("/api/public/playlists", json={"name": "  Voyage  "}, headers=headers)
    assert created.status_code == 200, created.text
    pid = created.json()["playlist"]["id"]
    assert created.json()["playlist"]["name"] == "Voyage"

    listed = client.get("/api/public/playlists", headers=headers).json()
    assert any(p["id"] == pid for p in listed["playlists"])

    added = client.put(f"/api/public/playlists/{pid}/items/{oid}", headers=headers)
    assert added.status_code == 200 and added.json()["added"] is True
    items = client.get(f"/api/public/playlists/{pid}/items", headers=headers).json()
    assert items["items"][0]["object_id"] == oid

    renamed = client.patch(f"/api/public/playlists/{pid}", json={"name": "Train"}, headers=headers)
    assert renamed.status_code == 200
    removed = client.delete(f"/api/public/playlists/{pid}/items/{oid}", headers=headers)
    assert removed.status_code == 200

    other, other_headers, _ = _public_client()
    assert other.delete(f"/api/public/playlists/{pid}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/public/playlists/{pid}", headers=headers).status_code == 200


def test_profile_form_creates_playlist_and_shows_stats():
    client, headers, _ = _public_client()
    form = client.post(
        "/api/public/playlists/create", data={"name": "À relire"}, headers=headers,
        follow_redirects=False,
    )
    assert form.status_code == 303
    page = client.get("/profil", headers=headers)
    assert page.status_code == 200
    assert "Mes listes privées" in page.text
    assert "À relire" in page.text
    assert "Mon écoute" in page.text
    stats = client.get("/api/public/stats", headers=headers)
    assert stats.status_code == 200
    assert {"estimated_listened_seconds", "completed", "favorites", "bookmarks"} <= set(stats.json())


def test_natural_language_search_is_translated_into_filters():
    intent = portal_search.parse_search("un thriller de moins de 8 heures par Awa Diallo")
    assert intent.max_seconds == 8 * 3600
    assert intent.author == "Awa Diallo"
    assert intent.explanation
    assert "thriller" in intent.q

    narrow = portal_search.parse_search("entre 1h et 3h")
    assert narrow.min_seconds == 3600 and narrow.max_seconds == 3 * 3600

    plain = portal_search.parse_search("Nuit")
    assert plain.q == "Nuit" and not plain.recognised


def test_book_page_shows_spoiler_free_recap_and_series_position(monkeypatch):
    first = {"id": OID, "title": "Tome 1", "author": "Auteur", "chapters": []}
    second = {"id": NEXT_OID, "title": "Tome 2", "author": "Autre auteur", "chapters": []}
    monkeypatch.setattr(main, "_find_public_book", lambda oid: (
        first, {"title": "La Série", "description": "Une histoire sans révélation.", "items": [first, second]},
    ))
    monkeypatch.setattr(main.repo, "get_object_unscoped", lambda oid: {
        "id": oid, "status": "available", "published_at": int(time.time()),
        "public_slug": "serie", "bucket": "aura", "object_key": f"aura/{oid}",
        "content_type": "audio/mpeg", "size_bytes": 1000,
        "display_name": "Auteur - Tome 1.mp3",
    })
    monkeypatch.setattr(main.repo, "get_audio_chapters_map", lambda ids: {})

    response = TestClient(main.app).get(f"/livre/{OID}")
    assert response.status_code == 200, response.text[:300]
    assert "Avant de continuer" in response.text
    assert "Une histoire sans révélation." in response.text
    assert "Tome 1 sur 2" in response.text
