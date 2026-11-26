"""Public catalogue facets derived from approved object metadata.

Categories, themes and language use reserved object tags so the portal can be
opened without a schema migration. Other tags stay private and are never
projected into the public catalogue.
"""
from __future__ import annotations

from collections import Counter

FORMAT_LABELS = {
    "mp3": "MP3",
    "m4a": "M4A / MP4",
    "ogg": "OGG",
    "wav": "WAV",
    "flac": "FLAC",
    "aac": "AAC",
    "epub": "EPUB",
    "pdf": "PDF",
    "other": "Autre format",
}

LANGUAGE_LABELS = {
    "fr": "Français",
    "en": "Anglais",
    "es": "Espagnol",
    "de": "Allemand",
    "it": "Italien",
    "pt": "Portugais",
    "pt-br": "Portugais (Brésil)",
    "ar": "Arabe",
    "wo": "Wolof",
    "yo": "Yoruba",
}


def normalize_format(value: str | None, *, unknown: str = "other") -> str:
    raw = (value or "").split(";", 1)[0].strip().lower()
    aliases = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "audio/m4a": "m4a",
        "audio/ogg": "ogg",
        "application/ogg": "ogg",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/flac": "flac",
        "audio/x-flac": "flac",
        "audio/aac": "aac",
        "application/epub+zip": "epub",
        "application/pdf": "pdf",
    }
    return aliases.get(raw, raw if raw in FORMAT_LABELS else unknown)


def humanize(value: str) -> str:
    words = [part for part in value.replace("_", "-").split("-") if part]
    return " ".join(word[:1].upper() + word[1:] for word in words) or value


def split_public_tags(tags: list[str] | tuple[str, ...] | None) -> dict:
    categories: list[str] = []
    themes: list[str] = []
    languages: list[str] = []
    for raw in tags or []:
        tag = str(raw).strip().lower()
        if tag.startswith("categorie-") and len(tag) > len("categorie-"):
            categories.append(tag[len("categorie-"):])
        elif tag.startswith("theme-") and len(tag) > len("theme-"):
            themes.append(tag[len("theme-"):])
        elif tag.startswith("langue-") and len(tag) > len("langue-"):
            languages.append(tag[len("langue-"):])
    return {
        "categories": sorted(set(categories)),
        "themes": sorted(set(themes)),
        "languages": sorted(set(languages)),
    }


def item_facets(item: dict) -> dict:
    if all(key in item for key in ("categories", "themes", "languages", "format")):
        return {
            "categories": item["categories"],
            "themes": item["themes"],
            "languages": item["languages"],
            "language": item.get("language") or (item["languages"][0] if item["languages"] else ""),
            "format": item["format"],
        }
    derived = split_public_tags(item.get("public_tags") or item.get("tags"))
    return {
        "categories": item.get("categories") or derived["categories"],
        "themes": item.get("themes") or derived["themes"],
        "languages": item.get("languages") or derived["languages"],
        "language": item.get("language") or (derived["languages"][0] if derived["languages"] else ""),
        "format": item.get("format") or normalize_format(item.get("content_type")),
    }


def enrich_public_item(item: dict, tags: list[str] | None) -> dict:
    facets = split_public_tags(tags)
    return {
        **item,
        "public_tags": [
            tag for tag in (tags or [])
            if str(tag).startswith(("categorie-", "theme-", "langue-"))
        ],
        "categories": facets["categories"],
        "themes": facets["themes"],
        "languages": facets["languages"],
        "language": facets["languages"][0] if facets["languages"] else "",
        "format": normalize_format(item.get("content_type")),
    }


def unique_items(collections: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for collection in collections:
        for item in collection.get("items", []):
            by_id.setdefault(str(item.get("id")), item)
    return list(by_id.values())


def _options(counts: Counter, labels: dict[str, str] | None = None) -> list[dict]:
    return [
        {
            "value": value,
            "label": (labels or {}).get(value, humanize(value)),
            "count": count,
        }
        for value, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].lower()))
    ]


def catalog_facets(collections: list[dict]) -> dict:
    """Facet options and counts from the complete, unfiltered catalogue."""
    items = unique_items(collections)
    category_counts: Counter = Counter()
    theme_counts: Counter = Counter()
    language_counts: Counter = Counter()
    format_counts: Counter = Counter()
    for item in items:
        facets = item_facets(item)
        category_counts.update(facets["categories"])
        theme_counts.update(facets["themes"])
        language_counts.update(facets["languages"])
        format_counts.update([facets["format"] or "other"])

    collection_options = []
    for collection in collections:
        slug = str(collection.get("slug") or "")
        if not slug:
            continue
        ids = {str(item.get("id")) for item in collection.get("items", [])}
        if not ids:
            continue
        collection_options.append({
            "value": slug,
            "label": collection.get("title") or "Bibliothèque",
            "count": len(ids),
        })
    collection_options.sort(key=lambda option: (-option["count"], option["label"].lower()))

    return {
        "collections": collection_options,
        "categories": _options(category_counts),
        "themes": _options(theme_counts),
        "languages": _options(language_counts, LANGUAGE_LABELS),
        "formats": _options(format_counts, FORMAT_LABELS),
    }


def minutes_to_seconds(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError("duration") from exc
    if minutes < 0:
        raise ValueError("duration")
    return minutes * 60
