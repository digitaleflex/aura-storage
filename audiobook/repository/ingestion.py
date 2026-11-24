"""Repository: staged ingest items and their idempotent transitions."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..errors import ConflictError, NotFoundError
from ..ids import new_id
from .base import BaseRepository


def _public_item(row: dict) -> dict:
    """Never expose an internal staging path through an API response."""
    hidden = {"staging_path"}
    return {key: value for key, value in row.items() if key not in hidden}


class IngestRepository(BaseRepository):
    def create_ingest_batch(self, *, source: str, label: str = "") -> dict:
        batch_id = new_id()
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingest_batches (id, source, label)
                    VALUES (%s, %s, %s)
                    """,
                    (batch_id, source, label[:300]),
                )
        return {"id": str(batch_id), "source": source, "label": label[:300]}

    def create_ingest_item(
        self,
        *,
        source: str,
        source_ref: str,
        original_filename: str,
        staging_path: str,
        declared_content_type: str,
        detected_content_type: str,
        size_bytes: int,
        sha256: str,
        kind: str,
        idempotency_key: str,
        batch_id: UUID | None,
        target_edition_id: UUID | None,
        track_position: int | None,
        track_title: str,
        duration_ms: int | None,
        request_id: str,
    ) -> tuple[dict, bool]:
        item_id = new_id()
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingest_items
                      (id, batch_id, source, source_ref, original_filename, staging_path,
                       declared_content_type, detected_content_type, size_bytes, sha256,
                       kind, state, idempotency_key, target_edition_id, track_position,
                       track_title, duration_ms, request_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'validating',
                            %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING *
                    """,
                    (
                        item_id,
                        batch_id,
                        source,
                        source_ref[:200],
                        original_filename[:255],
                        staging_path,
                        declared_content_type[:200],
                        detected_content_type[:200],
                        size_bytes,
                        sha256,
                        kind,
                        idempotency_key,
                        target_edition_id,
                        track_position,
                        track_title[:500],
                        duration_ms,
                        request_id,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    return _public_item(dict(row)), True
                cur.execute(
                    "SELECT * FROM ingest_items WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                existing = cur.fetchone()
        if existing is None:
            raise ConflictError("ingest item could not be created", code="INGEST_CREATE_FAILED")
        return _public_item(dict(existing)), False

    def get_ingest_item(self, item_id: UUID) -> dict:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ingest_items WHERE id = %s", (item_id,))
                row = cur.fetchone()
        if row is None:
            raise NotFoundError("ingest item not found", code="INGEST_NOT_FOUND")
        return _public_item(dict(row))

    def list_ingest_items(self, *, limit: int = 50, state: str = "") -> list[dict]:
        where = ""
        values: list[Any] = []
        if state:
            where = "WHERE state = %s"
            values.append(state)
        values.append(max(1, min(limit, 200)))
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM ingest_items {where} ORDER BY created_at DESC LIMIT %s",
                    tuple(values),
                )
                return [_public_item(dict(row)) for row in cur.fetchall()]

    def transition_ingest_item(
        self,
        item_id: UUID,
        *,
        to_state: str,
        from_states: tuple[str, ...] | None = None,
        error_code: str = "",
        increment_attempts: bool = False,
        storage_object_id: str | None = None,
        asset_id: UUID | None = None,
        duration_ms: int | None = None,
    ) -> dict:
        assignments = ["state = %s", "updated_at = now()"]
        values: list[Any] = [to_state]
        if error_code or to_state in {"completed", "rejected"}:
            assignments.append("error_code = %s")
            values.append(error_code[:200])
        if increment_attempts:
            assignments.append("attempts = attempts + 1")
        if storage_object_id is not None:
            assignments.append("storage_object_id = %s")
            values.append(storage_object_id)
        if asset_id is not None:
            assignments.append("asset_id = %s")
            values.append(asset_id)
        if duration_ms is not None:
            assignments.append("duration_ms = %s")
            values.append(duration_ms)
        if to_state == "completed":
            assignments.append("completed_at = now()")
        where = "id = %s"
        values.append(item_id)
        if from_states:
            where += " AND state = ANY(%s)"
            values.append(list(from_states))
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE ingest_items SET {', '.join(assignments)} "
                    f"WHERE {where} RETURNING *",
                    tuple(values),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute("SELECT state FROM ingest_items WHERE id = %s", (item_id,))
                    current = cur.fetchone()
                    if current is None:
                        raise NotFoundError("ingest item not found", code="INGEST_NOT_FOUND")
                    raise ConflictError(
                        f"ingest item is {current['state']}, not importable",
                        code="INGEST_STATE_CONFLICT",
                    )
        return _public_item(dict(row))

    def list_retryable_ingest_items(
        self, *, not_updated_since: datetime, max_attempts: int, limit: int = 20
    ) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ingest_items
                    WHERE state = 'retryable_failed'
                      AND attempts < %s
                      AND updated_at <= %s
                    ORDER BY updated_at, id
                    LIMIT %s
                    """,
                    (max_attempts, not_updated_since, max(1, min(limit, 100))),
                )
                return [_public_item(dict(row)) for row in cur.fetchall()]

    def list_stale_importing_items(
        self, *, older_than: datetime, limit: int = 20
    ) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ingest_items
                    WHERE state = 'importing' AND updated_at < %s
                    ORDER BY updated_at, id
                    LIMIT %s
                    """,
                    (older_than, max(1, min(limit, 100))),
                )
                return [_public_item(dict(row)) for row in cur.fetchall()]

    def find_asset_by_storage_object_id(self, storage_object_id: str) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM assets WHERE storage_object_id = %s",
                    (storage_object_id,),
                )
                row = cur.fetchone()
        return dict(row) if row is not None else None

    def internal_path(self, item_id: UUID) -> str:
        """For the ingestion service only; never returned by public methods."""
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT staging_path FROM ingest_items WHERE id = %s", (item_id,))
                row = cur.fetchone()
        if row is None:
            raise NotFoundError("ingest item not found", code="INGEST_NOT_FOUND")
        return str(row["staging_path"])

    def item_creation_time(self, item_id: UUID) -> datetime:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT created_at FROM ingest_items WHERE id = %s", (item_id,))
                row = cur.fetchone()
        if row is None:
            raise NotFoundError("ingest item not found", code="INGEST_NOT_FOUND")
        return row["created_at"]
