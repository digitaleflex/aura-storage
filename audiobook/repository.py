"""Persistence layer. SQL only; business decisions live in ``domain.py``."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .db import Database
from .domain import (
    ApplyResult,
    PlaybackEvent,
    PlaybackSessionState,
    ProgressState,
    apply_event,
)
from .errors import ConflictError, NotFoundError
from .ids import new_id, normalize_email


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


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

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
                           l.locale, l.timezone
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
        max_downloads: int | None = None,
        allowed_formats: list[str] | None = None,
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rights_windows
                      (id, edition_id, territory_code, channel, starts_at, ends_at,
                       status, max_downloads, allowed_formats)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        new_id(),
                        edition_id,
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
    ) -> dict:
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
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

    def _enqueue(
        self,
        cur,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        cur.execute(
            """
            INSERT INTO outbox_events
              (aggregate_type, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (aggregate_type, aggregate_id, event_type, Jsonb(_jsonable(payload))),
        )
