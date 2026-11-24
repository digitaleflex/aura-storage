"""Bridge the public portal's shelves to the audiobook scoring engine.

The portal has no audiobook listener session, so it translates its own signals
(favourites, listening progress, authors, duration) into the preference and
candidate shapes used by ``audiobook.services.recommendations.score_candidates``.
The same ranking and the same ``reasons`` vocabulary are reused; on any failure
the portal falls back to its small local author-based recommender.
"""
from __future__ import annotations

from . import public_ui


def _prefs_from_signals(items: list[dict]) -> dict:
    authors: list[str] = []
    favourites_ms: list[int] = []
    for item in items:
        progress = float(item.get("progress_seconds") or 0)
        if item.get("favorite") or progress > 0:
            author = str(item.get("author") or "").strip()
            if author and author not in authors:
                authors.append(author)
        if item.get("favorite") and item.get("duration_seconds"):
            favourites_ms.append(int(float(item["duration_seconds"]) * 1000))
    prefs = {
        "preferred_languages": [],
        "preferred_category_slugs": [],
        "preferred_authors": authors,
        "preferred_narrators": [],
        "min_duration_ms": None,
        "max_duration_ms": None,
        "prefer_completed": False,
    }
    if favourites_ms:
        average = sum(favourites_ms) // len(favourites_ms)
        prefs["min_duration_ms"] = int(average * 0.6)
        prefs["max_duration_ms"] = int(average * 1.6)
    return prefs


def _candidate(item: dict) -> dict:
    duration = int(float(item.get("duration_seconds") or 0) * 1000)
    author = str(item.get("author") or "").strip()
    return {
        "edition_id": str(item["id"]),
        "work_id": str(item["id"]),
        "edition_title": item.get("title") or item.get("display_name"),
        "work_title": item.get("title") or item.get("display_name"),
        "edition_language": "fr",
        "duration_ms": duration,
        "access_model": "free",
        "published_at": None,
        "category_slugs": list(item.get("tags") or []),
        "authors": [author] if author else [],
        "narrators": [],
        "in_library": False,
        "completed": False,
        "is_favorite": bool(item.get("favorite")),
        "progress_ms": int(float(item.get("progress_seconds") or 0) * 1000),
    }


def rank(items: list[dict], limit: int = 8) -> list[dict]:
    """Rank portal items with the audiobook engine, or fall back to local logic."""
    try:
        from audiobook.services.recommendations import score_candidates

        playable = [item for item in items if item.get("url")]
        if not playable:
            return public_ui.recommend(items, limit)
        result = score_candidates(
            _prefs_from_signals(playable),
            [_candidate(item) for item in playable],
            limit=limit,
            exclude_library=False,
        )
        by_id = {str(item["id"]): item for item in playable}
        ranked = []
        for scored in result["items"]:
            item = by_id.get(scored["edition_id"])
            if item is not None:
                ranked.append({
                    **item,
                    "reco_score": scored["score"],
                    "reco_reasons": scored["reasons"],
                })
        return ranked or public_ui.recommend(items, limit)
    except Exception:
        # A coupling or scoring problem must never break the public catalogue.
        return public_ui.recommend(items, limit)
