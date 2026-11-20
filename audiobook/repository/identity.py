"""Repository: Identity."""
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


class IdentityRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Identity and sessions
    # ------------------------------------------------------------------
    def create_listener(
        self,
        email: str,
        display_name: str = "",
        *,
        locale: str = "fr",
        timezone: str = "Europe/Paris",
    ) -> dict:
        normalized = normalize_email(email)
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO listeners
                      (id, email, email_normalized, display_name, locale, timezone)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email_normalized) DO UPDATE SET
                      display_name = CASE
                        WHEN listeners.display_name = '' THEN EXCLUDED.display_name
                        ELSE listeners.display_name
                      END,
                      updated_at = now()
                    RETURNING *
                    """,
                    (new_id(), email.strip(), normalized, display_name, locale, timezone),
                )
                return cur.fetchone()

    def get_listener(self, listener_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM listeners WHERE id = %s", (listener_id,))
                return cur.fetchone()

    def get_listener_by_email(self, email: str) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM listeners WHERE email_normalized = %s",
                    (normalize_email(email),),
                )
                return cur.fetchone()

    def get_listener_by_identity(self, provider: str, subject: str) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT l.*, i.provider, i.subject
                    FROM listener_identities i
                    JOIN listeners l ON l.id = i.listener_id
                    WHERE i.provider = %s AND i.subject = %s
                    """,
                    (provider, subject),
                )
                return cur.fetchone()

    def create_identity(self, listener_id: UUID, provider: str, subject: str) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO listener_identities
                      (id, listener_id, provider, subject)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (provider, subject) DO NOTHING
                    """,
                    (new_id(), listener_id, provider, subject),
                )

    def create_device(
        self, listener_id: UUID, name: str = "", platform: str = ""
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO devices (id, listener_id, name, platform, status, last_seen_at)
                    VALUES (%s, %s, %s, %s, 'active', now())
                    RETURNING *
                    """,
                    (new_id(), listener_id, name, platform),
                )
                return cur.fetchone()

    def get_device(self, device_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                return cur.fetchone()

    def touch_device(self, device_id: UUID) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE devices SET last_seen_at = now() WHERE id = %s",
                    (device_id,),
                )

    def create_session(
        self,
        listener_id: UUID,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
        device_id: UUID | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO listener_sessions
                      (id, listener_id, device_id, token_hash, csrf_hash, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), listener_id, device_id, token_hash, csrf_hash, expires_at),
                )
                return cur.fetchone()

    def get_session_by_token_hash(self, token_hash: str) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.*, l.email, l.display_name, l.status AS listener_status,
                           l.locale, l.timezone, l.territory_code
                    FROM listener_sessions s
                    JOIN listeners l ON l.id = s.listener_id
                    WHERE s.token_hash = %s
                    """,
                    (token_hash,),
                )
                return cur.fetchone()

    def revoke_session(self, session_id: UUID) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE listener_sessions SET revoked_at = now() WHERE id = %s",
                    (session_id,),
                )

    def touch_session(self, session_id: UUID) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE listener_sessions SET last_seen_at = now() WHERE id = %s",
                    (session_id,),
                )


    # ------------------------------------------------------------------
    # Devices, profile, deletion (Lot 1 completion / D-10, D-11)
    # ------------------------------------------------------------------
    def list_devices(self, listener_id: UUID) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM devices
                    WHERE listener_id = %s
                    ORDER BY created_at DESC
                    """,
                    (listener_id,),
                )
                return list(cur.fetchall())

    def register_device(
        self,
        listener_id: UUID,
        *,
        name: str = "",
        platform: str = "",
        max_devices: int | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM listeners WHERE id = %s FOR UPDATE",
                    (listener_id,),
                )
                if cur.fetchone() is None:
                    raise NotFoundError("listener not found", code="LISTENER_NOT_FOUND")
                if max_devices is not None:
                    cur.execute(
                        """
                        SELECT count(*) AS count FROM devices
                        WHERE listener_id = %s AND status = 'active'
                        """,
                        (listener_id,),
                    )
                    count = int(cur.fetchone()["count"])
                    if count >= max_devices:
                        raise ConflictError(
                            "maximum devices reached",
                            code="TOO_MANY_DEVICES",
                            details={"limit": max_devices, "active": count},
                        )
                cur.execute(
                    """
                    INSERT INTO devices
                      (id, listener_id, name, platform, status, last_seen_at)
                    VALUES (%s, %s, %s, %s, 'active', now())
                    RETURNING *
                    """,
                    (new_id(), listener_id, name, platform),
                )
                return cur.fetchone()

    def revoke_device(self, listener_id: UUID, device_id: UUID) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE devices
                    SET status = 'revoked', revoked_at = now()
                    WHERE id = %s AND listener_id = %s AND status <> 'revoked'
                    RETURNING id
                    """,
                    (device_id, listener_id),
                )
                row = cur.fetchone()
                if row is None:
                    return False
                # Revoked devices must not keep renewing active playback leases.
                cur.execute(
                    """
                    UPDATE playback_sessions
                    SET state = 'abandoned', active_lease_until = NULL,
                        version = version + 1
                    WHERE device_id = %s AND state = 'active'
                    """,
                    (device_id,),
                )
                return True

    def update_listener(
        self,
        listener_id: UUID,
        *,
        display_name: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        territory_code: str | None = None,
    ) -> dict:
        fields = []
        values = []
        if display_name is not None:
            fields.append("display_name = %s")
            values.append(display_name)
        if locale is not None:
            fields.append("locale = %s")
            values.append(locale)
        if timezone is not None:
            fields.append("timezone = %s")
            values.append(timezone)
        if territory_code is not None:
            fields.append("territory_code = %s")
            values.append(territory_code)
        if not fields:
            listener = self.get_listener(listener_id)
            if listener is None:
                raise NotFoundError("listener not found", code="LISTENER_NOT_FOUND")
            return listener
        fields.append("updated_at = now()")
        values.extend([listener_id])
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE listeners SET {', '.join(fields)} WHERE id = %s RETURNING *",
                    tuple(values),
                )
                row = cur.fetchone()
                if row is None:
                    raise NotFoundError("listener not found", code="LISTENER_NOT_FOUND")
                return row

    def request_listener_deletion(self, listener_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE listeners
                    SET status = 'pending_deletion',
                        deletion_requested_at = COALESCE(deletion_requested_at, now()),
                        updated_at = now()
                    WHERE id = %s AND status IN ('active', 'suspended')
                    RETURNING *
                    """,
                    (listener_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ConflictError(
                        "listener cannot be moved to pending deletion",
                        code="DELETION_REQUEST_REJECTED",
                    )
                cur.execute(
                    "UPDATE listener_sessions SET revoked_at = now() WHERE listener_id = %s AND revoked_at IS NULL",
                    (listener_id,),
                )
                cur.execute(
                    """
                    UPDATE playback_sessions
                    SET state = 'abandoned', active_lease_until = NULL,
                        version = version + 1
                    WHERE listener_id = %s AND state = 'active'
                    """,
                    (listener_id,),
                )
                self._enqueue(
                    cur,
                    aggregate_type="listener",
                    aggregate_id=str(listener_id),
                    event_type="listener.deletion.requested",
                    payload={"listener_id": str(listener_id)},
                )
                return row

    def list_auth_sessions(self, listener_id: UUID) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, listener_id, device_id, expires_at, revoked_at,
                           created_at, last_seen_at
                    FROM listener_sessions
                    WHERE listener_id = %s
                    ORDER BY created_at DESC
                    """,
                    (listener_id,),
                )
                return list(cur.fetchall())

    def revoke_auth_session(self, listener_id: UUID, session_id: UUID) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE listener_sessions SET revoked_at = now()
                    WHERE id = %s AND listener_id = %s AND revoked_at IS NULL
                    RETURNING id
                    """,
                    (session_id, listener_id),
                )
                return cur.fetchone() is not None
