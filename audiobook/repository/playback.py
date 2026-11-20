"""Repository: Playback."""
from __future__ import annotations

from psycopg.types.json import Jsonb

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


class PlaybackRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Access decisions
    # ------------------------------------------------------------------
    def record_access_decision(
        self,
        *,
        listener_id: UUID,
        edition_id: UUID,
        action: str,
        decision: str,
        reason_code: str,
        sources: list[str],
        policy_version: str,
        territory_code: str,
        decided_at: datetime,
        expires_at: datetime | None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO access_decisions
                      (id, listener_id, resource_type, resource_id, action,
                       decision, reason_code, sources, policy_version,
                       territory_code, decided_at, expires_at)
                    VALUES (%s, %s, 'edition', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        listener_id,
                        edition_id,
                        action,
                        decision,
                        reason_code,
                        Jsonb(sources),
                        policy_version,
                        territory_code,
                        decided_at,
                        expires_at,
                    ),
                )
                return cur.fetchone()

    def list_access_decisions(
        self, listener_id: UUID, *, limit: int = 50
    ) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM access_decisions
                    WHERE listener_id = %s
                    ORDER BY decided_at DESC LIMIT %s
                    """,
                    (listener_id, max(1, min(limit, 200))),
                )
                return list(cur.fetchall())


    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def get_progress(self, listener_id: UUID, edition_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM listening_progress
                    WHERE listener_id = %s AND edition_id = %s
                    """,
                    (listener_id, edition_id),
                )
                return cur.fetchone()

    def get_session(self, session_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM playback_sessions WHERE id = %s",
                    (session_id,),
                )
                return cur.fetchone()

    def get_active_session(self, listener_id: UUID, edition_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM playback_sessions
                    WHERE listener_id = %s AND edition_id = %s AND state = 'active'
                    """,
                    (listener_id, edition_id),
                )
                return cur.fetchone()

    def start_playback_session(
        self,
        listener_id: UUID,
        edition_id: UUID,
        *,
        device_id: UUID | None,
        lease_seconds: int,
        now: datetime,
        takeover: bool = False,
        max_simultaneous: int | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                # Serialize session starts per listener so global limits are safe.
                cur.execute(
                    "SELECT id FROM listeners WHERE id = %s FOR UPDATE",
                    (listener_id,),
                )
                if cur.fetchone() is None:
                    raise NotFoundError("listener not found", code="LISTENER_NOT_FOUND")
                cur.execute(
                    """
                    SELECT * FROM playback_sessions
                    WHERE listener_id = %s AND edition_id = %s AND state = 'active'
                    FOR UPDATE
                    """,
                    (listener_id, edition_id),
                )
                active = cur.fetchone()
                if active is not None:
                    if not takeover:
                        raise ConflictError(
                            "an active playback session already exists",
                            code="ACTIVE_SESSION_EXISTS",
                            details={
                                "active_session_id": str(active["id"]),
                                "started_at": active["started_at"].isoformat(),
                            },
                        )
                    cur.execute(
                        """
                        UPDATE playback_sessions
                        SET state = 'abandoned', active_lease_until = NULL,
                            version = version + 1
                        WHERE id = %s
                        """,
                        (active["id"],),
                    )
                elif max_simultaneous is not None:
                    cur.execute(
                        """
                        SELECT count(*) AS count FROM playback_sessions
                        WHERE listener_id = %s AND state = 'active'
                        """,
                        (listener_id,),
                    )
                    count = int(cur.fetchone()["count"])
                    if count >= max_simultaneous:
                        raise ConflictError(
                            "maximum simultaneous playback sessions reached",
                            code="TOO_MANY_ACTIVE_SESSIONS",
                            details={"limit": max_simultaneous, "active": count},
                        )
                cur.execute(
                    """
                    INSERT INTO playback_sessions
                      (id, listener_id, edition_id, device_id, state,
                       started_at, last_heartbeat_at, active_lease_until)
                    VALUES (%s, %s, %s, %s, 'active', %s, %s, %s)
                    ON CONFLICT (listener_id, edition_id) WHERE state = 'active'
                    DO NOTHING
                    RETURNING *
                    """,
                    (
                        new_id(),
                        listener_id,
                        edition_id,
                        device_id,
                        now,
                        now,
                        now + timedelta(seconds=lease_seconds),
                    ),
                )
                session = cur.fetchone()
                if session is None:
                    raise ConflictError(
                        "an active playback session already exists",
                        code="ACTIVE_SESSION_EXISTS",
                    )
                cur.execute(
                    """
                    INSERT INTO listening_progress
                      (listener_id, edition_id, position_ms, version, updated_at)
                    VALUES (%s, %s, 0, 1, %s)
                    ON CONFLICT (listener_id, edition_id) DO NOTHING
                    """,
                    (listener_id, edition_id, now),
                )
                self._enqueue(
                    cur,
                    aggregate_type="playback_session",
                    aggregate_id=str(session["id"]),
                    event_type="playback.session.started",
                    payload={
                        "session_id": str(session["id"]),
                        "listener_id": str(listener_id),
                        "edition_id": str(edition_id),
                        "device_id": str(device_id) if device_id else None,
                        "takeover": takeover,
                    },
                )
                return session

    def append_event(
        self,
        listener_id: UUID,
        session_id: UUID,
        event: PlaybackEvent,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM playback_sessions WHERE id = %s FOR UPDATE",
                    (session_id,),
                )
                session_row = cur.fetchone()
                if session_row is None or session_row["listener_id"] != listener_id:
                    raise NotFoundError(
                        "playback session not found", code="SESSION_NOT_FOUND"
                    )
                if (
                    event.listener_id != listener_id
                    or event.session_id != session_id
                    or event.edition_id != session_row["edition_id"]
                ):
                    raise ConflictError(
                        "event context does not match the session",
                        code="EVENT_CONTEXT_MISMATCH",
                    )
                cur.execute(
                    """
                    SELECT * FROM listening_progress
                    WHERE listener_id = %s AND edition_id = %s
                    FOR UPDATE
                    """,
                    (listener_id, session_row["edition_id"]),
                )
                progress_row = cur.fetchone()
                if progress_row is None:
                    cur.execute(
                        """
                        INSERT INTO listening_progress
                          (listener_id, edition_id, position_ms, version, updated_at)
                        VALUES (%s, %s, 0, 1, %s)
                        ON CONFLICT (listener_id, edition_id) DO NOTHING
                        """,
                        (listener_id, session_row["edition_id"], now),
                    )
                    cur.execute(
                        """
                        SELECT * FROM listening_progress
                        WHERE listener_id = %s AND edition_id = %s FOR UPDATE
                        """,
                        (listener_id, session_row["edition_id"]),
                    )
                    progress_row = cur.fetchone()

                cur.execute(
                    "SELECT * FROM listening_events WHERE event_id = %s",
                    (event.event_id,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    return self._result_from_rows(
                        existing, progress_row, duplicate=True
                    )

                cur.execute(
                    """
                    SELECT 1 AS present FROM listening_events
                    WHERE session_id = %s AND client_seq = %s
                    """,
                    (session_id, event.client_seq),
                )
                if cur.fetchone() is not None:
                    return {
                        "applied": False,
                        "conflict": False,
                        "reason": "stale_sequence",
                        "duplicate": False,
                        "progress": self._progress_dict(progress_row),
                        "session_state": session_row["state"],
                        "event_id": str(event.event_id),
                    }

                # A paused session may resume, but only if no other device holds
                # the single active lease for this edition.
                if session_row["state"] == "paused":
                    cur.execute(
                        """
                        SELECT 1 AS present FROM playback_sessions
                        WHERE listener_id = %s AND edition_id = %s
                          AND state = 'active' AND id <> %s
                        """,
                        (listener_id, session_row["edition_id"], session_id),
                    )
                    if cur.fetchone() is not None:
                        return {
                            "applied": False,
                            "conflict": True,
                            "reason": "another_session_active",
                            "duplicate": False,
                            "progress": self._progress_dict(progress_row),
                            "session_state": session_row["state"],
                            "event_id": str(event.event_id),
                        }

                progress = ProgressState(
                    listener_id=progress_row["listener_id"],
                    edition_id=progress_row["edition_id"],
                    position_ms=int(progress_row["position_ms"]),
                    track_id=progress_row["track_id"],
                    active_session_id=progress_row["active_session_id"],
                    last_event_id=progress_row["last_event_id"],
                    version=int(progress_row["version"]),
                    completed_at=progress_row["completed_at"],
                    last_completed_position_ms=progress_row["last_completed_position_ms"],
                    updated_at=progress_row["updated_at"],
                )
                session = PlaybackSessionState(
                    id=session_row["id"],
                    listener_id=session_row["listener_id"],
                    edition_id=session_row["edition_id"],
                    state=session_row["state"],
                    last_client_seq=int(session_row["last_client_seq"]),
                    last_heartbeat_at=session_row["last_heartbeat_at"],
                    active_lease_until=session_row["active_lease_until"],
                    version=int(session_row["version"]),
                )
                result: ApplyResult = apply_event(
                    progress, session, event, now, takeover=event.kind == "takeover"
                )

                cur.execute(
                    """
                    INSERT INTO listening_events
                      (id, event_id, session_id, listener_id, edition_id, track_id,
                       kind, client_seq, occurred_at_client, received_at_server,
                       position_ms, duration_ms, playback_rate, applied, reason_code)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_id(),
                        event.event_id,
                        session_id,
                        listener_id,
                        event.edition_id,
                        event.track_id,
                        event.kind,
                        event.client_seq,
                        event.occurred_at_client,
                        now,
                        event.position_ms,
                        event.duration_ms,
                        event.playback_rate,
                        result.applied,
                        result.reason,
                    ),
                )

                new_state = result.session_state if result.applied else session_row["state"]
                new_lease = (
                    now + timedelta(seconds=lease_seconds)
                    if result.applied and new_state == "active"
                    else (None if result.applied else session_row["active_lease_until"])
                )
                cur.execute(
                    """
                    UPDATE playback_sessions
                    SET last_client_seq = GREATEST(last_client_seq, %s),
                        last_heartbeat_at = %s,
                        active_lease_until = %s,
                        state = %s,
                        version = version + 1
                    WHERE id = %s
                    """,
                    (event.client_seq, now, new_lease, new_state, session_id),
                )
                if result.applied:
                    cur.execute(
                        """
                        UPDATE listening_progress
                        SET position_ms = %s, track_id = %s,
                            active_session_id = %s, last_event_id = %s,
                            version = %s, completed_at = %s,
                            last_completed_position_ms = %s, updated_at = %s
                        WHERE listener_id = %s AND edition_id = %s AND version = %s
                        """,
                        (
                            result.progress.position_ms,
                            result.progress.track_id,
                            result.progress.active_session_id,
                            result.progress.last_event_id,
                            result.progress.version,
                            result.progress.completed_at,
                            result.progress.last_completed_position_ms,
                            now,
                            listener_id,
                            event.edition_id,
                            progress.version,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise ConflictError(
                            "progress was modified concurrently",
                            code="PROGRESS_CONFLICT",
                        )
                    self._enqueue(
                        cur,
                        aggregate_type="listening_progress",
                        aggregate_id=f"{listener_id}:{event.edition_id}",
                        event_type="listening.progress.updated",
                        payload={
                            "listener_id": str(listener_id),
                            "edition_id": str(event.edition_id),
                            "session_id": str(session_id),
                            "position_ms": result.progress.position_ms,
                            "track_id": str(result.progress.track_id)
                            if result.progress.track_id
                            else None,
                            "version": result.progress.version,
                            "completed": result.progress.completed_at is not None,
                        },
                    )
                return {
                    "applied": result.applied,
                    "conflict": result.conflict,
                    "reason": result.reason,
                    "duplicate": result.duplicate,
                    "progress": self._progress_dict(
                        {
                            "listener_id": result.progress.listener_id,
                            "edition_id": result.progress.edition_id,
                            "position_ms": result.progress.position_ms,
                            "track_id": result.progress.track_id,
                            "active_session_id": result.progress.active_session_id,
                            "last_event_id": result.progress.last_event_id,
                            "version": result.progress.version,
                            "completed_at": result.progress.completed_at,
                            "last_completed_position_ms": result.progress.last_completed_position_ms,
                            "updated_at": result.progress.updated_at,
                        }
                    ),
                    "session_state": new_state,
                    "event_id": str(event.event_id),
                }

    # ------------------------------------------------------------------
    # History, stats, access dashboard (Lot 2)
    # ------------------------------------------------------------------
    def listening_history(self, listener_id: UUID, *, limit: int = 50) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.*, e.title AS edition_title, e.slug, e.duration_ms,
                           w.id AS work_id, w.title AS work_title
                    FROM listening_progress p
                    JOIN editions e ON e.id = p.edition_id
                    JOIN works w ON w.id = e.work_id
                    WHERE p.listener_id = %s
                    ORDER BY p.updated_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (listener_id, max(1, min(limit, 200))),
                )
                return list(cur.fetchall())

    def listening_stats(self, listener_id: UUID) -> dict:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      count(*)::int AS started,
                      count(*) FILTER (WHERE completed_at IS NOT NULL)::int AS completed,
                      count(*) FILTER (WHERE completed_at IS NULL)::int AS in_progress,
                      max(updated_at) AS last_listened_at
                    FROM listening_progress
                    WHERE listener_id = %s
                    """,
                    (listener_id,),
                )
                progress = cur.fetchone() or {}
                cur.execute(
                    """
                    SELECT count(*)::int AS events,
                           count(DISTINCT edition_id)::int AS editions
                    FROM listening_events
                    WHERE listener_id = %s AND applied = true
                    """,
                    (listener_id,),
                )
                events = cur.fetchone() or {}
                return {
                    "started": int(progress.get("started") or 0),
                    "completed": int(progress.get("completed") or 0),
                    "in_progress": int(progress.get("in_progress") or 0),
                    "last_listened_at": progress.get("last_listened_at"),
                    "applied_events": int(events.get("events") or 0),
                    "editions_with_events": int(events.get("editions") or 0),
                }

    def access_refusal_dashboard(self, *, limit: int = 200) -> dict:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT reason_code, count(*)::int AS count
                    FROM access_decisions
                    WHERE decision = 'deny'
                    GROUP BY reason_code
                    ORDER BY count DESC
                    """
                )
                by_reason = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT action, count(*)::int AS count
                    FROM access_decisions
                    WHERE decision = 'deny'
                    GROUP BY action
                    ORDER BY count DESC
                    """
                )
                by_action = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT d.*, e.title AS edition_title, e.slug
                    FROM access_decisions d
                    LEFT JOIN editions e ON e.id = d.resource_id
                    WHERE d.decision = 'deny'
                    ORDER BY d.decided_at DESC
                    LIMIT %s
                    """,
                    (max(1, min(limit, 500)),),
                )
                recent = list(cur.fetchall())
                return {
                    "by_reason": by_reason,
                    "by_action": by_action,
                    "recent": recent,
                }
