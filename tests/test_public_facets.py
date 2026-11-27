from api import public_facets


def test_only_reserved_tags_become_public_facets():
    facets = public_facets.split_public_tags([
        "categorie-roman", "theme-histoire", "langue-fr", "interne", "CATEGORIE-POESIE",
    ])
    assert facets == {
        "categories": ["poesie", "roman"],
        "themes": ["histoire"],
        "languages": ["fr"],
    }


def test_format_aliases_are_normalized_without_guessing_codecs():
    assert public_facets.normalize_format("audio/mpeg") == "mp3"
    assert public_facets.normalize_format("audio/mpeg; charset=binary") == "mp3"
    assert public_facets.normalize_format("audio/x-m4a") == "m4a"
    assert public_facets.normalize_format("audio/mp4") == "m4a"
    assert public_facets.normalize_format("application/epub+zip") == "epub"
    assert public_facets.normalize_format("application/x-unknown") == "other"


def test_facet_counts_use_unique_books_and_keep_source_collections():
    item = {
        "id": "one", "title": "Un", "content_type": "audio/mpeg",
        "categories": ["roman"], "themes": ["histoire"], "languages": ["fr"],
    }
    collections = [
        {"slug": "classiques", "title": "Classiques", "items": [item]},
        {"slug": "selection", "title": "Sélection", "items": [item]},
    ]
    options = public_facets.catalog_facets(collections)
    assert options["categories"] == [{"value": "roman", "label": "Roman", "count": 1}]
    assert options["formats"] == [{"value": "mp3", "label": "MP3", "count": 1}]
    assert [entry["value"] for entry in options["collections"]] == ["classiques", "selection"]


def test_duration_minutes_are_strict_and_bounded_to_whole_minutes():
    assert public_facets.minutes_to_seconds("") is None
    assert public_facets.minutes_to_seconds("90") == 5400
    for value in ("-1", "1.5", "abc"):
        try:
            public_facets.minutes_to_seconds(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{value!r} should be refused")
