"""Conservative automatic cover selection (no network)."""
import os

os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-auto-select.json")

from api import cover_review as cr  # noqa: E402
from scripts import auto_select_covers as asc  # noqa: E402


def test_allowed_hosts_match_the_review_allowlist():
    assert set(asc.ALLOWED_HOSTS) == set(cr.ALLOWED_HOSTS)
    assert asc.allowed_cover_url("https://books.google.com/books/content?id=abc&img=1")
    assert asc.allowed_cover_url("https://lh3.googleusercontent.com/cover.jpg")
    assert asc.allowed_cover_url("https://is1-ssl.mzstatic.com/image/cover.jpg")
    assert not asc.allowed_cover_url("https://www.googleapis.com/books/v1/volumes")
    assert not asc.allowed_cover_url("http://books.google.com/cover.jpg")
    assert not asc.allowed_cover_url("https://example.test/cover.jpg")


def test_normalize_ignores_accents_and_subtitles():
    assert asc.normalize("L'art de la guerre : extrait") == asc.normalize("L'art de la guerre")
    assert asc.normalize("Les mystères (tome 1)") == asc.normalize("Les mysteres")


def test_unique_google_candidate_is_selected():
    url = "https://books.google.com/books/content?id=abc&img=1"
    book = {
        "title": "Le Grand Livre",
        "author": "Alice",
        "status": "pending",
        "candidates": [{
            "provider": "google_books", "title": "Le Grand Livre",
            "author": "Alice", "url": url,
        }],
    }
    pick, reason = asc.decide(book)
    assert reason == "exact_title_author"
    assert pick["url"] == url


def test_conflicting_authors_prevent_auto_selection():
    book = {
        "title": "Le Grand Livre",
        "author": "Alice",
        "status": "pending",
        "candidates": [
            {"provider": "itunes", "title": "Le Grand Livre", "author": "Alice",
             "url": "https://is1-ssl.mzstatic.com/cover.jpg"},
            {"provider": "google_books", "title": "Le Grand Livre", "author": "Bob",
             "url": "https://books.google.com/books/content?id=abc&img=1"},
        ],
    }
    pick, reason = asc.decide(book)
    assert pick is None
    assert reason == "conflicting_exact_title_authors"
