"""Operator-only bulk cover selection and publication helpers (no network/S3)."""
import os
import sys

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_API_BACKEND", "sqlite")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-cover-candidates.json")

from api import cover_enrichment as ce  # noqa: E402
from scripts import cover_candidates as cc  # noqa: E402


def _book(*, status="selected", url="https://is1-ssl.mzstatic.com/cover.jpg"):
    return {
        "object_id": "obj-1",
        "title": "Le Grand Livre",
        "author": "Alice",
        "status": status,
        "chosen_url": url,
        "candidates": [{
            "provider": "itunes",
            "title": "Le Grand Livre",
            "author": "Alice",
            "url": "https://is1-ssl.mzstatic.com/cover.jpg",
        }],
    }


def test_selected_candidate_rejects_unreviewed_or_unsafe_urls():
    assert cc.selected_candidate(_book())["provider"] == "itunes"
    assert cc.selected_candidate(_book(status="pending")) is None
    assert cc.selected_candidate(_book(url="https://example.test/other.jpg")) is None
    assert cc.selected_candidate(_book(url="http://127.0.0.1/cover.jpg")) is None
    assert cc.selected_candidate(_book(url="https://[")) is None


def test_apply_selected_dry_run_never_downloads_or_writes(monkeypatch):
    review = {"books": [_book()]}
    monkeypatch.setattr(ce, "find_object", lambda _oid: {"id": "obj-1", "cover_key": None})

    def forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run must not download, publish or write")

    monkeypatch.setattr(ce, "s3_client", forbidden)
    monkeypatch.setattr(cc, "fetch_selected_cover", forbidden)
    monkeypatch.setattr(ce, "resize_image", forbidden)
    monkeypatch.setattr(ce, "publish_cover", forbidden)
    monkeypatch.setattr(cc, "write_review", forbidden)

    assert cc.apply_selected(review, apply=False) == (1, 0, 0)
    assert review["books"][0]["status"] == "selected"


def test_apply_selected_publishes_and_marks_review(monkeypatch):
    review = {"books": [_book()]}
    published = {}
    monkeypatch.setattr(ce, "find_object", lambda _oid: {"id": "obj-1", "cover_key": None})
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(cc, "fetch_selected_cover", lambda _url, **_kwargs: b"source-image")
    monkeypatch.setattr(ce, "resize_image", lambda _data: b"jpeg")
    monkeypatch.setattr(cc, "write_review", lambda _review: None)

    def publish(obj, jpeg, _client, apply):
        published.update(obj=obj, jpeg=jpeg, apply=apply)
        return "books/audio.mp3.cover.jpg"

    monkeypatch.setattr(ce, "publish_cover", publish)
    assert cc.apply_selected(review, apply=True) == (1, 0, 0)
    assert published["apply"] is True
    assert published["jpeg"] == b"jpeg"
    book = review["books"][0]
    assert book["status"] == "applied"
    assert book["chosen_provider"] == "itunes"
    assert book["cover_key"] == "books/audio.mp3.cover.jpg"
    assert isinstance(book["applied_at"], int)


def test_apply_selected_records_an_unreadable_image(monkeypatch):
    review = {"books": [_book()]}
    monkeypatch.setattr(ce, "find_object", lambda _oid: {"id": "obj-1", "cover_key": None})
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(cc, "fetch_selected_cover", lambda _url, **_kwargs: b"not-an-image")
    monkeypatch.setattr(ce, "resize_image", lambda _data: None)
    monkeypatch.setattr(cc, "write_review", lambda _review: None)

    assert cc.apply_selected(review, apply=True) == (0, 1, 0)
    assert review["books"][0]["status"] == "error"
    assert "illisible" in review["books"][0]["error"]


def test_apply_selected_continues_after_network_exception(monkeypatch):
    second = _book()
    second["object_id"] = "obj-2"
    second["title"] = "Le Deuxieme Livre"
    review = {"books": [_book(), second]}
    calls = 0

    def fetch(_url, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("network failed")
        return b"source-image"

    monkeypatch.setattr(ce, "find_object", lambda oid: {"id": oid, "cover_key": None})
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(cc, "fetch_selected_cover", fetch)
    monkeypatch.setattr(ce, "resize_image", lambda _data: b"jpeg")
    monkeypatch.setattr(ce, "publish_cover", lambda obj, _jpeg, _client, apply: obj["id"] + ".jpg")
    monkeypatch.setattr(cc, "write_review", lambda _review: None)

    assert cc.apply_selected(review, apply=True) == (1, 1, 0)
    assert review["books"][0]["status"] == "error"
    assert review["books"][1]["status"] == "applied"


def test_collect_candidates_preserves_history_outside_limit(monkeypatch):
    applied = {
        "object_id": "already-done", "status": "applied", "cover_key": "done.jpg",
        "candidates": [{"url": "https://is1-ssl.mzstatic.com/old.jpg"}],
    }
    current = _book(status="selected")
    current["error"] = "ancien avertissement"
    review = {"books": [applied, current]}
    monkeypatch.setattr(ce, "published_without_cover", lambda *_args, **_kwargs: [{
        "id": "obj-1", "display_name": "Alice - Le Grand Livre",
    }])
    monkeypatch.setattr(ce, "search_openlibrary", lambda *_args: [])

    assert cc.collect_candidates(review, 1, "openlibrary") == 1
    by_id = {book["object_id"]: book for book in review["books"]}
    assert set(by_id) == {"already-done", "obj-1"}
    assert by_id["already-done"] == applied
    assert by_id["obj-1"]["status"] == "selected"
    assert by_id["obj-1"]["error"] == "ancien avertissement"


def test_collect_candidates_keeps_the_reviewed_candidate_when_provider_is_empty(monkeypatch):
    current = _book(status="selected")
    review = {"books": [current]}
    monkeypatch.setattr(ce, "published_without_cover", lambda *_args, **_kwargs: [{
        "id": "obj-1", "display_name": "Alice - Le Grand Livre",
    }])
    monkeypatch.setattr(ce, "search_openlibrary", lambda *_args: [])

    cc.collect_candidates(review, 1, "openlibrary")
    book = review["books"][0]
    assert book["status"] == "selected"
    assert book["chosen_url"] == "https://is1-ssl.mzstatic.com/cover.jpg"
    assert book["candidates"] == current["candidates"]
    assert book["chosen_candidate"] == 0


def test_collect_candidates_keeps_candidate_for_retry_after_error(monkeypatch):
    current = _book(status="error")
    current["error"] = "publication impossible"
    review = {"books": [current]}
    monkeypatch.setattr(ce, "published_without_cover", lambda *_args, **_kwargs: [{
        "id": "obj-1", "display_name": "Alice - Le Grand Livre",
    }])
    monkeypatch.setattr(ce, "search_openlibrary", lambda *_args: [])

    cc.collect_candidates(review, 1, "openlibrary")
    book = review["books"][0]
    assert book["status"] == "error"
    assert book["chosen_url"] == "https://is1-ssl.mzstatic.com/cover.jpg"
    assert book["candidates"] == current["candidates"]
    assert book["chosen_candidate"] == 0


def test_fetch_selected_cover_rejects_disallowed_host_before_opening(monkeypatch):
    def forbidden():
        raise AssertionError("must not open a disallowed host")

    monkeypatch.setattr(cc, "build_opener", forbidden)
    assert cc.fetch_selected_cover("https://example.test/cover.jpg") is None


def test_redirect_handler_refuses_off_host_redirects():
    handler = cc._NoRedirect()
    assert handler.redirect_request(None, None, 302, "", {}, "http://127.0.0.1/") is None


@pytest.mark.parametrize("payload", [
    '{"books": [',
    '{"books": ["bad"]}',
    '{"books": [{"candidates": {}}]}',
    '{"books": [], "value": NaN}',
])
def test_read_review_strict_rejects_malformed_json(tmp_path, payload):
    path = tmp_path / "review.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        cc.read_review_file(path, strict=True)


def test_write_review_is_atomic_and_leaves_no_temp(monkeypatch, tmp_path):
    path = tmp_path / "review.json"
    monkeypatch.setenv("AURA_COVER_REVIEW_FILE", str(path))
    assert cc.write_review({"books": []}) == path
    assert cc.read_review_file(path) == {"books": []}
    assert list(tmp_path.iterdir()) == [path]


def test_apply_selected_main_persists_an_empty_batch(monkeypatch, tmp_path):
    source = tmp_path / "selection.json"
    output = tmp_path / "review.json"
    source.write_text('{"books": [{"object_id": "obj-1", "status": "pending"}]}',
                      encoding="utf-8")
    monkeypatch.setenv("AURA_COVER_REVIEW_FILE", str(output))
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(sys, "argv", [
        "cover_candidates.py", "--apply-selected", "--review-input", str(source),
    ])

    assert cc.main() == 0
    assert cc.read_review_file(output)["books"][0]["status"] == "pending"
