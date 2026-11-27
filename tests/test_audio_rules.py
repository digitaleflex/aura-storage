"""Deterministic audio classification rules (no external provider)."""
import json
import os
from pathlib import Path

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")

from api import audio_ai  # noqa: E402


def test_rules_file_is_valid_and_extends_the_default_categories():
    rules = json.loads(
        (Path(audio_ai.__file__).parent / "audio_rules.json").read_text(encoding="utf-8")
    )
    categories = {item["category"] for item in rules["categories"]}
    assert {"meditation", "sante_bien_etre", "histoire_societe"} <= categories
    assert all(item["keywords"] for item in rules["categories"])


def test_rules_classify_from_filename_and_genre_without_ai():
    result = audio_ai.classify_with_rules(
        metadata={"display_name": "Respirez - Méditation guidée.m4a", "folder_name": "Audiobooks"},
        quality={
            "tags": {"genre": "meditation", "title": "Méditation guidée"},
            "duration_s": 1200,
        },
    )
    assert result["provider"] == "rules"
    assert result["suggested_category"] == "meditation"
    assert result["confidence"] >= 0.8
    assert "meditation" in result["reason"]


def test_rules_fall_back_to_autre_when_no_keyword_matches():
    result = audio_ai.classify_with_rules(
        metadata={"display_name": "Sans titre.bin"},
        quality={"tags": {}, "duration_s": 600},
    )
    assert result["suggested_category"] == "autre"
    assert result["confidence"] < 0.5
