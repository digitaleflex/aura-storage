"""Admin cover review endpoints: authentication, selection and bounded apply."""
import json
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")
os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-admin-covers.json")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import cover_enrichment as ce  # noqa: E402
from api import cover_review as cr  # noqa: E402
from api.auth import hash_password  # noqa: E402

GOOD_URL = "https://is1-ssl.mzstatic.com/image/thumb/cover.jpg/600x600bb.jpg"
BAD_URL = "https://example.test/cover.jpg"


def _account(role):
    username = f"cover-admin-{uuid.uuid4().hex[:10]}"
    password = "cover-admin-test-password"
    main.repo.create_user(username, hash_password(password), role=role)
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/login", json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def review_file(tmp_path, monkeypatch):
    path = tmp_path / "cover-candidates.json"
    path.write_text(json.dumps({
        "generated_at": 100,
        "books": [{
            "object_id": "book-1",
            "title": "Les Vertus de l'échec",
            "author": "Charles Pépin",
            "display_name": "Charles Pépin - Les vertus de l'échec.m4a",
            "status": "pending",
            "candidates": [
                {"provider": "itunes", "title": "Les Vertus de l'échec",
                 "author": "Charles Pépin", "url": GOOD_URL},
                {"provider": "other", "title": "Autre livre",
                 "author": "Alice", "url": BAD_URL},
            ],
        }, {
            "object_id": "book-2",
            "title": "Sans proposition",
            "status": "pending",
            "candidates": [],
        }],
    }), encoding="utf-8")
    monkeypatch.setenv("AURA_COVER_REVIEW_FILE", str(path))
    return path


def test_cover_candidates_require_admin_read_and_filter_unsafe_urls(review_file):
    assert TestClient(main.app).get("/api/v1/admin/cover-candidates").status_code == 401
    operator, _ = _account("operator")
    assert operator.get("/api/v1/admin/cover-candidates").status_code == 200
    admin, _ = _account("admin")
    data = admin.get("/api/v1/admin/cover-candidates").json()
    assert data["counts"] == {"books": 2, "with_candidates": 1, "candidates": 1}
    candidate = data["books"][0]["candidates"][0]
    assert candidate["match"] == "exact"
    assert candidate["url"] == GOOD_URL


def test_selection_requires_admin_write_csrf_and_a_listed_candidate(review_file):
    operator, csrf = _account("operator")
    body = {"object_id": "book-1", "candidate_url": GOOD_URL}
    assert operator.post("/api/v1/admin/covers/select", json=body).status_code == 403
    admin, admin_csrf = _account("admin")
    assert admin.post("/api/v1/admin/covers/select", json=body).status_code == 403
    bad = {"object_id": "book-1", "candidate_url": BAD_URL}
    r = admin.post("/api/v1/admin/covers/select", json=bad, headers=admin_csrf)
    assert r.status_code == 400
    r = admin.post("/api/v1/admin/covers/select", json=body, headers=admin_csrf)
    assert r.status_code == 200, r.text
    assert r.json()["book"]["status"] == "selected"
    saved = json.loads(review_file.read_text(encoding="utf-8"))
    assert saved["books"][0]["chosen_url"] == GOOD_URL
    assert isinstance(saved["selection_updated_at"], int)


def test_apply_dry_run_publishes_nothing_and_requires_confirm(monkeypatch, review_file):
    monkeypatch.setattr(ce, "find_object", lambda _oid: {"id": "book-1", "cover_key": None})
    admin, csrf = _account("admin")
    admin.post("/api/v1/admin/covers/select",
               json={"object_id": "book-1", "candidate_url": GOOD_URL}, headers=csrf)
    r = admin.post("/api/v1/admin/covers/apply",
                   json={"dry_run": True, "confirm": False}, headers=csrf)
    assert r.status_code == 400
    r = admin.post("/api/v1/admin/covers/apply",
                   json={"dry_run": True, "confirm": True}, headers=csrf)
    assert r.status_code == 200
    assert r.json() == {"applied": 1, "failed": 0, "skipped": 0, "dry_run": True}
    saved = json.loads(review_file.read_text(encoding="utf-8"))
    assert saved["books"][0]["status"] == "selected"
    assert "cover_key" not in saved["books"][0]


def test_apply_selected_cover_without_s3(monkeypatch, review_file):
    admin, csrf = _account("admin")
    admin.post("/api/v1/admin/covers/select",
               json={"object_id": "book-1", "candidate_url": GOOD_URL}, headers=csrf)
    monkeypatch.setattr(cr, "fetch_image", lambda _url: b"source")
    monkeypatch.setattr(ce, "resize_image", lambda _data: b"jpeg")
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(ce, "find_object", lambda _oid: {
        "id": "book-1", "bucket": "b", "object_key": "audio.mp3", "cover_key": None,
    })
    monkeypatch.setattr(ce, "publish_cover",
                        lambda obj, jpeg, client, apply: "audio.mp3.cover.jpg")
    r = admin.post("/api/v1/admin/covers/apply",
                   json={"dry_run": False, "confirm": True}, headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1
    saved = json.loads(review_file.read_text(encoding="utf-8"))
    assert saved["books"][0]["status"] == "applied"
    assert saved["books"][0]["cover_key"] == "audio.mp3.cover.jpg"


def test_google_books_candidate_carries_provenance(monkeypatch):
    payload = {"items": [{
        "id": "vol-1",
        "volumeInfo": {
            "title": "Les Vertus de l'échec", "authors": ["Charles Pépin"],
            "imageLinks": {"thumbnail": "http://books.google.com/books/content?id=vol-1"},
            "industryIdentifiers": [{"identifier": "9782213710000"}],
            "copyright": "Éditeur",
        },
    }]}
    monkeypatch.setattr(ce, "fetch_url", lambda *_args, **_kwargs: json.dumps(payload).encode())
    found = ce.search_google_books("Les Vertus de l'échec", "Charles Pépin",
                                   "9782213710000", 3)
    assert found[0]["provider"] == "google_books"
    assert found[0]["url"].startswith("https://books.google.com/")
    assert found[0]["size"] == "thumbnail"
    assert found[0]["isbn"] == "9782213710000"
    assert found[0]["license"] == "Éditeur"
    assert "vol-1" in found[0]["source_url"]


def test_search_endpoint_uses_isbn_and_records_provenance(monkeypatch, review_file):
    candidate = {
        "provider": "google_books", "title": "Les Vertus de l'échec",
        "author": "Charles Pépin", "url": GOOD_URL, "size": "large",
        "isbn": "9782213710000", "source_url": "https://books.google.com/books?id=1",
        "license": "Éditeur", "query": "isbn:9782213710000",
    }
    monkeypatch.setattr(ce, "search_google_books", lambda *_args: [candidate])
    monkeypatch.setattr(ce, "search_openlibrary", lambda *_args: [])
    monkeypatch.setattr(ce, "search_itunes", lambda *_args: [])
    admin, csrf = _account("admin")
    r = admin.post("/api/v1/admin/covers/search", json={
        "object_id": "book-1", "isbn": "9782213710000", "limit": 5,
    }, headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["book"]["candidates"][0]["size"] == "large"
    saved = json.loads(review_file.read_text(encoding="utf-8"))
    assert saved["books"][0]["search_isbn"] == "9782213710000"
    assert isinstance(saved["books"][0]["last_search_at"], int)


def test_search_endpoint_rejects_invalid_isbn(review_file):
    admin, csrf = _account("admin")
    r = admin.post("/api/v1/admin/covers/search", json={
        "object_id": "book-1", "isbn": "not-an-isbn",
    }, headers=csrf)
    assert r.status_code == 400


def test_applied_book_cannot_be_reselected(review_file):
    admin, csrf = _account("admin")
    saved = json.loads(review_file.read_text(encoding="utf-8"))
    saved["books"][0]["status"] = "applied"
    review_file.write_text(json.dumps(saved), encoding="utf-8")
    r = admin.post("/api/v1/admin/covers/select",
                   json={"object_id": "book-1", "candidate_url": GOOD_URL}, headers=csrf)
    assert r.status_code == 400
