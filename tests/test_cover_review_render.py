"""Rendering helpers for the operator cover-review page."""
from scripts.render_cover_review import allowed_cover_url, match_class, normalize, render


def test_match_class_ignores_accents_case_and_subtitle():
    book = {"title": "Les Vertus de l'échec", "author": "Charles Pépin"}
    candidate = {"title": "LES VERTUS DE L'ECHEC : édition intégrale", "author": "Charles Pepin"}
    assert match_class(book, candidate) == "exact"
    assert normalize("L'art de la guerre (extrait)") == "l art de la guerre"


def test_allowed_cover_url_rejects_internal_or_insecure_sources():
    assert allowed_cover_url("https://is1-ssl.mzstatic.com/cover.jpg")
    assert allowed_cover_url("https://covers.openlibrary.org/b/id/1-L.jpg")
    assert not allowed_cover_url("http://is1-ssl.mzstatic.com/cover.jpg")
    assert not allowed_cover_url("https://127.0.0.1/cover.jpg")
    assert not allowed_cover_url("https://example.test/cover.jpg")
    assert not allowed_cover_url("https://[")


def test_render_escapes_untrusted_metadata_and_keeps_selection_workflow():
    review = {"books": [{
        "object_id": "obj-1",
        "title": "</script><script>alert(1)</script>",
        "author": "Alice",
        "candidates": [{
            "provider": "itunes",
            "title": "Livre",
            "author": "Alice",
            "url": "https://is1-ssl.mzstatic.com/cover.jpg",
        }],
    }]}
    page = render(review)
    assert "</script><script>alert(1)</script>" not in page
    assert "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "Exporter les sélections" in page
    assert "--apply-selected" not in page  # the page itself never publishes
    assert "apply_cover_candidates.sh" in page


def test_render_does_not_load_unapproved_image_hosts():
    review = {"books": [{
        "object_id": "obj-1",
        "title": "Livre",
        "candidates": [{"provider": "other", "title": "Livre",
                        "url": "http://127.0.0.1/cover.jpg"}],
    }]}
    page = render(review)
    assert '<img src="http://127.0.0.1/cover.jpg"' not in page
    assert page.count("<img") == 0
    assert "Aucun candidat automatique" in page
