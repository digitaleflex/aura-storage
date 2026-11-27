"""Locally generated AURA jackets (no network, no ffmpeg)."""
import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_API_BACKEND", "sqlite")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-cover-jacket.json")

from api import cover_enrichment as ce  # noqa: E402
from api import cover_jacket  # noqa: E402
from api import cover_review as cr  # noqa: E402
from api import public_ui  # noqa: E402


def test_palette_stays_in_sync_with_the_portal():
    assert cover_jacket.COVER_HUES == public_ui.COVER_HUES
    assert cover_jacket.cover_hue("Le Grand Livre") == public_ui.cover_hue("Le Grand Livre")


def test_jacket_is_a_deterministic_jpeg():
    first = cover_jacket.render_jacket("Les mystères de la forêt", "Alice Écrivain")
    assert first.startswith(b"\xff\xd8")
    assert len(first) > 1024
    assert first == cover_jacket.render_jacket("Les mystères de la forêt", "Alice Écrivain")
    assert first != cover_jacket.render_jacket("Un autre livre", "Alice Écrivain")


def test_long_title_is_wrapped_without_an_error():
    jpeg = cover_jacket.render_jacket(
        "Une histoire très très longue avec des mots qui ne finissent jamais "
        "et encore davantage de texte pour dépasser la jaquette",
        "Un auteur au nom tout aussi interminable",
    )
    assert jpeg.startswith(b"\xff\xd8")


def test_render_jacket_splits_the_display_name():
    seen = {}

    def fake_render(title, author, **_kwargs):
        seen["title"], seen["author"] = title, author
        return b"\xff\xd8" + b"0" * 2000

    original = cover_jacket.render_jacket
    try:
        cover_jacket.render_jacket = fake_render
        jpeg = ce.render_jacket({
            "display_name": "Alice Écrivain - Les mystères de la forêt.mp3",
            "title": "autre chose",
        })
    finally:
        cover_jacket.render_jacket = original
    assert jpeg is not None
    assert seen == {"title": "Les mystères de la forêt", "author": "Alice Écrivain"}


def test_generated_cover_uses_a_replaceable_key(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)

    class Repo:
        def __init__(self):
            self.calls = []

        def set_object_cover(self, oid, key):
            self.calls.append(("cover", oid, key))

        def mark_media_probe(self, oid, kind, timestamp):
            self.calls.append(("probe", oid, kind, timestamp))

    monkeypatch.setattr(ce, "repo", Repo())
    client = Client()
    obj = {"id": "object-1", "bucket": "bucket", "object_key": "auteur - livre.mp3"}
    key = ce.publish_cover(obj, b"\xff\xd8" + b"0" * 2000, client, True, generated=True)
    assert key == "auteur - livre.mp3.jacket.jpg"
    assert ce.is_generated_cover(key)
    assert not ce.is_generated_cover("auteur - livre.mp3.cover.jpg")
    assert client.calls[0]["Key"] == key
    assert client.calls[0]["ContentType"] == "image/jpeg"
    assert ce.repo.calls[0] == ("cover", "object-1", key)
    assert ce.repo.calls[1][:3] == ("probe", "object-1", "cover")


def _review(cover_key):
    url = "https://is1-ssl.mzstatic.com/image/thumb/cover.jpg"
    return {
        "generated_at": 1,
        "books": [{
            "object_id": "object-1",
            "title": "Le Grand Livre",
            "status": "selected",
            "chosen_url": url,
            "candidates": [{"url": url, "provider": "itunes"}],
        }],
    }, cover_key


def test_selected_cover_replaces_a_generated_jacket(monkeypatch):
    review, cover_key = _review("auteur - livre.mp3.jacket.jpg")
    monkeypatch.setattr(ce, "find_object", lambda _oid: {
        "id": "object-1", "bucket": "bucket", "object_key": "auteur - livre.mp3",
        "cover_key": cover_key,
    })
    monkeypatch.setattr(ce, "resize_image", lambda _data: b"jpeg")
    monkeypatch.setattr(ce, "s3_client", lambda: object())
    monkeypatch.setattr(ce, "publish_cover", lambda *_a, **_k: "auteur - livre.mp3.cover.jpg")
    monkeypatch.setattr(cr, "fetch_image", lambda _url: b"image")
    monkeypatch.setattr(cr, "write_review", lambda _review: None)

    result = cr.apply_selected(review, dry_run=False)
    assert result == {"applied": 1, "failed": 0, "skipped": 0, "dry_run": False}
    assert review["books"][0]["status"] == "applied"
    assert review["books"][0]["cover_key"] == "auteur - livre.mp3.cover.jpg"


def test_selected_cover_never_replaces_a_real_cover(monkeypatch):
    review, cover_key = _review("auteur - livre.mp3.cover.jpg")
    monkeypatch.setattr(ce, "find_object", lambda _oid: {
        "id": "object-1", "bucket": "bucket", "object_key": "auteur - livre.mp3",
        "cover_key": cover_key,
    })
    monkeypatch.setattr(cr, "write_review", lambda _review: None)

    result = cr.apply_selected(review, dry_run=False)
    assert result["skipped"] == 1
    assert result["applied"] == 0
    assert review["books"][0]["status"] == "already_applied"
