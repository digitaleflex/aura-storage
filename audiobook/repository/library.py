"""Repository: Library."""
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


class LibraryRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Library and entitlements
    # ------------------------------------------------------------------
    def add_library_entry(
        self,
        listener_id: UUID,
        work_id: UUID,
        *,
        preferred_edition_id: UUID | None = None,
        source: str = "manual",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO library_entries
                      (id, listener_id, work_id, preferred_edition_id, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (listener_id, work_id) WHERE removed_at IS NULL
                    DO UPDATE SET
                      preferred_edition_id = COALESCE(
                        EXCLUDED.preferred_edition_id,
                        library_entries.preferred_edition_id
                      )
                    RETURNING *
                    """,
                    (new_id(), listener_id, work_id, preferred_edition_id, source),
                )
                return cur.fetchone()

    def remove_library_entry(self, listener_id: UUID, work_id: UUID) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE library_entries SET removed_at = now()
                    WHERE listener_id = %s AND work_id = %s AND removed_at IS NULL
                    """,
                    (listener_id, work_id),
                )
                return cur.rowcount == 1

    def list_library(self, listener_id: UUID) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT le.*, w.title AS work_title, w.language AS work_language,
                           e.slug, e.duration_ms, e.access_model,
                           e.status AS edition_status,
                           p.position_ms, p.completed_at,
                           p.updated_at AS progress_updated_at,
                           p.version AS progress_version
                    FROM library_entries le
                    JOIN works w ON w.id = le.work_id
                    LEFT JOIN editions e ON e.id = le.preferred_edition_id
                    LEFT JOIN listening_progress p
                      ON p.listener_id = le.listener_id
                     AND p.edition_id = le.preferred_edition_id
                    WHERE le.listener_id = %s AND le.removed_at IS NULL
                    ORDER BY le.added_at DESC
                    """,
                    (listener_id,),
                )
                return list(cur.fetchall())

    def set_favorite(self, listener_id: UUID, work_id: UUID, favorite: bool) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                if favorite:
                    cur.execute(
                        """
                        INSERT INTO favorites (listener_id, work_id)
                        VALUES (%s, %s)
                        ON CONFLICT (listener_id, work_id) DO NOTHING
                        """,
                        (listener_id, work_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM favorites WHERE listener_id = %s AND work_id = %s",
                        (listener_id, work_id),
                    )
                return favorite

    def create_entitlement(
        self,
        listener_id: UUID,
        *,
        source_type: str,
        source_id: str,
        scope_type: str,
        scope_id: str,
        valid_from: datetime,
        valid_until: datetime | None = None,
        status: str = "active",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entitlements
                      (id, listener_id, source_type, source_id, scope_type,
                       scope_id, valid_from, valid_until, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (listener_id, source_type, source_id, scope_type, scope_id)
                      WHERE status IN ('pending','active','suspended')
                    DO UPDATE SET
                      valid_until = COALESCE(EXCLUDED.valid_until, entitlements.valid_until),
                      status = EXCLUDED.status
                    RETURNING *
                    """,
                    (
                        new_id(),
                        listener_id,
                        source_type,
                        source_id,
                        scope_type,
                        scope_id,
                        valid_from,
                        valid_until,
                        status,
                    ),
                )
                return cur.fetchone()

    def list_entitlements(
        self,
        listener_id: UUID,
        *,
        now: datetime,
        edition_id: UUID,
        work_id: UUID,
    ) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM entitlements
                    WHERE listener_id = %s
                      AND status = 'active'
                      AND valid_from <= %s
                      AND (valid_until IS NULL OR valid_until > %s)
                      AND (
                        (scope_type = 'edition' AND scope_id = %s)
                        OR (scope_type = 'work' AND scope_id = %s)
                        OR scope_type = 'plan_catalog'
                      )
                    ORDER BY created_at
                    """,
                    (listener_id, now, now, str(edition_id), str(work_id)),
                )
                return list(cur.fetchall())

    def get_entitlement(self, entitlement_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM entitlements WHERE id = %s", (entitlement_id,)
                )
                return cur.fetchone()

    def revoke_entitlement(
        self, entitlement_id: UUID, *, reason: str = "revoked"
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE entitlements
                    SET status = 'revoked', revoked_at = now(), revocation_reason = %s
                    WHERE id = %s AND status IN ('pending','active','suspended')
                    RETURNING *
                    """,
                    (reason, entitlement_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise NotFoundError(
                        "entitlement not found or not revocable",
                        code="ENTITLEMENT_NOT_FOUND",
                    )
                self._enqueue(
                    cur,
                    aggregate_type="entitlement",
                    aggregate_id=str(entitlement_id),
                    event_type="entitlement.revoked",
                    payload={
                        "entitlement_id": str(entitlement_id),
                        "listener_id": str(row["listener_id"]),
                        "reason": reason,
                    },
                )
                return row


    # ------------------------------------------------------------------
    # Personal collections (Lot 1)
    # ------------------------------------------------------------------
    def create_personal_collection(
        self, listener_id: UUID, title: str, description: str = ""
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO personal_collections (id, listener_id, title, description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), listener_id, title, description),
                )
                return cur.fetchone()

    def list_personal_collections(self, listener_id: UUID) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.*,
                      (SELECT count(*) FROM personal_collection_items i
                        WHERE i.collection_id = c.id) AS item_count
                    FROM personal_collections c
                    WHERE c.listener_id = %s
                    ORDER BY c.created_at DESC
                    """,
                    (listener_id,),
                )
                return list(cur.fetchall())

    def get_personal_collection(
        self, listener_id: UUID, collection_id: UUID
    ) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM personal_collections
                    WHERE id = %s AND listener_id = %s
                    """,
                    (collection_id, listener_id),
                )
                collection = cur.fetchone()
                if collection is None:
                    return None
                cur.execute(
                    """
                    SELECT i.*, w.title AS work_title
                    FROM personal_collection_items i
                    JOIN works w ON w.id = i.work_id
                    WHERE i.collection_id = %s
                    ORDER BY i.position, i.added_at
                    """,
                    (collection_id,),
                )
                collection["items"] = list(cur.fetchall())
                return collection

    def add_personal_collection_item(
        self, listener_id: UUID, collection_id: UUID, work_id: UUID, position: int = 0
    ) -> dict | None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM personal_collections WHERE id = %s AND listener_id = %s",
                    (collection_id, listener_id),
                )
                if cur.fetchone() is None:
                    return None
                cur.execute(
                    """
                    INSERT INTO personal_collection_items
                      (collection_id, work_id, position)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (collection_id, work_id)
                    DO UPDATE SET position = EXCLUDED.position
                    RETURNING *
                    """,
                    (collection_id, work_id, position),
                )
                return cur.fetchone()

    def remove_personal_collection_item(
        self, listener_id: UUID, collection_id: UUID, work_id: UUID
    ) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM personal_collections WHERE id = %s AND listener_id = %s",
                    (collection_id, listener_id),
                )
                if cur.fetchone() is None:
                    return False
                cur.execute(
                    """
                    DELETE FROM personal_collection_items
                    WHERE collection_id = %s AND work_id = %s
                    """,
                    (collection_id, work_id),
                )
                return cur.rowcount == 1

    def delete_personal_collection(
        self, listener_id: UUID, collection_id: UUID
    ) -> bool:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM personal_collections
                    WHERE id = %s AND listener_id = %s
                    """,
                    (collection_id, listener_id),
                )
                return cur.rowcount == 1
