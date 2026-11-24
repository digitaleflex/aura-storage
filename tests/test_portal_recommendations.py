"""Phase 2 : le portail réutilise le scoring de recommandation de l'audiobook."""
import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from api import portal_recommendations  # noqa: E402
from audiobook.services.recommendations import score_candidates  # noqa: E402


def _item(oid, *, author, favourite=False, progress=0, duration=600):
    return {
        "id": oid,
        "title": f"Livre {oid}",
        "display_name": f"{author} - Livre {oid}.mp3",
        "author": author,
        "duration_seconds": duration,
        "favorite": favourite,
        "progress_seconds": progress,
        "url": f"/m/livre-{oid}",
        "chapters": [],
    }


def test_shared_scoring_uses_preferences_and_exposes_reasons():
    prefs = {
        "preferred_languages": ["fr"],
        "preferred_category_slugs": [],
        "preferred_authors": ["Awa Diallo"],
        "preferred_narrators": [],
        "min_duration_ms": None,
        "max_duration_ms": None,
        "prefer_completed": False,
    }
    candidates = [
        {
            "edition_id": "one", "work_id": "one", "edition_title": "Un",
            "authors": ["Awa Diallo"], "edition_language": "fr",
            "duration_ms": 600_000, "published_at": None,
            "is_favorite": False, "progress_ms": 0,
        },
        {
            "edition_id": "two", "work_id": "two", "edition_title": "Deux",
            "authors": ["Autre"], "edition_language": "en",
            "duration_ms": 900_000, "published_at": None,
            "is_favorite": False, "progress_ms": 0,
        },
    ]
    result = score_candidates(prefs, candidates, limit=2)
    assert result["items"][0]["edition_id"] == "one"
    assert "preferred_author" in result["items"][0]["reasons"]
    assert "preferred_language" in result["items"][0]["reasons"]
    assert result["meta"]["has_explicit_preferences"] is True


def test_portal_shelf_is_ranked_and_explained_from_own_signals():
    items = [
        _item("11111111-1111-4111-8111-111111111111", author="Awa Diallo", favourite=True),
        _item("22222222-2222-4222-8222-222222222222", author="Awa Diallo"),
        _item("33333333-3333-4333-8333-333333333333", author="Autre"),
    ]
    ranked = portal_recommendations.rank(items)
    assert ranked
    assert all("reco_reasons" in item for item in ranked)
    # The favourite's author becomes an explicit preference, so other books by
    # the same author are explained with the same reason.
    explained = [i for i in ranked if "preferred_author" in i["reco_reasons"]]
    assert explained


def test_portal_falls_back_when_nothing_is_playable():
    items = [_item("44444444-4444-4444-8444-444444444444", author="Auteur")]
    items[0]["url"] = None
    assert portal_recommendations.rank(items) == []
