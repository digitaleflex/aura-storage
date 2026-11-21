"""Repository: listener preferences and recommendations."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .base import BaseRepository, _jsonable


DEFAULT_PREFERENCES: dict[str, Any] = {
    "preferred_languages": [],
    "preferred_category_slugs": [],
    "preferred_authors": [],
    "preferred_narrators": [],
    "min_duration_ms": None,
    "max_duration_ms": None,
    "prefer_completed": False,
}


class RecommendationsRepository(BaseRepository):
    def get_listener_preferences(self, listener_id: UUID) -> dict:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT listener_id, preferred_languages, preferred_category_slugs,
                           preferred_authors, preferred_narrators,
                           min_duration_ms, max_duration_ms, prefer_completed, updated_at
                    FROM listener_preferences
                    WHERE listener_id = %s
                    """,
                    (listener_id,),
                )
                row = cur.fetchone()
        if row is None:
            return {"listener_id": str(listener_id), **DEFAULT_PREFERENCES, "updated_at": None}
        return {
            "listener_id": str(row["listener_id"]),
            "preferred_languages": list(row["preferred_languages"] or []),
            "preferred_category_slugs": list(row["preferred_category_slugs"] or []),
            "preferred_authors": list(row["preferred_authors"] or []),
            "preferred_narrators": list(row["preferred_narrators"] or []),
            "min_duration_ms": row["min_duration_ms"],
            "max_duration_ms": row["max_duration_ms"],
            "prefer_completed": bool(row["prefer_completed"]),
            "updated_at": row["updated_at"],
        }

    def upsert_listener_preferences(self, listener_id: UUID, prefs: dict[str, Any]) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO listener_preferences (
                        listener_id, preferred_languages, preferred_category_slugs,
                        preferred_authors, preferred_narrators,
                        min_duration_ms, max_duration_ms, prefer_completed, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (listener_id) DO UPDATE SET
                        preferred_languages = EXCLUDED.preferred_languages,
                        preferred_category_slugs = EXCLUDED.preferred_category_slugs,
                        preferred_authors = EXCLUDED.preferred_authors,
                        preferred_narrators = EXCLUDED.preferred_narrators,
                        min_duration_ms = EXCLUDED.min_duration_ms,
                        max_duration_ms = EXCLUDED.max_duration_ms,
                        prefer_completed = EXCLUDED.prefer_completed,
                        updated_at = now()
                    RETURNING listener_id, preferred_languages, preferred_category_slugs,
                              preferred_authors, preferred_narrators,
                              min_duration_ms, max_duration_ms, prefer_completed, updated_at
                    """,
                    (
                        listener_id,
                        list(prefs.get("preferred_languages") or []),
                        list(prefs.get("preferred_category_slugs") or []),
                        list(prefs.get("preferred_authors") or []),
                        list(prefs.get("preferred_narrators") or []),
                        prefs.get("min_duration_ms"),
                        prefs.get("max_duration_ms"),
                        bool(prefs.get("prefer_completed", False)),
                    ),
                )
                row = cur.fetchone()
        return {
            "listener_id": str(row["listener_id"]),
            "preferred_languages": list(row["preferred_languages"] or []),
            "preferred_category_slugs": list(row["preferred_category_slugs"] or []),
            "preferred_authors": list(row["preferred_authors"] or []),
            "preferred_narrators": list(row["preferred_narrators"] or []),
            "min_duration_ms": row["min_duration_ms"],
            "max_duration_ms": row["max_duration_ms"],
            "prefer_completed": bool(row["prefer_completed"]),
            "updated_at": row["updated_at"],
        }

    def list_recommendation_candidates(self, listener_id: UUID, *, limit: int = 200) -> list[dict]:
        """Return published editions with metadata needed for scoring."""
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        e.id AS edition_id,
                        e.work_id,
                        e.title AS edition_title,
                        e.language AS edition_language,
                        e.duration_ms,
                        e.access_model,
                        e.published_at,
                        e.description AS edition_description,
                        w.title AS work_title,
                        w.language AS work_language,
                        COALESCE((
                            SELECT array_agg(DISTINCT c.slug)
                            FROM work_categories wc
                            JOIN categories c ON c.id = wc.category_id
                            WHERE wc.work_id = w.id
                        ), '{}') AS category_slugs,
                        COALESCE((
                            SELECT array_agg(DISTINCT co.name)
                            FROM work_contributors wc2
                            JOIN contributors co ON co.id = wc2.contributor_id
                            WHERE wc2.work_id = w.id AND wc2.role = 'author'
                        ), '{}') AS authors,
                        COALESCE((
                            SELECT array_agg(DISTINCT co.name)
                            FROM work_contributors wc2
                            JOIN contributors co ON co.id = wc2.contributor_id
                            WHERE wc2.work_id = w.id AND wc2.role = 'narrator'
                        ), '{}') AS narrators,
                        EXISTS (
                            SELECT 1 FROM library_entries le
                            WHERE le.listener_id = %s AND le.work_id = w.id
                        ) AS in_library,
                        EXISTS (
                            SELECT 1 FROM favorites f
                            WHERE f.listener_id = %s AND f.work_id = w.id
                        ) AS is_favorite,
                        (
                            SELECT p.completed_at IS NOT NULL
                            FROM listening_progress p
                            WHERE p.listener_id = %s AND p.edition_id = e.id
                        ) AS completed,
                        (
                            SELECT p.position_ms
                            FROM listening_progress p
                            WHERE p.listener_id = %s AND p.edition_id = e.id
                        ) AS progress_ms
                    FROM editions e
                    JOIN works w ON w.id = e.work_id
                    WHERE e.status = 'published'
                    ORDER BY e.published_at DESC NULLS LAST, e.id
                    LIMIT %s
                    """,
                    (listener_id, listener_id, listener_id, listener_id, limit),
                )
                return list(cur.fetchall())
