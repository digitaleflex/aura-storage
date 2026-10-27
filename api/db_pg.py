"""PostgreSQL catalogue implementing the same Repository interface as db.py (#19)."""
import threading
import time
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from . import ids
from .auth import new_token, session_key
from .dblock import synchronized
from .migrations import (
    DEFAULT_APPLICATION_NAME,
    DEFAULT_ENVIRONMENT,
    DEFAULT_SPACE_NAME,
    apply_migrations,
)
from .object_query import build_object_where, order_clause

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


@synchronized
class Repository:
    dialect = "postgres"

    def __init__(self, dsn: str):
        # psycopg connections are not thread-safe and FastAPI runs sync endpoints
        # in a threadpool, so `_lock` serializes access; see api/dblock.py.
        self._lock = threading.RLock()
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA)
        apply_migrations(self.conn, "postgres")

    def now(self) -> int:
        return int(time.time())

    def new_id(self) -> str:
        return ids.new_id()

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _run(self, sql: str, params: tuple = ()) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def _run_many(self, sql: str, params_seq) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(sql, params_seq)

    # -- users ------------------------------------------------------------
    def get_user_by_name(self, username: str) -> Optional[dict]:
        return self._one("SELECT * FROM users WHERE username = %s", (username,))

    def get_user(self, uid: str) -> Optional[dict]:
        return self._one("SELECT * FROM users WHERE id = %s", (uid,))

    def create_user(
        self, username: str, pass_hash: str, role: str = "user",
        space_id: Optional[str] = None, application_id: Optional[str] = None,
    ) -> str:
        uid = self.new_id()
        application_id, space_id = self.default_scope(application_id, space_id)
        self._run(
            "INSERT INTO users (id, username, pass_hash, created_at, role, "
            "application_id, space_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (uid, username, pass_hash, self.now(), role, application_id, space_id),
        )
        return uid

    def ensure_admin(self, uid: str) -> None:
        application_id, space_id = self.default_scope()
        self._run("UPDATE users SET role = 'admin' WHERE id = %s", (uid,))
        self._run(
            "UPDATE users SET application_id = %s WHERE id = %s AND application_id IS NULL",
            (application_id, uid),
        )
        self._run(
            "UPDATE users SET space_id = %s WHERE id = %s AND space_id IS NULL",
            (space_id, uid),
        )

    # -- default tenant ---------------------------------------------------
    def get_default_space(self, application_id: str) -> Optional[dict]:
        """The seeded default space of ``application_id`` (name + environment)."""
        return self._one(
            "SELECT * FROM spaces WHERE application_id = %s AND name = %s "
            "AND environment = %s ORDER BY created_at LIMIT 1",
            (application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT),
        )

    def default_scope(
        self,
        application_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve the seeded default application/space ids for a new row.

        Ids are generated UUID v4 values, not constants, so they are looked up by
        the seed names (``aura`` / ``default`` / ``prod``) and only used to fill a
        missing argument. Either element stays ``None`` if the seed row is absent.
        """
        if not application_id:
            application = self.get_application_by_name(DEFAULT_APPLICATION_NAME)
            application_id = application["id"] if application else None
        if not space_id and application_id:
            space = self.get_default_space(application_id)
            space_id = space["id"] if space else None
        return application_id, space_id

    # -- sessions ---------------------------------------------------------
    def create_session(self, user_id: str, csrf: str, expires_at: int) -> str:
        """Create a session and return its opaque cookie token.

        Only ``session_key(token)`` is stored (row ``id``); the clear token
        exists solely in the returned value and the client cookie. Expired rows
        are pruned here so the table cannot grow without bound.
        """
        token = new_token(32)
        self._run("DELETE FROM sessions WHERE expires_at <= %s", (self.now(),))
        self._run(
            "INSERT INTO sessions (id, user_id, csrf, expires_at) VALUES (%s, %s, %s, %s)",
            (session_key(token), user_id, csrf, expires_at),
        )
        return token

    def get_session(self, token: str) -> Optional[dict]:
        """Look a session up by its cookie token (hashed before the query)."""
        return self._one(
            "SELECT * FROM sessions WHERE id = %s AND expires_at > %s",
            (session_key(token), self.now()),
        )

    def revoke_sessions_beyond(self, max_expires_at: int) -> int:
        """PostgreSQL twin of ``SqliteRepository.revoke_sessions_beyond``."""
        return self._run(
            "DELETE FROM sessions WHERE expires_at > %s", (max_expires_at,)
        )

    def delete_session(self, sid: str) -> None:
        """Delete by stored row id (``session["id"]``, i.e. the digest)."""
        self._run("DELETE FROM sessions WHERE id = %s", (sid,))

    def set_session_master(self, sid: str, until: Optional[int]) -> None:
        """Grant (epoch seconds) or end (None) master mode on one session."""
        self._run("UPDATE sessions SET master_until = %s WHERE id = %s", (until, sid))

    # -- applications / spaces / buckets (#35) ----------------------------
    def create_application(self, name: str) -> str:
        aid = self.new_id()
        self._run(
            "INSERT INTO applications (id, name, status, created_at) VALUES (%s, %s, 'active', %s)",
            (aid, name, self.now()),
        )
        return aid

    def get_application(self, aid: str) -> Optional[dict]:
        return self._one("SELECT * FROM applications WHERE id = %s", (aid,))

    def get_application_by_name(self, name: str) -> Optional[dict]:
        return self._one("SELECT * FROM applications WHERE name = %s", (name,))

    def list_applications(self) -> list:
        return self._all("SELECT * FROM applications ORDER BY created_at")

    def application_name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        sql = "SELECT 1 AS x FROM applications WHERE name = %s"
        params: list = [name]
        if exclude_id is not None:
            sql += " AND id != %s"
            params.append(exclude_id)
        return self._one(sql, tuple(params)) is not None

    def update_application(
        self, aid: str, *, name: Optional[str] = None, status: Optional[str] = None
    ) -> None:
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        if not sets:
            return
        params.append(aid)
        self._run(f"UPDATE applications SET {', '.join(sets)} WHERE id = %s", tuple(params))

    def count_spaces_for_application(self, aid: str) -> int:
        return int(self._one(
            "SELECT COUNT(*) AS n FROM spaces WHERE application_id = %s", (aid,)
        )["n"])

    def create_space(self, application_id: str, name: str, environment: str) -> str:
        sid = self.new_id()
        self._run(
            "INSERT INTO spaces (id, application_id, name, environment, status, "
            "created_at) VALUES (%s, %s, %s, %s, 'active', %s)",
            (sid, application_id, name, environment, self.now()),
        )
        return sid

    def get_space(self, sid: str) -> Optional[dict]:
        return self._one("SELECT * FROM spaces WHERE id = %s", (sid,))

    def list_spaces(self, application_id: Optional[str] = None) -> list:
        if application_id:
            return self._all(
                "SELECT * FROM spaces WHERE application_id = %s ORDER BY created_at",
                (application_id,),
            )
        return self._all("SELECT * FROM spaces ORDER BY created_at")

    def space_exists(
        self, application_id: str, name: str, environment: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        sql = (
            "SELECT 1 AS x FROM spaces WHERE application_id = %s AND name = %s "
            "AND environment = %s"
        )
        params: list = [application_id, name, environment]
        if exclude_id is not None:
            sql += " AND id != %s"
            params.append(exclude_id)
        return self._one(sql, tuple(params)) is not None

    def update_space(
        self, sid: str, *, name: Optional[str] = None,
        environment: Optional[str] = None, status: Optional[str] = None,
    ) -> None:
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if environment is not None:
            sets.append("environment = %s")
            params.append(environment)
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        if not sets:
            return
        params.append(sid)
        self._run(f"UPDATE spaces SET {', '.join(sets)} WHERE id = %s", tuple(params))

    def space_counts(self, sid: str) -> dict:
        def count(sql: str) -> int:
            return int(self._one(sql, (sid,))["n"])

        return {
            "buckets": count("SELECT COUNT(*) AS n FROM buckets WHERE space_id = %s"),
            "identities": count(
                "SELECT COUNT(*) AS n FROM service_identities WHERE space_id = %s"
            ),
            "objects": count("SELECT COUNT(*) AS n FROM objects WHERE space_id = %s"),
        }

    def create_bucket(self, space_id: str, name: str, is_default: bool = False) -> str:
        bid = self.new_id()
        self._run(
            "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (bid, space_id, name, 1 if is_default else 0, self.now()),
        )
        return bid

    def get_bucket_for_space(self, space_id: str, name: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM buckets WHERE space_id = %s AND name = %s", (space_id, name)
        )

    def get_default_bucket(self, space_id: str) -> Optional[dict]:
        # Strict default only (M06): see api/db.py.
        return self._one(
            "SELECT * FROM buckets WHERE space_id = %s AND is_default = 1 "
            "ORDER BY created_at ASC LIMIT 1",
            (space_id,),
        )

    def get_bucket_by_name(self, name: str) -> Optional[dict]:
        return self._one("SELECT * FROM buckets WHERE name = %s", (name,))

    def get_bucket(self, bid: str) -> Optional[dict]:
        return self._one("SELECT * FROM buckets WHERE id = %s", (bid,))

    def list_buckets(self, space_id: str) -> list:
        return self._all(
            "SELECT * FROM buckets WHERE space_id = %s ORDER BY created_at", (space_id,)
        )

    def has_object(self, bucket: str, object_key: str) -> bool:
        row = self._one(
            "SELECT 1 AS x FROM objects WHERE bucket = %s AND object_key = %s LIMIT 1",
            (bucket, object_key),
        )
        return row is not None

    def list_all_buckets(self) -> list:
        # Every registered bucket, oldest first; the API joins space/application
        # names so a bucket is never shown without its attachment (#M04).
        return self._all("SELECT * FROM buckets ORDER BY created_at, name")

    def set_default_bucket(self, space_id: str, bid: str, is_default: bool = True) -> None:
        # Exactly one default per space: clear the flag on the space's other
        # buckets, then set it on the target (scoped to the same space).
        if is_default:
            self._run("UPDATE buckets SET is_default = 0 WHERE space_id = %s", (space_id,))
            self._run(
                "UPDATE buckets SET is_default = 1 WHERE id = %s AND space_id = %s",
                (bid, space_id),
            )
        else:
            self._run(
                "UPDATE buckets SET is_default = 0 WHERE id = %s AND space_id = %s",
                (bid, space_id),
            )

    # -- service identities (#38) -----------------------------------------
    def create_identity(
        self, iid: str, application_id: str, space_id: str, name: str,
        secret_hash: str, scopes: str, expires_at: Optional[int] = None,
    ) -> str:
        self._run(
            "INSERT INTO service_identities (id, application_id, space_id, name, "
            "secret_hash, scopes, created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (iid, application_id, space_id, name, secret_hash, scopes, self.now(), expires_at),
        )
        return iid

    def get_identity(self, iid: str) -> Optional[dict]:
        return self._one("SELECT * FROM service_identities WHERE id = %s", (iid,))

    def list_identities(self, space_id: Optional[str] = None) -> list:
        if space_id:
            return self._all(
                "SELECT * FROM service_identities WHERE space_id = %s ORDER BY created_at",
                (space_id,),
            )
        return self._all("SELECT * FROM service_identities ORDER BY created_at")

    def update_identity_secret(self, iid: str, secret_hash: str) -> None:
        self._run(
            "UPDATE service_identities SET secret_hash = %s, rotated_at = %s WHERE id = %s",
            (secret_hash, self.now(), iid),
        )

    # -- partner integrations -------------------------------------------
    _PARTNER_SELECT = (
        "SELECT p.*, i.name AS identity_name, i.scopes AS identity_scopes, "
        "i.expires_at AS identity_expires_at, i.last_used_at AS identity_last_used_at, "
        "i.revoked_at AS identity_revoked_at, i.rotated_at AS identity_rotated_at "
        "FROM partner_sites p JOIN service_identities i ON i.id = p.identity_id "
    )

    def create_partner_site(
        self, pid: str, space_id: str, identity_id: str, name: str, site_url: str,
        default_ttl_seconds: Optional[int], notes: str, created_by: Optional[str],
    ) -> str:
        now = self.now()
        self._run(
            "INSERT INTO partner_sites (id, space_id, identity_id, name, site_url, "
            "default_ttl_seconds, notes, created_by, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (pid, space_id, identity_id, name, site_url, default_ttl_seconds,
             notes, created_by, now, now),
        )
        return pid

    def list_partner_sites(self) -> list:
        return self._all(self._PARTNER_SELECT + "ORDER BY p.created_at")

    def get_partner_site(self, pid: str) -> Optional[dict]:
        return self._one(self._PARTNER_SELECT + "WHERE p.id = %s", (pid,))

    def update_partner_site(
        self, pid: str, name: str, site_url: str,
        default_ttl_seconds: Optional[int], notes: str,
    ) -> None:
        self._run(
            "UPDATE partner_sites SET name = %s, site_url = %s, "
            "default_ttl_seconds = %s, notes = %s, updated_at = %s WHERE id = %s",
            (name, site_url, default_ttl_seconds, notes, self.now(), pid),
        )

    def delete_partner_site(self, pid: str) -> None:
        self._run("DELETE FROM partner_sites WHERE id = %s", (pid,))

    def revoke_identity(self, iid: str) -> None:
        self._run(
            "UPDATE service_identities SET revoked_at = %s WHERE id = %s",
            (self.now(), iid),
        )

    def touch_identity(self, iid: str, ts: int) -> None:
        self._run(
            "UPDATE service_identities SET last_used_at = %s WHERE id = %s", (ts, iid)
        )

    # -- object shares ----------------------------------------------------
    def create_share(
        self, object_id: str, space_id: str, created_by: str,
        created_by_kind: str, token_hash: str, expires_at: int,
        content_disposition: str = "attachment",
        max_uses: Optional[int] = None,
    ) -> str:
        sid = self.new_id()
        self._run(
            "INSERT INTO object_shares (id, object_id, space_id, created_by, "
            "created_by_kind, token_hash, content_disposition, expires_at, "
            "max_uses, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (sid, object_id, space_id, created_by, created_by_kind, token_hash,
             content_disposition, expires_at, max_uses, self.now()),
        )
        return sid

    def get_share(self, sid: str) -> Optional[dict]:
        return self._one("SELECT * FROM object_shares WHERE id = %s", (sid,))

    def get_share_by_token_hash(self, token_hash: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM object_shares WHERE token_hash = %s", (token_hash,)
        )

    def list_shares(self, object_id: str) -> list:
        return self._all(
            "SELECT * FROM object_shares WHERE object_id = %s "
            "ORDER BY created_at DESC, id",
            (object_id,),
        )

    # -- content revisions (docs/CONTENT-REVISIONS.md, phase 1) ---------------
    # PostgreSQL twin of the SqliteRepository methods: identical signatures and
    # identical results. Persistence only — nothing calls these from the API yet.
    def create_revision(
        self, object_id: str, revision_number: int, bucket: str,
        storage_key: str, size_bytes: int, checksum_sha256: str,
        content_type: str, created_by_id: Optional[str] = None,
        created_by_kind: Optional[str] = None, keep_forever: bool = False,
    ) -> str:
        rid = self.new_id()
        self._run(
            "INSERT INTO object_revisions (id, object_id, revision_number, bucket, "
            "storage_key, size_bytes, checksum_sha256, content_type, created_at, "
            "created_by_id, created_by_kind, keep_forever) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (rid, object_id, revision_number, bucket, storage_key, size_bytes,
             checksum_sha256, content_type, self.now(), created_by_id,
             created_by_kind, 1 if keep_forever else 0),
        )
        return rid

    def list_revisions(self, object_id: str) -> list:
        return self._all(
            "SELECT * FROM object_revisions WHERE object_id = %s "
            "ORDER BY revision_number DESC",
            (object_id,),
        )

    def get_revision(self, object_id: str, revision_id: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM object_revisions WHERE object_id = %s AND id = %s",
            (object_id, revision_id),
        )

    def delete_revision(self, revision_id: str) -> int:
        return self._run("DELETE FROM object_revisions WHERE id = %s", (revision_id,))

    def set_revision_keep_forever(self, revision_id: str, keep: bool) -> int:
        return self._run(
            "UPDATE object_revisions SET keep_forever = %s WHERE id = %s",
            (1 if keep else 0, revision_id),
        )

    def count_keep_forever(self, owner_id: str) -> int:
        """Revisions pinned by one owner, across all their objects (per-user cap)."""
        row = self._one(
            "SELECT COUNT(*) AS n FROM object_revisions r "
            "JOIN objects o ON o.id = r.object_id "
            "WHERE o.owner_id = %s AND r.keep_forever = 1",
            (owner_id,),
        )
        return int(row["n"]) if row else 0

    def consume_share(self, sid: str, now: int) -> bool:
        # See api/db.py: the guard is part of the UPDATE so a last use cannot be
        # redeemed twice by concurrent requests.
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE object_shares SET use_count = use_count + 1, "
                "last_used_at = %s WHERE id = %s AND revoked_at IS NULL "
                "AND expires_at > %s "
                "AND (max_uses IS NULL OR use_count < max_uses)",
                (now, sid, now),
            )
            return cur.rowcount == 1

    def revoke_share(self, sid: str, now: int) -> None:
        self._run(
            "UPDATE object_shares SET revoked_at = %s "
            "WHERE id = %s AND revoked_at IS NULL",
            (now, sid),
        )

    def delete_shares_for_object(self, object_id: str) -> None:
        self._run("DELETE FROM object_shares WHERE object_id = %s", (object_id,))

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, *, space_id: str, application_id: Optional[str], environment: Optional[str],
        bucket: str, object_key: str, display_name: str, content_type: str,
        owner_id: Optional[str], actor_id: str, actor_kind: str,
        intent_expires_at: Optional[int], folder_id: Optional[str] = None,
        expected_size_bytes: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        content_encoding: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self._run(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at, actor_kind, actor_id, application_id, space_id,
               environment, intent_expires_at, expected_size_bytes, idempotency_key,
               content_encoding)
               VALUES (%s, %s, %s, %s, %s, -1, '', %s, %s, 'private', 'pending', %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (oid, bucket, object_key, display_name, content_type, folder_id, owner_id,
             now, now, actor_kind, actor_id, application_id, space_id, environment,
             intent_expires_at, expected_size_bytes, idempotency_key, content_encoding),
        )
        return oid

    def get_object(self, oid: str, *, space_id: str, owner_id: Optional[str] = None):
        sql = "SELECT * FROM objects WHERE id = %s AND space_id = %s"
        params = [oid, space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
        return self._one(sql, tuple(params))

    def get_object_by_slug(self, slug: str):
        return self._one(
            "SELECT * FROM objects WHERE public_slug = %s", (slug,)
        )

    def set_object_publication(
        self, oid: str, slug: Optional[str], published_at: Optional[int],
    ) -> None:
        self._run(
            "UPDATE objects SET public_slug = %s, published_at = %s, "
            "version = version + 1, updated_at = %s WHERE id = %s",
            (slug, published_at, self.now(), oid),
        )

    def set_object_thumbnail(
        self, oid: str, thumbnail_key: Optional[str],
        duration_seconds: Optional[float],
    ) -> None:
        self._run(
            "UPDATE objects SET thumbnail_key = %s, duration_seconds = %s WHERE id = %s",
            (thumbnail_key, duration_seconds, oid),
        )

    def replace_object_content(self, target_id: str, source_id: str, source: dict) -> None:
        with self.conn.transaction():
            self._run("DELETE FROM objects WHERE id = %s", (source_id,))
            self._run(
                "UPDATE objects SET bucket = %s, object_key = %s, size_bytes = %s, "
                "checksum_sha256 = %s, content_type = %s, expected_size_bytes = %s, "
                "content_encoding = %s, thumbnail_key = %s, duration_seconds = %s, "
                "scrubbed_at = %s, scrub_result = 'ok', version = version + 1, "
                "updated_at = %s WHERE id = %s",
                (source["bucket"], source["object_key"], source["size_bytes"],
                 source["checksum_sha256"], source["content_type"],
                 source.get("expected_size_bytes"), source.get("content_encoding"),
                 source.get("thumbnail_key"), source.get("duration_seconds"),
                 self.now(), self.now(), target_id),
            )

    def list_objects(
        self, *, space_id: str, owner_id: Optional[str] = None,
        folder_id: Optional[str] = None, q: Optional[str] = None,
        status: Optional[str] = None, hide_deleted: bool = False,
        content_type: Optional[str] = None, tag: Optional[str] = None,
        min_size: Optional[int] = None, max_size: Optional[int] = None,
        created_after: Optional[int] = None, created_before: Optional[int] = None,
        sort: str = "created_at", order: str = "desc",
        limit: int = 50, offset: int = 0,
    ):
        # Filters and sort are built by api/object_query.py so this stays in
        # lockstep with the SQLite repository (M02).
        where, params = build_object_where(
            ph="%s", space_id=space_id, owner_id=owner_id, folder_id=folder_id,
            q=q, status=status, hide_deleted=hide_deleted,
            content_type=content_type, tag=tag, min_size=min_size,
            max_size=max_size, created_after=created_after,
            created_before=created_before,
        )
        sql = (
            f"SELECT * FROM objects WHERE {where} "
            f"{order_clause(sort=sort, order=order)} LIMIT %s OFFSET %s"
        )
        params += [limit, offset]
        return self._all(sql, tuple(params))

    def count_pending(
        self, *, space_id: str, owner_id: Optional[str] = None,
        min_expires_at: Optional[int] = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS n FROM objects WHERE status = 'pending' AND space_id = %s"
        params: list = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
        if min_expires_at is not None:
            # Expired intents stay 'pending' until the sweep deletes their
            # bytes: they must not count against the live-intent cap.
            sql += " AND (intent_expires_at IS NULL OR intent_expires_at >= %s)"
            params.append(min_expires_at)
        row = self._one(sql, tuple(params))
        return int(row["n"])

    def reserved_bytes_for(self, *, space_id: str,
                           owner_id: Optional[str] = None) -> int:
        """PostgreSQL twin of ``SqliteRepository.reserved_bytes_for``."""
        sql = (
            "SELECT COALESCE(SUM(expected_size_bytes), 0) AS n FROM objects "
            "WHERE status = 'pending' AND space_id = %s"
        )
        params: list = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
        else:
            sql += " AND owner_id IS NULL"
        row = self._one(sql, tuple(params))
        return int(row["n"])

    def get_pending_by_idempotency(
        self, *, actor_id: str, idempotency_key: str, space_id: str,
    ):
        """The live pending intent for an ``Idempotency-Key`` + actor, if any."""
        return self._one(
            "SELECT * FROM objects WHERE status = 'pending' AND actor_id = %s "
            "AND idempotency_key = %s AND space_id = %s ORDER BY created_at DESC LIMIT 1",
            (actor_id, idempotency_key, space_id),
        )

    # -- asynchronous verification (N5) ------------------------------------
    def mark_verifying(self, oid: str, etag: Optional[str]) -> None:
        """Hand an uploaded object to the verification worker."""
        self._run(
            "UPDATE objects SET status = 'verifying', verify_etag = %s, "
            "verify_lease_until = NULL, verify_attempts = 0, updated_at = %s "
            "WHERE id = %s AND status IN ('pending', 'verifying')",
            (etag, self.now(), oid),
        )

    def claim_verification(self, now: int, lease_until: int):
        """Take the oldest verifying object nobody holds, under a lease.

        ``FOR UPDATE SKIP LOCKED`` lets several workers claim in parallel
        without blocking or taking the same row; a crashed worker's lease
        simply runs out and the object is taken again.
        """
        return self._one(
            "UPDATE objects SET verify_lease_until = %s, "
            "verify_attempts = COALESCE(verify_attempts, 0) + 1 "
            "WHERE id = (SELECT id FROM objects WHERE status = 'verifying' "
            "AND (verify_lease_until IS NULL OR verify_lease_until < %s) "
            "ORDER BY updated_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "RETURNING *",
            (lease_until, now),
        )

    def extend_verification(self, oid: str, lease_until: int) -> None:
        """Push the lease (heartbeat while hashing, or a retry delay)."""
        self._run(
            "UPDATE objects SET verify_lease_until = %s WHERE id = %s AND status = 'verifying'",
            (lease_until, oid),
        )

    def get_by_idempotency(
        self, *, actor_id: str, idempotency_key: str, space_id: str,
    ):
        """Newest object of any status for an ``Idempotency-Key`` + actor."""
        return self._one(
            "SELECT * FROM objects WHERE actor_id = %s AND idempotency_key = %s "
            "AND space_id = %s ORDER BY created_at DESC LIMIT 1",
            (actor_id, idempotency_key, space_id),
        )

    def storage_commitment(self) -> dict:
        """Bytes the object store holds or has promised, across every space.

        ``stored``: verified bytes still on disk (available, trash, purge in
        progress). ``reserved``: declared sizes of uploads not yet verified
        (pending, verifying) — counted from the moment the intent is issued.
        """
        row = self._one(
            "SELECT "
            "COALESCE(SUM(CASE WHEN status IN ('available', 'deleted', 'purging') "
            "AND size_bytes > 0 THEN size_bytes ELSE 0 END), 0) AS stored, "
            "COALESCE(SUM(CASE WHEN status IN ('pending', 'verifying') "
            "AND expected_size_bytes > 0 THEN expected_size_bytes ELSE 0 END), 0) AS reserved "
            "FROM objects"
        )
        return {"stored": int(row["stored"]), "reserved": int(row["reserved"])}
    # -- periodic integrity scrub ------------------------------------------
    def has_pending_uploads(self, since: int) -> bool:
        """True if an upload intent created at or after ``since`` is still pending."""
        return self._one(
            "SELECT 1 AS n FROM objects WHERE status = 'pending' AND created_at >= %s LIMIT 1",
            (since,),
        ) is not None

    def claim_scrub(self, now: int, lease_until: int, checked_before: int):
        """Take the available object checked longest ago (never-checked first),
        under a lease, if it is due (checked before ``checked_before``)."""
        return self._one(
            "UPDATE objects SET scrub_lease_until = %s WHERE id = ("
            "SELECT id FROM objects WHERE status = 'available' "
            "AND (scrubbed_at IS NULL OR scrubbed_at < %s) "
            "AND (scrub_lease_until IS NULL OR scrub_lease_until < %s) "
            "ORDER BY COALESCE(scrubbed_at, 0) ASC, created_at ASC LIMIT 1 "
            "FOR UPDATE SKIP LOCKED) RETURNING *",
            (lease_until, checked_before, now),
        )

    def record_scrub(self, oid: str, result: str, at: int) -> None:
        self._run(
            "UPDATE objects SET scrubbed_at = %s, scrub_result = %s, scrub_lease_until = NULL "
            "WHERE id = %s",
            (at, result, oid),
        )

    def has_active_transfers(self, since: int) -> bool:
        """True while uploads are in flight: a verifying object, or a pending
        intent created at or after ``since``. The scrubber yields to them."""
        return self._one(
            "SELECT 1 AS n FROM objects WHERE status = 'verifying' "
            "OR (status = 'pending' AND created_at >= %s) LIMIT 1",
            (since,),
        ) is not None

    def release_scrub(self, oid: str) -> None:
        """Give the object back unchecked (storage outage): retried next run."""
        self._run("UPDATE objects SET scrub_lease_until = NULL WHERE id = %s", (oid,))

    def integrity_summary(self) -> dict:
        rows = self._all(
            "SELECT COALESCE(scrub_result, 'unchecked') AS result, COUNT(*) AS n, "
            "MIN(scrubbed_at) AS oldest FROM objects WHERE status = 'available' "
            "GROUP BY COALESCE(scrub_result, 'unchecked')"
        )
        return {r["result"]: {"count": int(r["n"]), "oldest": r["oldest"]} for r in rows}

    def list_integrity_problems(self, limit: int = 100):
        return self._all(
            "SELECT id, space_id, display_name, size_bytes, scrub_result, scrubbed_at "
            "FROM objects WHERE status = 'available' "
            "AND scrub_result IN ('mismatch', 'missing') "
            "ORDER BY scrubbed_at DESC LIMIT %s",
            (limit,),
        )
    def object_states_for_keys(self, bucket: str, keys: list) -> dict:
        """Catalogue state of storage keys: ``{key: {id, status, multipart_upload_id}}``.

        Keys without a row are absent from the result (storage orphans).
        """
        out: dict = {}
        if not keys:
            return out
        for r in self._all(
            "SELECT id, object_key, status, multipart_upload_id FROM objects "
            "WHERE bucket = %s AND object_key = ANY(%s)",
            (bucket, list(keys)),
        ):
            out[r["object_key"]] = {
                "id": r["id"], "status": r["status"],
                "multipart_upload_id": r["multipart_upload_id"],
            }
        return out

    TERMINAL_STATUSES = {"failed", "expired", "aborted", "deleted"}

    def mark_available(self, oid: str, size_bytes: int, checksum_sha256: str,
                       expected_version=None) -> int:
        if expected_version is None:
            return self._run(
                "UPDATE objects SET status = 'available', size_bytes = %s, "
                "checksum_sha256 = %s, version = version + 1, updated_at = %s, "
                "scrubbed_at = %s, scrub_result = 'ok' "
                "WHERE id = %s AND status IN ('pending', 'verifying')",
                (size_bytes, checksum_sha256, self.now(), self.now(), oid),
            )
        return self._run(
            "UPDATE objects SET status = 'available', size_bytes = %s, "
            "checksum_sha256 = %s, version = version + 1, updated_at = %s, "
            "scrubbed_at = %s, scrub_result = 'ok' "
            "WHERE id = %s AND status IN ('pending', 'verifying') AND version = %s",
            (size_bytes, checksum_sha256, self.now(), self.now(), oid, expected_version),
        )

    def set_multipart(self, oid: str, upload_id: Optional[str],
                      part_bytes: Optional[int]) -> None:
        """Record (or clear, with ``upload_id=None``) a multipart session (#72)."""
        self._run(
            "UPDATE objects SET multipart_upload_id = %s, multipart_part_bytes = %s, "
            "updated_at = %s WHERE id = %s",
            (upload_id, part_bytes, self.now(), oid),
        )

    def list_pending_before(self, cutoff: int, limit: int = 500,
                            multipart_expired_before: Optional[int] = None):
        # A multipart session lives longer than a single-PUT intent: it is only
        # stale once its own expiry has passed, whatever its creation time.
        mp_cut = multipart_expired_before if multipart_expired_before is not None else cutoff
        return self._all(
            "SELECT * FROM objects WHERE status = 'pending' AND created_at < %s "
            "AND (multipart_upload_id IS NULL OR intent_expires_at < %s) "
            "ORDER BY created_at ASC LIMIT %s",
            (cutoff, mp_cut, limit),
        )

    def list_available(self, limit: int = 500):
        """Available rows oldest-first, bounded (M07 orphan scan)."""
        return self._all(
            "SELECT * FROM objects WHERE status = 'available' "
            "ORDER BY updated_at ASC LIMIT %s",
            (limit,),
        )

    def mark_reverified(self, oid: str, size_bytes: int,
                        checksum_sha256: str) -> int:
        """PostgreSQL twin of ``SqliteRepository.mark_reverified``."""
        return self._run(
            "UPDATE objects SET status = 'available', size_bytes = %s, "
            "checksum_sha256 = %s, version = version + 1, updated_at = %s, "
            "scrubbed_at = %s, scrub_result = 'ok' "
            "WHERE id = %s AND status IN ('available', 'suspect', 'failed')",
            (size_bytes, checksum_sha256, self.now(), self.now(), oid),
        )

    def set_status(self, oid: str, status: str, *,
                   expected_version=None, allowed_from=None) -> int:
        clauses = ["status = %s", "version = version + 1", "updated_at = %s"]
        params = [status, self.now()]
        where = ["id = %s"]
        params2 = [oid]
        if allowed_from:
            where.append("status IN (%s)" % ",".join(["%s"] * len(allowed_from)))
            params2.extend(allowed_from)
        if expected_version is not None:
            where.append("version = %s")
            params2.append(expected_version)
        if status in self.TERMINAL_STATUSES:
            clauses.append("terminal_since = COALESCE(terminal_since, %s)")
            params.insert(1, self.now())
        sql = "UPDATE objects SET " + ", ".join(clauses) + " WHERE " + " AND ".join(where)
        return self._run(sql, params + params2)

    def list_status_before(self, status: str, cutoff: int, limit: int = 500):
        """Rows in ``status`` not updated since ``cutoff``, oldest first."""
        return self._all(
            "SELECT * FROM objects WHERE status = %s AND updated_at < %s "
            "ORDER BY updated_at ASC LIMIT %s",
            (status, cutoff, limit),
        )

    def delete_object_row(self, oid: str) -> None:
        self._run("DELETE FROM objects WHERE id = %s", (oid,))

    # -- folders (#61) ----------------------------------------------------
    # Folders are logical catalogue entities owned by a human user. They are
    # never real host directories; parent/child links live in `parent_id`.
    def create_folder(self, owner_id: str, name: str, parent_id: Optional[str] = None) -> str:
        fid = self.new_id()
        self._run(
            "INSERT INTO folders (id, owner_id, parent_id, name, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (fid, owner_id, parent_id, name, self.now()),
        )
        return fid

    def get_folder(self, fid: str, *, owner_id: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM folders WHERE id = %s AND owner_id = %s", (fid, owner_id)
        )

    def list_folders(self, *, owner_id: str, parent_id: Optional[str] = None) -> list:
        # parent_id=None lists the root level (parent_id IS NULL).
        if parent_id is None:
            return self._all(
                "SELECT * FROM folders WHERE owner_id = %s AND parent_id IS NULL "
                'ORDER BY name COLLATE "C"',
                (owner_id,),
            )
        return self._all(
            "SELECT * FROM folders WHERE owner_id = %s AND parent_id = %s "
            'ORDER BY name COLLATE "C"',
            (owner_id, parent_id),
        )

    def list_all_folders(self, *, owner_id: str) -> list:
        # Flat listing of the owner's whole tree in one query (#62 follow-up).
        # Ordered by name for a deterministic payload; the client rebuilds the
        # hierarchy from parent_id. Owner-scoped, so no cross-user leak.
        # COLLATE "C": byte order, same as SQLite, whatever the database locale
        # (an en_US.utf8 cluster would put "d10-x" before "d1-x").
        return self._all(
            'SELECT * FROM folders WHERE owner_id = %s ORDER BY name COLLATE "C", id',
            (owner_id,),
        )

    def folder_name_exists(
        self, *, owner_id: str, parent_id: Optional[str], name: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        if parent_id is None:
            sql = "SELECT 1 AS x FROM folders WHERE owner_id = %s AND parent_id IS NULL AND name = %s"
            params: list = [owner_id, name]
        else:
            sql = "SELECT 1 AS x FROM folders WHERE owner_id = %s AND parent_id = %s AND name = %s"
            params = [owner_id, parent_id, name]
        if exclude_id is not None:
            sql += " AND id != %s"
            params.append(exclude_id)
        return self._one(sql, tuple(params)) is not None

    def rename_folder(self, fid: str, *, owner_id: str, name: str) -> None:
        self._run(
            "UPDATE folders SET name = %s WHERE id = %s AND owner_id = %s", (name, fid, owner_id)
        )

    def set_folder_parent(
        self, fid: str, *, owner_id: str, parent_id: Optional[str]
    ) -> None:
        self._run(
            "UPDATE folders SET parent_id = %s WHERE id = %s AND owner_id = %s",
            (parent_id, fid, owner_id),
        )

    def set_object_folder(self, oid: str, *, folder_id: Optional[str]) -> None:
        # File an object into a folder, or unfiled (folder_id IS NULL). Scope is
        # enforced by the caller first (#61/#62): the route reads the object with
        # the caller's space/owner filter before issuing this update.
        self._run(
            "UPDATE objects SET folder_id = %s, updated_at = %s WHERE id = %s",
            (folder_id, self.now(), oid),
        )

    def folder_child_count(self, fid: str, *, owner_id: str) -> int:
        return int(self._one(
            "SELECT COUNT(*) AS n FROM folders WHERE parent_id = %s AND owner_id = %s",
            (fid, owner_id),
        )["n"])

    def folder_object_count(self, fid: str, *, owner_id: str) -> int:
        # Only live objects keep a folder "non-empty". Live means an object the
        # user can still act on: committed (``available``) plus in-flight
        # uploads (``pending``/``verifying``), which must block the delete
        # because their bytes may still land in the folder. Every other status
        # (deleted, failed, expired, aborted, purging) is a leftover row hidden
        # from the listings (api/object_query.py) but still carrying a
        # ``folder_id``: counting it would refuse the DELETE of a folder the
        # user already sees as empty, forever.
        return int(self._one(
            "SELECT COUNT(*) AS n FROM objects WHERE folder_id = %s AND owner_id = %s "
            "AND status IN ('available', 'pending', 'verifying')",
            (fid, owner_id),
        )["n"])

    def release_folder_objects(self, fid: str, *, owner_id: str) -> None:
        # Called just before the folder row is deleted, after the counts
        # confirmed no live object remains attached. Detach every leftover row
        # (a dangling ``objects.folder_id`` would break the FK on PostgreSQL)
        # and mark it ``deleted`` so failed/aborted/expired leftovers do not
        # reappear as unfiled rows in the root listing. The guard keeps the
        # live statuses out even if a caller skipped the count check; rows are
        # kept in the catalogue until an explicit purge.
        self._run(
            "UPDATE objects SET folder_id = NULL, status = 'deleted', updated_at = %s "
            "WHERE folder_id = %s AND owner_id = %s "
            "AND status NOT IN ('available', 'pending', 'verifying')",
            (self.now(), fid, owner_id),
        )

    def delete_folder(self, fid: str, *, owner_id: str) -> None:
        self._run("DELETE FROM folders WHERE id = %s AND owner_id = %s", (fid, owner_id))

    # -- observability (#40, M07) ----------------------------------------
    def ping(self) -> None:
        """Liveness probe for supervision: raises on any backend failure."""
        self._one("SELECT 1")

    def stored_bytes(self) -> int:
        """Verified bytes currently held: available objects only (M07)."""
        row = self._one(
            "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM objects "
            "WHERE status = 'available'"
        )
        return int(row["n"])

    def space_usage(self, sid: str) -> dict:
        """Real per-space consumption for the M07 usage endpoint."""
        by_status = {
            row["status"]: row["n"]
            for row in self._all(
                "SELECT status, COUNT(*) AS n FROM objects "
                "WHERE space_id = %s GROUP BY status", (sid,)
            )
        }
        row = self._one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes "
            "FROM objects WHERE space_id = %s AND status = 'available'",
            (sid,),
        )
        pending = int(self._one(
            "SELECT COUNT(*) AS n FROM objects "
            "WHERE space_id = %s AND status = 'pending'", (sid,),
        )["n"])
        return {
            "objects_by_status": by_status,
            "available_count": int(row["n"]),
            "stored_bytes": int(row["bytes"]),
            "pending_count": pending,
        }

    def get_space_quotas(self, sid: str) -> Optional[dict]:
        return self._one("SELECT * FROM space_quotas WHERE space_id = %s", (sid,))

    def set_space_quotas(
        self, sid: str, storage_bytes: Optional[int],
        egress_bytes_monthly: Optional[int], updated_by: Optional[str],
    ) -> None:
        self._run(
            "INSERT INTO space_quotas (space_id, storage_bytes, "
            "egress_bytes_monthly, updated_at, updated_by) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (space_id) DO UPDATE SET "
            "storage_bytes = excluded.storage_bytes, "
            "egress_bytes_monthly = excluded.egress_bytes_monthly, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (sid, storage_bytes, egress_bytes_monthly, self.now(), updated_by),
        )

    def get_space_usage_monthly(self, sid: str, period: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM space_usage_monthly WHERE space_id = %s AND period = %s",
            (sid, period),
        )

    def record_space_egress(
        self, sid: str, period: str, kind: str, size_bytes: int,
    ) -> None:
        column = {
            "download": "download_intents",
            "preview": "preview_intents",
            "share": "share_redemptions",
        }[kind]
        self._run(
            "INSERT INTO space_usage_monthly (space_id, period, egress_bytes, "
            f"{column}, updated_at) VALUES (%s, %s, %s, 1, %s) "
            "ON CONFLICT (space_id, period) DO UPDATE SET "
            "egress_bytes = space_usage_monthly.egress_bytes + excluded.egress_bytes, "
            f"{column} = space_usage_monthly.{column} + 1, "
            "updated_at = excluded.updated_at",
            (sid, period, max(0, int(size_bytes)), self.now()),
        )


    # -- tags and packs (Sprint 2) --------------------------------------
    def set_object_tags(self, oid: str, tags: list) -> None:
        self._run("DELETE FROM object_tags WHERE object_id = %s", (oid,))
        self._run_many(
            "INSERT INTO object_tags (object_id, tag) VALUES (%s, %s)",
            [(oid, tag) for tag in tags],
        )

    def get_object_tags(self, oid: str) -> list:
        return [r["tag"] for r in self._all(
            "SELECT tag FROM object_tags WHERE object_id = %s ORDER BY tag", (oid,)
        )]

    def list_tags_for_objects(self, ids: list) -> dict:
        if not ids:
            return {}
        marks = ",".join("%s" for _ in ids)
        rows = self._all(
            f"SELECT object_id, tag FROM object_tags WHERE object_id IN ({marks}) "
            "ORDER BY tag", tuple(ids),
        )
        out: dict = {}
        for row in rows:
            out.setdefault(row["object_id"], []).append(row["tag"])
        return out

    def create_collection(
        self, cid: str, space_id: str, owner_id, slug: str,
        title: str, description: str,
    ) -> str:
        now = self.now()
        self._run(
            "INSERT INTO collections (id, space_id, owner_id, slug, title, "
            "description, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (cid, space_id, owner_id, slug, title, description, now, now),
        )
        return cid

    def list_collections(self, space_id: str, owner_id=None) -> list:
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM collection_items i "
            "WHERE i.collection_id = c.id) AS item_count "
            "FROM collections c WHERE c.space_id = %s"
        )
        params = [space_id]
        if owner_id is not None:
            sql += " AND c.owner_id = %s"
            params.append(owner_id)
        sql += " ORDER BY c.created_at DESC"
        return self._all(sql, tuple(params))

    def get_collection(self, cid: str):
        return self._one("SELECT * FROM collections WHERE id = %s", (cid,))

    def get_collection_by_slug(self, slug: str):
        return self._one("SELECT * FROM collections WHERE slug = %s", (slug,))

    def update_collection(self, cid: str, title: str, description: str, published_at) -> None:
        self._run(
            "UPDATE collections SET title = %s, description = %s, published_at = %s, "
            "updated_at = %s WHERE id = %s",
            (title, description, published_at, self.now(), cid),
        )

    def replace_collection_items(self, cid: str, object_ids: list) -> None:
        with self.conn.transaction():
            self._run("DELETE FROM collection_items WHERE collection_id = %s", (cid,))
            self._run_many(
                "INSERT INTO collection_items (collection_id, object_id, position) "
                "VALUES (%s, %s, %s)",
                [(cid, oid, pos) for pos, oid in enumerate(object_ids)],
            )
            self._run(
                "UPDATE collections SET updated_at = %s WHERE id = %s",
                (self.now(), cid),
            )

    def get_collection_items(self, cid: str) -> list:
        return self._all(
            "SELECT o.*, i.position FROM collection_items i "
            "JOIN objects o ON o.id = i.object_id "
            "WHERE i.collection_id = %s ORDER BY i.position", (cid,)
        )

    def delete_collection(self, cid: str) -> None:
        with self.conn.transaction():
            self._run("DELETE FROM collection_items WHERE collection_id = %s", (cid,))
            self._run("DELETE FROM collections WHERE id = %s", (cid,))


    # -- per-object analytics -------------------------------------------
    def record_object_event(self, oid: str, period: str, kind: str,
                            size_bytes: int, now: int) -> None:
        column = {"view": "views", "download": "downloads",
                  "share": "share_opens"}[kind]
        self._run(
            "INSERT INTO object_usage_monthly (object_id, period, views, downloads, "
            "share_opens, egress_bytes, last_access_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(object_id, period) DO UPDATE SET "
            f"{column} = object_usage_monthly.{column} + 1, "
            "egress_bytes = object_usage_monthly.egress_bytes + excluded.egress_bytes, "
            "last_access_at = excluded.last_access_at",
            (oid, period,
             1 if kind == "view" else 0,
             1 if kind == "download" else 0,
             1 if kind == "share" else 0,
             max(0, int(size_bytes)), now),
        )

    def get_object_usage(self, oid: str, period: str):
        return self._one(
            "SELECT * FROM object_usage_monthly WHERE object_id = %s AND period = %s",
            (oid, period),
        )

    def get_object_usage_totals(self, oid: str) -> dict:
        row = self._one(
            "SELECT COALESCE(SUM(views),0) AS views, "
            "COALESCE(SUM(downloads),0) AS downloads, "
            "COALESCE(SUM(share_opens),0) AS share_opens, "
            "COALESCE(SUM(egress_bytes),0) AS egress_bytes, "
            "MAX(last_access_at) AS last_access_at "
            "FROM object_usage_monthly WHERE object_id = %s", (oid,),
        )
        return row or {}

    def stats(self) -> dict:
        objects = {
            row["status"]: row["n"]
            for row in self._all("SELECT status, COUNT(*) AS n FROM objects GROUP BY status")
        }
        counts = {
            "applications": "SELECT COUNT(*) AS n FROM applications",
            "spaces": "SELECT COUNT(*) AS n FROM spaces",
            "buckets": "SELECT COUNT(*) AS n FROM buckets",
            "service_identities": "SELECT COUNT(*) AS n FROM service_identities",
            "active_service_identities": (
                "SELECT COUNT(*) AS n FROM service_identities WHERE revoked_at IS NULL"
            ),
        }
        stats = {"objects_by_status": objects}
        for key, sql in counts.items():
            stats[key] = self._one(sql)["n"]
        return stats
