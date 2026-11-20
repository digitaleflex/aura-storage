"""Repository: Catalog."""
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


class CatalogRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------
    def create_contributor(self, name: str, sort_name: str = "") -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contributors (id, name, sort_name)
                    VALUES (%s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), name.strip(), sort_name.strip() or name.strip()),
                )
                return cur.fetchone()

    def link_contributor(
        self, work_id: UUID, contributor_id: UUID, role: str, position: int = 0
    ) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO work_contributors
                      (work_id, contributor_id, role, position)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (work_id, contributor_id, role)
                    DO UPDATE SET position = EXCLUDED.position
                    """,
                    (work_id, contributor_id, role, position),
                )

    def create_work(
        self,
        title: str,
        language: str,
        description: str = "",
        publication_year: int | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO works
                      (id, title, language, description, publication_year)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), title.strip(), language.strip(), description, publication_year),
                )
                return cur.fetchone()

    def get_work(self, work_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM works WHERE id = %s", (work_id,))
                return cur.fetchone()

    def set_work_status(self, work_id: UUID, status: str) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE works SET status = %s, updated_at = now()
                    WHERE id = %s RETURNING *
                    """,
                    (status, work_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise NotFoundError("work not found", code="WORK_NOT_FOUND")
                return row

    def get_contributors(self, work_id: UUID) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.name, c.sort_name, wc.role, wc.position
                    FROM work_contributors wc
                    JOIN contributors c ON c.id = wc.contributor_id
                    WHERE wc.work_id = %s
                    ORDER BY wc.role, wc.position, c.name
                    """,
                    (work_id,),
                )
                return list(cur.fetchall())

    def create_asset(
        self,
        storage_object_id: str,
        *,
        kind: str = "source",
        content_type: str = "",
        size_bytes: int = -1,
        checksum_sha256: str = "",
        duration_ms: int | None = None,
        codec: str = "",
        status: str = "ready",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO assets
                      (id, storage_object_id, kind, content_type, size_bytes,
                       checksum_sha256, duration_ms, codec, status, ready_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s = 'ready' THEN now() ELSE NULL END)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        storage_object_id,
                        kind,
                        content_type,
                        size_bytes,
                        checksum_sha256,
                        duration_ms,
                        codec,
                        status,
                        status,
                    ),
                )
                return cur.fetchone()

    def mark_asset_ready(self, asset_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE assets SET status = 'ready',
                      ready_at = COALESCE(ready_at, now())
                    WHERE id = %s RETURNING *
                    """,
                    (asset_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise NotFoundError("asset not found", code="ASSET_NOT_FOUND")
                return row

    def create_edition(
        self,
        work_id: UUID,
        *,
        title: str,
        language: str,
        slug: str,
        description: str,
        duration_ms: int,
        publisher: str = "",
        publication_date=None,
        cover_asset_id: UUID | None = None,
        access_model: str = "free",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO editions
                      (id, work_id, title, language, publisher, publication_date,
                       description, slug, duration_ms, cover_asset_id, access_model)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        work_id,
                        title.strip(),
                        language.strip(),
                        publisher,
                        publication_date,
                        description,
                        slug,
                        duration_ms,
                        cover_asset_id,
                        access_model,
                    ),
                )
                return cur.fetchone()

    def create_track(
        self,
        edition_id: UUID,
        *,
        position: int,
        title: str,
        start_ms: int,
        end_ms: int,
        asset_id: UUID | None,
        status: str = "ready",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tracks
                      (id, edition_id, position, title, start_ms, end_ms, asset_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), edition_id, position, title, start_ms, end_ms, asset_id, status),
                )
                return cur.fetchone()

    def create_chapter(
        self,
        edition_id: UUID,
        *,
        position: int,
        title: str,
        start_ms: int,
        end_ms: int,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chapters
                      (id, edition_id, position, title, start_ms, end_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), edition_id, position, title, start_ms, end_ms),
                )
                return cur.fetchone()

    def create_rights_window(
        self,
        edition_id: UUID,
        *,
        starts_at: datetime,
        ends_at: datetime,
        territory_code: str = "WORLD",
        channel: str = "stream",
        status: str = "active",
        contract_id: UUID | None = None,
        max_downloads: int | None = None,
        allowed_formats: list[str] | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rights_windows
                      (id, edition_id, contract_id, territory_code, channel,
                       starts_at, ends_at, status, max_downloads, allowed_formats)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        edition_id,
                        contract_id,
                        territory_code,
                        channel,
                        starts_at,
                        ends_at,
                        status,
                        max_downloads,
                        allowed_formats,
                    ),
                )
                return cur.fetchone()

    def get_edition(self, edition_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, w.title AS work_title, w.language AS work_language,
                           w.status AS work_status, w.description AS work_description
                    FROM editions e JOIN works w ON w.id = e.work_id
                    WHERE e.id = %s
                    """,
                    (edition_id,),
                )
                return cur.fetchone()

    def get_edition_by_slug(self, slug: str) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, w.title AS work_title, w.language AS work_language,
                           w.status AS work_status, w.description AS work_description
                    FROM editions e JOIN works w ON w.id = e.work_id
                    WHERE e.slug = %s
                    """,
                    (slug,),
                )
                return cur.fetchone()

    def get_edition_bundle(self, edition_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, w.title AS work_title, w.language AS work_language,
                           w.status AS work_status, w.description AS work_description
                    FROM editions e JOIN works w ON w.id = e.work_id
                    WHERE e.id = %s
                    """,
                    (edition_id,),
                )
                edition = cur.fetchone()
                if edition is None:
                    return None
                cur.execute(
                    """
                    SELECT c.id, c.name, c.sort_name, wc.role, wc.position
                    FROM work_contributors wc
                    JOIN contributors c ON c.id = wc.contributor_id
                    WHERE wc.work_id = %s
                    ORDER BY wc.role, wc.position, c.name
                    """,
                    (edition["work_id"],),
                )
                contributors = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT t.*, a.status AS asset_status, a.storage_object_id,
                           a.content_type, a.size_bytes, a.checksum_sha256,
                           a.duration_ms AS asset_duration_ms
                    FROM tracks t
                    LEFT JOIN assets a ON a.id = t.asset_id
                    WHERE t.edition_id = %s
                    ORDER BY t.position
                    """,
                    (edition_id,),
                )
                tracks = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT * FROM chapters WHERE edition_id = %s ORDER BY position
                    """,
                    (edition_id,),
                )
                chapters = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT * FROM rights_windows
                    WHERE edition_id = %s ORDER BY starts_at
                    """,
                    (edition_id,),
                )
                rights = list(cur.fetchall())
                return {
                    "edition": edition,
                    "contributors": contributors,
                    "tracks": tracks,
                    "chapters": chapters,
                    "rights": rights,
                }

    def publish_edition(self, edition_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE editions
                    SET status = 'published', published_at = now(),
                        updated_at = now(), version = version + 1
                    WHERE id = %s
                      AND status IN ('draft','metadata_complete','assets_pending','validation','approved')
                    RETURNING *
                    """,
                    (edition_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ConflictError(
                        "edition cannot be published from its current state",
                        code="EDITION_STATE_CONFLICT",
                    )
                self._enqueue(
                    cur,
                    aggregate_type="edition",
                    aggregate_id=str(edition_id),
                    event_type="catalog.edition.published",
                    payload={
                        "edition_id": str(edition_id),
                        "work_id": str(row["work_id"]),
                        "published_at": row["published_at"],
                    },
                )
                return row

    def list_catalog(
        self, *, language: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                if language:
                    cur.execute(
                        """
                        SELECT e.*, w.title AS work_title, w.language AS work_language,
                               w.status AS work_status,
                               (SELECT count(*) FROM tracks t WHERE t.edition_id = e.id)
                                 AS track_count,
                               (SELECT count(*) FROM tracks t
                                  JOIN assets a ON a.id = t.asset_id
                                  WHERE t.edition_id = e.id
                                    AND t.status = 'ready' AND a.status = 'ready')
                                 AS ready_track_count
                        FROM editions e JOIN works w ON w.id = e.work_id
                        WHERE e.status = 'published' AND e.language = %s
                        ORDER BY e.published_at DESC NULLS LAST, e.id
                        LIMIT %s OFFSET %s
                        """,
                        (language, limit, offset),
                    )
                else:
                    cur.execute(
                        """
                        SELECT e.*, w.title AS work_title, w.language AS work_language,
                               w.status AS work_status,
                               (SELECT count(*) FROM tracks t WHERE t.edition_id = e.id)
                                 AS track_count,
                               (SELECT count(*) FROM tracks t
                                  JOIN assets a ON a.id = t.asset_id
                                  WHERE t.edition_id = e.id
                                    AND t.status = 'ready' AND a.status = 'ready')
                                 AS ready_track_count
                        FROM editions e JOIN works w ON w.id = e.work_id
                        WHERE e.status = 'published'
                        ORDER BY e.published_at DESC NULLS LAST, e.id
                        LIMIT %s OFFSET %s
                        """,
                        (limit, offset),
                    )
                return list(cur.fetchall())

    def latest_published_edition(self, work_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM editions
                    WHERE work_id = %s AND status = 'published'
                    ORDER BY published_at DESC NULLS LAST, id
                    LIMIT 1
                    """,
                    (work_id,),
                )
                return cur.fetchone()


    # ------------------------------------------------------------------
    # Catalog completion (Lot 1): suspension, categories, editorial collections
    # ------------------------------------------------------------------
    def suspend_edition(self, edition_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE editions
                    SET status = 'suspended', suspended_at = now(), updated_at = now(),
                        version = version + 1
                    WHERE id = %s AND status = 'published'
                    RETURNING *
                    """,
                    (edition_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ConflictError(
                        "edition cannot be suspended from its current state",
                        code="EDITION_STATE_CONFLICT",
                    )
                self._enqueue(
                    cur,
                    aggregate_type="edition",
                    aggregate_id=str(edition_id),
                    event_type="catalog.edition.suspended",
                    payload={"edition_id": str(edition_id)},
                )
                return row

    def unsuspend_edition(self, edition_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE editions
                    SET status = 'published', suspended_at = NULL, updated_at = now(),
                        version = version + 1
                    WHERE id = %s AND status = 'suspended'
                    RETURNING *
                    """,
                    (edition_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ConflictError(
                        "edition cannot be unsuspended from its current state",
                        code="EDITION_STATE_CONFLICT",
                    )
                self._enqueue(
                    cur,
                    aggregate_type="edition",
                    aggregate_id=str(edition_id),
                    event_type="catalog.edition.unsuspended",
                    payload={"edition_id": str(edition_id)},
                )
                return row

    def create_contract(
        self,
        *,
        name: str,
        licensor: str = "",
        territory_scope: str = "WORLD",
        starts_at: datetime,
        ends_at: datetime,
        status: str = "draft",
        notes: str = "",
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contracts
                      (id, name, licensor, territory_scope, starts_at, ends_at, status, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        name,
                        licensor,
                        territory_scope,
                        starts_at,
                        ends_at,
                        status,
                        notes,
                    ),
                )
                return cur.fetchone()

    def list_contracts(self) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM contracts ORDER BY created_at DESC"
                )
                return list(cur.fetchall())

    def get_contract(self, contract_id: UUID) -> dict | None:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM contracts WHERE id = %s", (contract_id,)
                )
                return cur.fetchone()

    def create_category(self, slug: str, name: str, description: str = "") -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO categories (id, slug, name, description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), slug, name, description),
                )
                return cur.fetchone()

    def list_categories(self) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM categories ORDER BY name")
                return list(cur.fetchall())

    def link_work_category(
        self, work_id: UUID, category_id: UUID, position: int = 0
    ) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO work_categories (work_id, category_id, position)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (work_id, category_id)
                    DO UPDATE SET position = EXCLUDED.position
                    """,
                    (work_id, category_id, position),
                )

    def create_editorial_collection(
        self, slug: str, title: str, description: str = ""
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO editorial_collections (id, slug, title, description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id(), slug, title, description),
                )
                return cur.fetchone()

    def add_editorial_collection_item(
        self, collection_id: UUID, edition_id: UUID, position: int = 0
    ) -> None:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO editorial_collection_items
                      (collection_id, edition_id, position)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (collection_id, edition_id)
                    DO UPDATE SET position = EXCLUDED.position
                    """,
                    (collection_id, edition_id, position),
                )

    def publish_editorial_collection(self, collection_id: UUID) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE editorial_collections
                    SET status = 'published', published_at = now(), updated_at = now()
                    WHERE id = %s AND status IN ('draft', 'archived')
                    RETURNING *
                    """,
                    (collection_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ConflictError(
                        "editorial collection cannot be published",
                        code="COLLECTION_STATE_CONFLICT",
                    )
                return row

    def list_editorial_collections(self, *, published_only: bool = False) -> list[dict]:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                if published_only:
                    cur.execute(
                        """
                        SELECT * FROM editorial_collections
                        WHERE status = 'published'
                        ORDER BY published_at DESC NULLS LAST, title
                        """
                    )
                else:
                    cur.execute(
                        "SELECT * FROM editorial_collections ORDER BY created_at DESC"
                    )
                return list(cur.fetchall())
