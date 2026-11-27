from urllib.parse import urlencode

from api import public_book, public_classification, public_facets, public_series, public_ui


def test_classification_uses_private_folder_only_as_a_proposal_source():
    cyber = public_classification.classify_public_item(
        "Cybercriminalité et IA : rançongiciel furtif.m4a", "Podcast_cyber_substack",
    )
    assert cyber["category"] == "cybersecurite"
    assert "intelligence-artificielle" in cyber["themes"]
    assert "cybersecurite" in cyber["themes"]
    assert "Podcast_cyber_substack" not in public_classification.classification_tags(cyber)

    meditation = public_classification.classify_public_item(
        "001_Les_Meditations_Guidees_Respirez.mp3",
        "AudioBook - Méditations guidées Respirez - @Ebooks_fr",
    )
    assert meditation["category"] == "meditation"
    assert "meditation" in meditation["themes"]


def test_classification_falls_back_to_development_and_keeps_tags_valid():
    unknown = public_classification.classify_public_item("Documentaire inédit.mp3", "Dossier privé")
    assert unknown["category"] == "developpement"
    tags = public_classification.classification_tags(unknown)
    assert tags == [
        "categorie-developpement", "theme-motivation", "theme-bien-etre", "langue-fr",
    ]
    assert all(len(tag) <= 32 and public_classification.TAG_RE.fullmatch(tag) for tag in tags)


def test_merge_preserves_private_and_manual_public_tags_unless_replacing():
    proposal = public_classification.classify_public_item("Un livre", "Robert Kiyosaki")
    existing = ["interne", "categorie-roman", "theme-histoire", "langue-en"]
    assert public_classification.merge_public_tags(existing, proposal) == existing

    replaced = public_classification.merge_public_tags(existing, proposal, replace=True)
    assert "interne" in replaced
    assert "categorie-finance" in replaced
    assert "categorie-roman" not in replaced
    assert "theme-histoire" not in replaced
    assert "langue-en" not in replaced
    assert len(replaced) <= 20


def test_editorial_labels_are_used_for_categories_and_themes():
    assert public_facets.facet_label("category", "developpement") == "Développement personnel"
    assert public_facets.facet_label("theme", "intelligence-artificielle") == "Intelligence artificielle"
    assert public_facets.facet_label("category", "roman") == "Roman"


def test_category_navigation_has_icons_counts_and_preserves_other_filters():
    calls = []

    def href(**changes):
        calls.append(changes)
        return "/?" + urlencode({"q": "argent", "auteur": "Alice", **changes})

    html = public_ui.category_theme_nav(
        facet_options={
            "categories": [{"value": "finance", "label": "Finance", "count": 12}],
            "themes": [{"value": "argent", "label": "Argent", "count": 8}],
        },
        active_facets={"category": "finance"},
        href=href,
    )
    assert 'aria-label="Catégories"' in html
    assert 'aria-label="Thèmes"' in html
    assert 'class="facet-icon"' in html
    assert "<svg" in html and "Finance &amp; entrepreneuriat" in html
    assert "<small>12</small>" in html
    assert 'aria-pressed="true"' in html
    assert {"categorie": "finance", "page": None} in calls
    assert "q=argent" in html and "auteur=Alice" in html


def test_series_are_curated_from_folders_and_grouped_from_published_items():
    assert public_series.series_for_folder("Podcast_cyber_substack") == "Cyber substack"
    assert public_series.series_for_folder("Dossier prive") == ""
    items = [
        {"id": str(i), "title": f"Livre {i}", "series": "Robert Greene", "cover_url": None}
        for i in range(3)
    ] + [{"id": "other", "title": "Autre", "series": "", "cover_url": None}]
    shelves = public_series.group_series(items)
    assert len(shelves) == 1
    assert shelves[0]["label"] == "Robert Greene"
    assert len(shelves[0]["items"]) == 3
    duplicate = {"id": "dup", "title": "Livre 0", "series": "Robert Greene"}
    deduped = public_series.group_series(items + [duplicate])
    assert len(deduped[0]["items"]) == 3


def test_categories_group_published_items_with_real_labels():
    items = [
        {"id": str(i), "categories": ["finance"], "themes": [], "languages": [], "format": "mp3"}
        for i in range(4)
    ]
    shelves = public_series.group_categories(items)
    assert shelves[0]["label"] == "Finance & entrepreneuriat"
    assert len(shelves[0]["items"]) == 4


def test_standard_cards_use_typographic_jackets_only():
    item = {
        "id": "one", "title": "Le Grand Livre", "author": "Alice",
        "cover_url": "/covers/one.jpg",
    }
    assert "<img" not in public_ui._track_html(item)
    assert "<img" not in public_ui.hero_cover_html(item)
    assert "<img" not in public_book._cover(item)
    assert "cover-fallback" in public_ui._track_html(item)


def test_carousels_show_real_covers_only_for_curated_series():
    shelf = {
        "slug": "robert-greene", "label": "Robert Greene",
        "items": [{
            "id": "one", "title": "Stratégie", "author": "Robert Greene",
            "cover_url": "/covers/one.jpg", "series": "Robert Greene",
            "categories": ["leadership"], "themes": [], "languages": [],
            "format": "mp3",
        }],
    }
    uniform = public_ui.carousel_shelf(shelf)
    series = public_ui.carousel_shelf(shelf, use_covers=True)
    for html in (uniform, series):
        assert 'class="carousel-track"' in html
        assert 'data-carousel="carousel-robert-greene"' in html
        assert 'href="/livre/one"' in html
        assert 'aria-label="Faire défiler Robert Greene vers la droite"' in html
    assert "<img" not in uniform
    # A cover key alone is not enough: real art needs the editorial flag.
    assert "<img" not in series
    curated = dict(shelf)
    curated["items"] = [dict(shelf["items"][0], emblematic_cover=True)]
    assert "/covers/one.jpg" in public_ui.carousel_shelf(curated, use_covers=True)


def test_anonymous_landing_renders_the_shared_category_navigation():
    item = {
        "id": "one", "display_name": "Alice - Finance.mp3", "title": "Finance",
        "author": "Alice", "duration_seconds": 600, "cover_url": None,
        "categories": ["finance"], "themes": ["argent"], "languages": ["fr"],
        "format": "mp3",
    }
    html = public_book.landing_page(
        [{"slug": "all", "title": "Tous", "items": [item]}],
        query="argent", active_author="Alice",
        facet_options=public_facets.catalog_facets([{"slug": "all", "items": [item]}]),
        active_facets={"category": "finance"},
    )
    assert 'aria-label="Catégories"' in html
    assert 'class="facet-icon"' in html
    assert "Finance &amp; entrepreneuriat" in html
    assert "categorie=finance" in html and "q=argent" in html and "auteur=Alice" in html
    assert 'class="carousel-shelf"' in html and 'class="carousel-track"' in html
    assert "carousel.js" in html
