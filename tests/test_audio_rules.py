import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "test")
os.environ.setdefault("AURA_S3_SECRET_KEY", "test")
os.environ.setdefault("AURA_S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("AURA_S3_BUCKET", "test")
os.environ.setdefault("AURA_SPACE_ID", "00000000-0000-0000-0000-000000000001")

from api.audio_ai import classify_with_rules


def test_meditation_keyword():
    r = classify_with_rules(
        metadata={"display_name": "Méditation guidée respiration.mp3"},
        quality={"ok": True, "duration_s": 900, "tags": {}, "technical_score": 80},
    )
    assert r["suggested_category"] == "meditation"
    assert r["confidence"] >= 0.60
    assert "rules" == r["provider"]


def test_podcast_keyword():
    r = classify_with_rules(
        metadata={"display_name": "Podcast interview épisode 12.mp3"},
        quality={"ok": True, "duration_s": 2400, "tags": {}, "technical_score": 80},
    )
    assert r["suggested_category"] == "podcast"
    assert r["confidence"] >= 0.60


def test_genre_tag_weighted():
    r = classify_with_rules(
        metadata={"display_name": "session 01.mp3"},
        quality={"ok": True, "duration_s": 1200, "tags": {"genre": "Meditation"}, "technical_score": 80},
    )
    assert r["suggested_category"] == "meditation"
    assert "genre:" in r["reason"]


def test_unknown_low_confidence():
    r = classify_with_rules(
        metadata={"display_name": "audio_001.mp3"},
        quality={"ok": True, "duration_s": 120, "tags": {}, "technical_score": 70},
    )
    assert r["suggested_category"] == "autre"
    assert r["confidence"] < 0.60
