"""Service: listener preferences and automatic recommendations.

The scoring is a pure function (``score_candidates``) so the public portal can
reuse the same signals without depending on the service's database or sessions.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .. import auth
from .base import BaseService


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_any(haystack: list[str], needles: list[str]) -> list[str]:
    if not haystack or not needles:
        return []
    normalized_haystack = {_norm(h) for h in haystack if h}
    matches: list[str] = []
    for needle in needles:
        n = _norm(needle)
        if n and n in normalized_haystack:
            matches.append(needle)
    return matches


def score_candidates(
    prefs: dict,
    candidates: list[dict],
    *,
    limit: int = 10,
    exclude_library: bool = True,
) -> dict:
    """Score catalogue candidates against one listener's preferences.

    Pure: no repository, no session, no I/O. ``candidates`` rows carry the same
    keys as ``Repository.list_recommendation_candidates``. The portal builds a
    compatible list from its own published items and gets the same ranking and
    the same ``reasons`` vocabulary.
    """
    limit = max(1, min(limit, 50))

    preferred_languages = {_norm(v) for v in prefs.get("preferred_languages", []) if v}
    preferred_categories = {_norm(v) for v in prefs.get("preferred_category_slugs", []) if v}
    preferred_authors = {_norm(v) for v in prefs.get("preferred_authors", []) if v}
    preferred_narrators = {_norm(v) for v in prefs.get("preferred_narrators", []) if v}
    min_duration_ms = prefs.get("min_duration_ms")
    max_duration_ms = prefs.get("max_duration_ms")
    prefer_completed = bool(prefs.get("prefer_completed", False))

    has_explicit_prefs = any(
        [
            preferred_languages,
            preferred_categories,
            preferred_authors,
            preferred_narrators,
            min_duration_ms is not None,
            max_duration_ms is not None,
        ]
    )

    scored: list[dict[str, Any]] = []
    for row in candidates:
        in_library = bool(row.get("in_library"))
        completed = bool(row.get("completed"))
        if exclude_library and in_library:
            continue
        if completed and not prefer_completed:
            continue

        score = 0.0
        reasons: list[str] = []

        lang = _norm(str(row.get("edition_language") or row.get("work_language") or ""))
        if lang and lang in preferred_languages:
            score += 5.0
            reasons.append("preferred_language")

        row_categories = [str(c) for c in (row.get("category_slugs") or []) if c]
        cat_matches = [c for c in row_categories if _norm(c) in preferred_categories]
        if cat_matches:
            score += 4.0 + min(len(cat_matches), 3) * 0.5
            reasons.append("preferred_category")

        row_authors = [str(a) for a in (row.get("authors") or []) if a]
        author_matches = [a for a in row_authors if _norm(a) in preferred_authors]
        if author_matches:
            score += 3.0 + min(len(author_matches), 2) * 0.5
            reasons.append("preferred_author")

        row_narrators = [str(n) for n in (row.get("narrators") or []) if n]
        narrator_matches = [n for n in row_narrators if _norm(n) in preferred_narrators]
        if narrator_matches:
            score += 2.5 + min(len(narrator_matches), 2) * 0.5
            reasons.append("preferred_narrator")

        duration_ms = row.get("duration_ms")
        if duration_ms is not None:
            duration_ms = int(duration_ms)
            if min_duration_ms is not None and duration_ms < int(min_duration_ms):
                score -= 2.0
                reasons.append("below_min_duration")
            if max_duration_ms is not None and duration_ms > int(max_duration_ms):
                score -= 2.0
                reasons.append("above_max_duration")
            if (
                (min_duration_ms is None or duration_ms >= int(min_duration_ms))
                and (max_duration_ms is None or duration_ms <= int(max_duration_ms))
                and (min_duration_ms is not None or max_duration_ms is not None)
            ):
                score += 1.5
                reasons.append("preferred_duration")

        if bool(row.get("is_favorite")):
            score += 0.5
            reasons.append("favorite_signal")

        if row.get("progress_ms") and not completed:
            score += 0.5
            reasons.append("in_progress_signal")

        # Mild recency boost for discovery when no strong preference match.
        if not reasons:
            reasons.append("recent_catalog")

        # If user has no explicit preferences, still provide recent published items.
        if not has_explicit_prefs:
            score += 1.0

        scored.append(
            {
                "edition_id": str(row["edition_id"]),
                "work_id": str(row["work_id"]),
                "title": row.get("edition_title") or row.get("work_title"),
                "work_title": row.get("work_title"),
                "language": row.get("edition_language") or row.get("work_language"),
                "duration_ms": row.get("duration_ms"),
                "access_model": row.get("access_model"),
                "published_at": row.get("published_at"),
                "description": row.get("edition_description") or "",
                "category_slugs": row_categories,
                "authors": row_authors,
                "narrators": row_narrators,
                "in_library": in_library,
                "completed": completed,
                "score": round(score, 3),
                "reasons": reasons,
            }
        )

    scored.sort(
        key=lambda item: (
            -float(item["score"]),
            item["published_at"] is None,
            -(item["published_at"].timestamp() if item["published_at"] else 0),
            item["title"] or "",
        )
    )
    return {
        "items": scored[:limit],
        "preferences": prefs,
        "meta": {
            "limit": limit,
            "exclude_library": exclude_library,
            "candidate_count": len(candidates),
            "has_explicit_preferences": has_explicit_prefs,
        },
    }


class RecommendationsService(BaseService):
    def get_preferences(self, principal: auth.Principal) -> dict:
        return self.repo.get_listener_preferences(principal.listener_id)

    def update_preferences(
        self,
        principal: auth.Principal,
        *,
        preferred_languages: list[str],
        preferred_category_slugs: list[str],
        preferred_authors: list[str],
        preferred_narrators: list[str],
        min_duration_ms: int | None,
        max_duration_ms: int | None,
        prefer_completed: bool,
        request_id: str = "",
    ) -> dict:
        prefs = {
            "preferred_languages": [v.strip() for v in preferred_languages if v and v.strip()],
            "preferred_category_slugs": [v.strip().lower() for v in preferred_category_slugs if v and v.strip()],
            "preferred_authors": [v.strip() for v in preferred_authors if v and v.strip()],
            "preferred_narrators": [v.strip() for v in preferred_narrators if v and v.strip()],
            "min_duration_ms": min_duration_ms,
            "max_duration_ms": max_duration_ms,
            "prefer_completed": bool(prefer_completed),
        }
        if (
            prefs["min_duration_ms"] is not None
            and prefs["max_duration_ms"] is not None
            and prefs["min_duration_ms"] > prefs["max_duration_ms"]
        ):
            from ..errors import ValidationError

            raise ValidationError(
                "min_duration_ms must be <= max_duration_ms",
                code="INVALID_PREFERENCE_RANGE",
            )
        saved = self.repo.upsert_listener_preferences(principal.listener_id, prefs)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="listener.preferences.updated",
            target_type="listener",
            target_id=str(principal.listener_id),
            outcome="success",
            request_id=request_id,
        )
        return saved

    def recommend(
        self,
        principal: auth.Principal,
        *,
        limit: int = 10,
        exclude_library: bool = True,
    ) -> dict:
        prefs = self.repo.get_listener_preferences(principal.listener_id)
        candidates = self.repo.list_recommendation_candidates(
            principal.listener_id, limit=300
        )
        return score_candidates(
            prefs, candidates, limit=limit, exclude_library=exclude_library
        )
