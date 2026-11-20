"""Shared repository helpers and base class."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from ..db import Database
from ..domain import ApplyResult, PlaybackSessionState, ProgressState


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class BaseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _progress_dict(row: dict) -> dict:
        return {
            "listener_id": row["listener_id"],
            "edition_id": row["edition_id"],
            "position_ms": int(row["position_ms"]),
            "track_id": row["track_id"],
            "active_session_id": row["active_session_id"],
            "last_event_id": row["last_event_id"],
            "version": int(row["version"]),
            "completed_at": row["completed_at"],
            "last_completed_position_ms": row["last_completed_position_ms"],
            "updated_at": row["updated_at"],
        }

    def _result_from_rows(
        self, event_row: dict, progress_row: dict, *, duplicate: bool
    ) -> dict:
        return {
            "applied": bool(event_row["applied"]),
            "conflict": not bool(event_row["applied"]),
            "reason": event_row["reason_code"],
            "duplicate": duplicate,
            "progress": self._progress_dict(progress_row),
            "session_state": None,
            "event_id": str(event_row["event_id"]),
        }

    def _enqueue(
        self,
        cur,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        schema_version: int = 1,
    ) -> None:
        cur.execute(
            """
            INSERT INTO outbox_events
              (aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                aggregate_type,
                aggregate_id,
                event_type,
                schema_version,
                Jsonb(_jsonable(payload)),
            ),
        )
