"""Serialization helpers for service responses."""
from __future__ import annotations

from .base import BaseService


class SerializationService(BaseService):
    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _public_edition_row(row: dict) -> dict:
        return {
            "id": row["id"],
            "work_id": row["work_id"],
            "title": row["title"] or row["work_title"],
            "language": row["language"] or row["work_language"],
            "description": row["description"],
            "slug": row["slug"],
            "duration_ms": int(row["duration_ms"]),
            "access_model": row["access_model"],
            "published_at": row["published_at"],
            "cover_asset_id": row["cover_asset_id"],
            "track_count": int(row.get("track_count", 0)),
            "ready_track_count": int(row.get("ready_track_count", 0)),
        }

    @classmethod
    def _public_bundle(cls, bundle: dict) -> dict:
        edition = bundle["edition"]
        contributors = bundle["contributors"]
        return {
            "edition": cls._public_edition_row(edition),
            "authors": [
                {"id": c["id"], "name": c["name"], "position": c["position"]}
                for c in contributors
                if c["role"] == "author"
            ],
            "narrators": [
                {"id": c["id"], "name": c["name"], "position": c["position"]}
                for c in contributors
                if c["role"] == "narrator"
            ],
            "tracks": [
                {
                    "id": t["id"],
                    "position": t["position"],
                    "title": t["title"],
                    "start_ms": int(t["start_ms"]),
                    "end_ms": int(t["end_ms"]),
                    "duration_ms": int(t["end_ms"]) - int(t["start_ms"]),
                    "status": t["status"],
                }
                for t in bundle["tracks"]
            ],
            "chapters": [
                {
                    "id": c["id"],
                    "position": c["position"],
                    "title": c["title"],
                    "start_ms": int(c["start_ms"]),
                    "end_ms": int(c["end_ms"]),
                }
                for c in bundle["chapters"]
            ],
        }
