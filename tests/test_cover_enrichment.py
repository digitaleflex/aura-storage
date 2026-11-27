"""Pure helpers used by the cover enrichment scripts (no network, no ffmpeg)."""
import json
import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_API_BACKEND", "sqlite")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-cover-candidates.json")

from api import cover_enrichment as ce  # noqa: E402


def test_sibling_candidates_prefers_the_same_stem():
    obj = {"bucket": "b", "object_key": "Auteur - Titre/Auteur - Titre.mp3"}
    images = [
        {"object_key": "Auteur - Titre/cover.jpg", "size_bytes": 90},
        {"object_key": "Auteur - Titre/Auteur - Titre.png", "size_bytes": 40},
        {"object_key": "Auteur - Titre/chapter.jpg", "size_bytes": 500},
        {"object_key": "autre/folder.jpg", "size_bytes": 900},
    ]
    got = ce.sibling_candidates(obj, images)
    # Une image sans lien avec le livre n'est pas proposée (pas de faux positif).
    assert [row["object_key"] for row in got] == [
        "Auteur - Titre/Auteur - Titre.png",
        "Auteur - Titre/cover.jpg",
    ]


def _fake_payload(monkeypatch, payload):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return json.dumps(payload).encode()

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return Response()

    monkeypatch.setattr(ce, "urlopen", fake_urlopen)
    return seen


def test_itunes_candidates_are_upscaled(monkeypatch):
    seen = _fake_payload(monkeypatch, {"results": [{
        "collectionName": "Le Grand Livre", "artistName": "Alice",
        "artworkUrl100": "https://example.test/cover/100x100bb.jpg",
    }]})
    out = ce.search_itunes("Le Grand Livre", "Alice", 2)
    assert out == [{
        "provider": "itunes", "title": "Le Grand Livre", "author": "Alice",
        "url": "https://example.test/cover/600x600bb.jpg",
        "size": "600", "source_url": "",
    }]
    assert "term=Alice+Le+Grand+Livre" in seen["url"]
    assert "entity=audiobook" in seen["url"]


def test_openlibrary_candidates_use_the_cover_id(monkeypatch):
    seen = _fake_payload(monkeypatch, {"docs": [{
        "title": "Le Grand Livre", "author_name": ["Alice"], "cover_i": 12345,
    }]})
    out = ce.search_openlibrary("Le Grand Livre", "Alice", 1)
    assert out[0]["url"] == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert "title=Le+Grand+Livre" in seen["url"]
