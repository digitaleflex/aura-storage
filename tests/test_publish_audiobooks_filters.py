"""Pure safety filters for incremental audiobook publication."""
import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_API_BACKEND", "sqlite")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from scripts import publish_audiobooks as publish  # noqa: E402


def test_incremental_filter_excludes_published_objects_and_published_titles():
    rows = [
        {"id": "published", "display_name": "Déjà publié", "published_at": 1, "status": "available"},
        {"id": "same-title", "display_name": "Déjà publié", "published_at": None, "status": "available"},
        {"id": "new", "display_name": "Nouveau", "published_at": None, "status": "available"},
    ]
    kept, excluded = publish.filter_publication_rows(
        rows, only_unpublished=True, dedupe_display_name=True,
    )
    assert [row["id"] for row in kept] == ["new"]
    assert excluded == {"already_published": 1, "published_title": 1, "duplicate": 0}


def test_dedupe_prefers_available_copy_over_newer_pending_duplicate():
    rows = [
        {"id": "pending", "display_name": "Livre", "published_at": None, "status": "pending"},
        {"id": "available", "display_name": "Livre", "published_at": None, "status": "available"},
        {"id": "older", "display_name": "Livre", "published_at": None, "status": "available"},
    ]
    kept, excluded = publish.filter_publication_rows(
        rows, only_unpublished=True, dedupe_display_name=True,
    )
    assert [row["id"] for row in kept] == ["available"]
    assert excluded["duplicate"] == 2
