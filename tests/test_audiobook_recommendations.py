"""Tests for audiobook listener preferences and recommendations.

These tests exercise the scoring/service logic with a fake repository so they
run without PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from audiobook import auth
from audiobook.errors import ValidationError
from audiobook.schemas import PreferencesIn, ProfileIn
from audiobook.services.recommendations import RecommendationsService


def _principal():
    return auth.Principal(
        listener={
            "id": uuid4(),
            "email": "listener@example.com",
            "display_name": "Listener",
            "status": "active",
            "locale": "fr",
            "timezone": "Europe/Paris",
            "territory_code": "WORLD",
        },
        session_id=uuid4(),
        csrf_hash="x",
        auth_source="cookie",
    )


class FakeRepo:
    def __init__(self):
        self.prefs = None
        self.candidates = []
        self.audit = []

    def get_listener_preferences(self, listener_id):
        if self.prefs is None:
            return {
                "listener_id": str(listener_id),
                "preferred_languages": [],
                "preferred_category_slugs": [],
                "preferred_authors": [],
                "preferred_narrators": [],
                "min_duration_ms": None,
                "max_duration_ms": None,
                "prefer_completed": False,
                "updated_at": None,
            }
        return self.prefs

    def upsert_listener_preferences(self, listener_id, prefs):
        self.prefs = {"listener_id": str(listener_id), **prefs, "updated_at": datetime.now(timezone.utc)}
        return self.prefs

    def list_recommendation_candidates(self, listener_id, *, limit=200):
        return self.candidates[:limit]

    def record_audit(self, **kwargs):
        self.audit.append(kwargs)


def _service(repo):
    settings = SimpleNamespace()
    storage = SimpleNamespace()
    return RecommendationsService(repo, settings, storage)


def _candidate(**overrides):
    base = {
        "edition_id": uuid4(),
        "work_id": uuid4(),
        "edition_title": "Titre",
        "work_title": "Titre",
        "edition_language": "fr",
        "work_language": "fr",
        "duration_ms": 3_600_000,
        "access_model": "free",
        "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "edition_description": "desc",
        "category_slugs": ["fiction"],
        "authors": ["Auteur A"],
        "narrators": ["Narrateur A"],
        "in_library": False,
        "is_favorite": False,
        "completed": False,
        "progress_ms": 0,
    }
    base.update(overrides)
    return base


def test_preferences_default_and_update():
    repo = FakeRepo()
    svc = _service(repo)
    principal = _principal()

    prefs = svc.get_preferences(principal)
    assert prefs["preferred_languages"] == []
    assert prefs["prefer_completed"] is False

    updated = svc.update_preferences(
        principal,
        preferred_languages=["fr", " en "],
        preferred_category_slugs=["Fiction", ""],
        preferred_authors=["Auteur A"],
        preferred_narrators=[],
        min_duration_ms=1000,
        max_duration_ms=5000,
        prefer_completed=True,
        request_id="r1",
    )
    assert updated["preferred_languages"] == ["fr", "en"]
    assert updated["preferred_category_slugs"] == ["fiction"]
    assert updated["min_duration_ms"] == 1000
    assert updated["prefer_completed"] is True
    assert repo.audit[-1]["action"] == "listener.preferences.updated"


def test_preferences_reject_invalid_duration_range():
    repo = FakeRepo()
    svc = _service(repo)
    principal = _principal()

    with pytest.raises(ValidationError) as exc:
        svc.update_preferences(
            principal,
            preferred_languages=[],
            preferred_category_slugs=[],
            preferred_authors=[],
            preferred_narrators=[],
            min_duration_ms=5000,
            max_duration_ms=1000,
            prefer_completed=False,
        )
    assert exc.value.code == "INVALID_PREFERENCE_RANGE"


def test_recommendations_rank_by_preferences():
    repo = FakeRepo()
    svc = _service(repo)
    principal = _principal()
    repo.prefs = {
        "listener_id": str(principal.listener_id),
        "preferred_languages": ["fr"],
        "preferred_category_slugs": ["histoire"],
        "preferred_authors": ["Auteur Préféré"],
        "preferred_narrators": ["Narrateur Préféré"],
        "min_duration_ms": 1_000_000,
        "max_duration_ms": 5_000_000,
        "prefer_completed": False,
        "updated_at": None,
    }
    match = _candidate(
        edition_title="Match",
        category_slugs=["histoire"],
        authors=["Auteur Préféré"],
        narrators=["Narrateur Préféré"],
        duration_ms=2_000_000,
        edition_language="fr",
    )
    other = _candidate(
        edition_title="Other",
        category_slugs=["fiction"],
        authors=["Autre"],
        narrators=["Autre"],
        duration_ms=10_000_000,
        edition_language="en",
    )
    repo.candidates = [other, match]

    result = svc.recommend(principal, limit=10)
    assert result["items"][0]["title"] == "Match"
    assert result["items"][0]["score"] > result["items"][1]["score"]
    assert "preferred_language" in result["items"][0]["reasons"]
    assert "preferred_category" in result["items"][0]["reasons"]


def test_recommendations_exclude_library_and_completed_by_default():
    repo = FakeRepo()
    svc = _service(repo)
    principal = _principal()
    repo.candidates = [
        _candidate(edition_title="InLibrary", in_library=True),
        _candidate(edition_title="Completed", completed=True),
        _candidate(edition_title="Visible"),
    ]

    result = svc.recommend(principal, limit=10)
    titles = [item["title"] for item in result["items"]]
    assert titles == ["Visible"]


def test_preferences_schema_validation():
    model = PreferencesIn(
        preferred_languages=["fr"],
        preferred_category_slugs=["fiction"],
        min_duration_ms=0,
        max_duration_ms=10,
    )
    assert model.preferred_languages == ["fr"]

    with pytest.raises(Exception):
        PreferencesIn(min_duration_ms=-1)


def test_profile_schema_accepts_new_fields():
    model = ProfileIn(
        display_name="Nom",
        first_name="Jean",
        last_name="Dupont",
        avatar_url="https://example.com/a.png",
        bio="Bio",
        marketing_opt_in=True,
    )
    assert model.first_name == "Jean"
    assert model.marketing_opt_in is True
