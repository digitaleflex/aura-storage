"""Repository: Audit."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..domain import (
    ApplyResult,
    PlaybackEvent,
    PlaybackSessionState,
    ProgressState,
    apply_event,
)
from ..errors import ConflictError, NotFoundError
from ..ids import new_id, normalize_email
from .base import BaseRepository, _jsonable


class AuditRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Audit and outbox
    # ------------------------------------------------------------------
    def record_audit(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        action: str,
        target_type: str = "",
        target_id: str | None = None,
        outcome: str = "success",
        reason: str = "",
        request_id: str = "",
    ) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_events
                      (id, actor_type, actor_id, action, target_type, target_id,
                       outcome, reason, request_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_id(),
                        actor_type,
                        actor_id,
                        action,
                        target_type,
                        target_id,
                        outcome,
                        reason,
                        request_id,
                    ),
                )

    def list_audit(self, *, limit: int = 100) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT %s",
                    (max(1, min(limit, 500)),),
                )
                return list(cur.fetchall())
