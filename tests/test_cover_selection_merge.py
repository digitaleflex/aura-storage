"""Safe merge of operator exports into the canonical cover review."""
import json

import pytest

from scripts.merge_cover_selections import load_review, merge_selections


def _candidate(url="https://is1-ssl.mzstatic.com/cover.jpg"):
    return {"provider": "itunes", "title": "Livre", "url": url}


def test_merge_preserves_canonical_books_and_applied_states():
    canonical = {"books": [
        {"object_id": "done", "status": "applied", "cover_key": "done.jpg",
         "candidates": [_candidate()]},
        {"object_id": "new", "status": "pending", "candidates": [_candidate()]},
    ]}
    selections = {"exported_at": 200, "books": [
        {"object_id": "done", "status": "pending", "chosen_url": None},
        {"object_id": "new", "status": "selected",
         "chosen_url": "https://is1-ssl.mzstatic.com/cover.jpg"},
        {"object_id": "removed", "status": "selected", "chosen_url": "https://example.test"},
    ]}
    merged = merge_selections(canonical, selections)
    by_id = {book["object_id"]: book for book in merged["books"]}
    assert set(by_id) == {"done", "new"}
    assert by_id["done"]["status"] == "applied"
    assert by_id["done"]["cover_key"] == "done.jpg"
    assert by_id["new"]["status"] == "selected"
    assert by_id["new"]["chosen_candidate"] == 0


def test_merge_rejects_export_older_than_candidate_refresh():
    with pytest.raises(ValueError, match="generated_at"):
        merge_selections(
            {"generated_at": 200, "books": []},
            {"exported_at": 100, "books": []},
        )


def test_merge_rejects_page_rendered_before_a_newer_selection():
    with pytest.raises(ValueError, match="page de revue plus ancienne"):
        merge_selections(
            {"generated_at": 100, "selection_updated_at": 200, "books": []},
            {"generated_at": 100, "selection_updated_at": 150,
             "exported_at": 300, "books": []},
        )


def test_merge_rejects_candidate_removed_by_refresh():
    with pytest.raises(ValueError, match="perimee"):
        merge_selections(
            {"books": [{"object_id": "new", "status": "pending", "candidates": []}]},
            {"exported_at": 200, "books": [{
                "object_id": "new", "status": "selected",
                "chosen_url": "https://is1-ssl.mzstatic.com/old.jpg",
            }]},
        )


def test_newer_export_can_clear_a_selection():
    canonical = {"selection_updated_at": 100, "last_selection_export_at": 100, "books": [{
        "object_id": "new", "status": "selected", "chosen_url": "https://is1-ssl.mzstatic.com/a.jpg",
        "chosen_candidate": 0, "candidates": [_candidate("https://is1-ssl.mzstatic.com/a.jpg")],
    }]}
    merged = merge_selections(canonical, {
        "selection_updated_at": 100,
        "exported_at": 200,
        "books": [{"object_id": "new", "status": "pending", "chosen_url": None}],
    })
    assert merged["books"][0]["status"] == "pending"
    assert merged["books"][0]["chosen_url"] is None


def test_same_export_can_retry_after_partial_failure():
    canonical = {
        "selection_updated_at": 200, "last_selection_export_at": 150,
        "books": [{"object_id": "new", "status": "error", "candidates": [_candidate()]}],
    }
    merged = merge_selections(canonical, {
        "exported_at": 150,
        "books": [{"object_id": "new", "status": "selected",
                   "chosen_url": "https://is1-ssl.mzstatic.com/cover.jpg"}],
    })
    assert merged["books"][0]["status"] == "selected"


def test_load_review_rejects_non_finite_json(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"books": [], "value": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="NaN"):
        load_review(path)


def test_merge_output_is_json_serializable_without_nan():
    merged = merge_selections({"books": []}, {"exported_at": 1, "books": []})
    json.dumps(merged, allow_nan=False)
