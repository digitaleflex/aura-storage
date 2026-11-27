"""Public series groupings for the audiobook portal.

Folders are an internal storage concern.  Only the curated names below become
public series; everything else stays private.  Grouping is done from the
published catalogue, so no schema change is needed.
"""
from __future__ import annotations

import unicodedata

from . import public_facets

SERIES_BY_FOLDER = {
    "brian tracy": "Brian Tracy",
    "brian tracy - capsules": "Brian Tracy — Capsules",
    "robert greene": "Robert Greene",
    "robert kiyosaki": "Robert Kiyosaki",
    "louise hay": "Louise Hay",
    "napoleon hill": "Napoleon Hill",
    "wayne dyer": "Wayne Dyer",
    "podcast cyber substack": "Cyber substack",
    "audiobook - meditations guidees respirez - @ebooks fr": "Méditations guidées Respirez",
    "s'aimer, c'est donner un sens": "S'aimer, c'est donner un sens",
    "serie inconnue (chapitres 2 a 6)": "Motivation — série de chapitres",
    "dale carnegie": "Dale Carnegie",
    "stephen covey": "Stephen Covey",
    "capsules diverses": "Capsules diverses",
    "dan millman": "Dan Millman",
    "joseph murphy": "Joseph Murphy",
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.lower().replace("_", " ").split())


def series_for_folder(folder_name: str) -> str:
    return SERIES_BY_FOLDER.get(_fold(folder_name), "")


def series_slug(label: str) -> str:
    value = "".join(
        char if char.isalnum() else "-" for char in _fold(label)
    ).strip("-")
    return value or "serie"


def _shelf(slug: str, label: str, items: list[dict]) -> dict:
    return {"slug": slug, "label": label, "items": items[:16]}


def _unique_items(items: list[dict]) -> list[dict]:
    """Keep the first copy of a title; duplicate uploads must not crowd a shelf."""
    seen = set()
    unique = []
    for item in items:
        key = " ".join(str(
            item.get("title") or item.get("display_name") or ""
        ).strip().lower().split())
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(item)
    return unique


def group_series(items: list[dict], *, min_items: int = 3, limit: int = 8) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    for item in items:
        label = str(item.get("series") or "")
        if not label:
            continue
        slug = series_slug(label)
        grouped.setdefault(slug, []).append(item)
        labels.setdefault(slug, label)
    for slug in grouped:
        grouped[slug] = _unique_items(grouped[slug])
    shelves = [
        _shelf(slug, labels[slug], grouped[slug])
        for slug, grouped_items in sorted(
            grouped.items(), key=lambda pair: (-len(pair[1]), labels[pair[0]].lower())
        )
        if len(grouped_items) >= min_items
    ]
    return shelves[:limit]


def group_categories(
    items: list[dict], *, limit: int = 8, per_shelf: int = 12,
) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        for category in public_facets.item_facets(item)["categories"]:
            grouped.setdefault(category, []).append(item)
    for category in grouped:
        grouped[category] = _unique_items(grouped[category])
    shelves = []
    for category, shelf_items in sorted(
        grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])
    )[:limit]:
        shelves.append(_shelf(
            category,
            public_facets.facet_label("category", category),
            shelf_items,
        ))
        shelves[-1]["items"] = shelves[-1]["items"][:per_shelf]
    return shelves
