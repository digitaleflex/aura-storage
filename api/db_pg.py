"""PostgreSQL catalogue implementing the same Repository interface as db.py (#19)."""
import threading
import time
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from . import ids
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

    def _run(self, sql: str, params: tuple = ()) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

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
        sid = self.new_id()
        self._run(
            "INSERT INTO sessions (id, user_id, csrf, expires_at) VALUES (%s, %s, %s, %s)",
            (sid, user_id, csrf, expires_at),
        )
        return sid

    def get_session(self, sid: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM sessions WHERE id = %s AND expires_at > %s",
            (sid, self.now()),
        )

    def delete_session(self, sid: str) -> None:
        self._run("DELETE FROM sessions WHERE id = %s", (sid,))

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

    def revoke_identity(self, iid: str) -> None:
        self._run(
            "UPDATE service_identities SET revoked_at = %s WHERE id = %s",
            (self.now(), iid),
        )

    def touch_identity(self, iid: str, ts: int) -> None:
        self._run(
            "UPDATE service_identities SET last_used_at = %s WHERE id = %s", (ts, iid)
        )

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, *, space_id: str, application_id: Optional[str], environment: Optional[str],
        bucket: str, object_key: str, display_name: str, content_type: str,
        owner_id: Optional[str], actor_id: str, actor_kind: str,
        intent_expires_at: Optional[int], folder_id: Optional[str] = None,
        expected_size_bytes: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self._run(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at, actor_kind, actor_id, application_id, space_id,
               environment, intent_expires_at, expected_size_bytes, idempotency_key)
               VALUES (%s, %s, %s, %s, %s, -1, '', %s, %s, 'private', 'pending', %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s)""",
            (oid, bucket, object_key, display_name, content_type, folder_id, owner_id,
             now, now, actor_kind, actor_id, application_id, space_id, environment,
             intent_expires_at, expected_size_bytes, idempotency_key),
        )
        return oid

    def get_object(self, oid: str, *, space_id: str, owner_id: Optional[str] = None):
        sql = "SELECT * FROM objects WHERE id = %s AND space_id = %s"
        params = [oid, space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
        return self._one(sql, tuple(params))

    def list_objects(
        self, *, space_id: str, owner_id: Optional[str] = None,
        folder_id: Optional[str] = None, q: Optional[str] = None,
        status: Optional[str] = None, content_type: Optional[str] = None,
        min_size: Optional[int] = None, max_size: Optional[int] = None,
        created_after: Optional[int] = None, created_before: Optional[int] = None,
        sort: str = "created_at", order: str = "desc",
        limit: int = 50, offset: int = 0,
    ):
        # Filters and sort are built by api/object_query.py so this stays in
        # lockstep with the SQLite repository (M02).
        where, params = build_object_where(
            ph="%s", space_id=space_id, owner_id=owner_id, folder_id=folder_id,
            q=q, status=status, content_type=content_type, min_size=min_size,
            max_size=max_size, created_after=created_after,
            created_before=created_before,
        )
        sql = (
            f"SELECT * FROM objects WHERE {where} "
            f"{order_clause(sort=sort, order=order)} LIMIT %s OFFSET %s"
        )
        params += [limit, offset]
        return self._all(sql, tuple(params))

    def count_pending(self, *, space_id: str, owner_id: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM objects WHERE status = 'pending' AND space_id = %s"
        params = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
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

    def mark_available(self, oid: str, size_bytes: int, checksum_sha256: str) -> None:
        self._run(
            "UPDATE objects SET status = 'available', size_bytes = %s, checksum_sha256 = %s, updated_at = %s WHERE id = %s",
            (size_bytes, checksum_sha256, self.now(), oid),
        )

    def list_pending_before(self, cutoff: int):
        return self._all(
            "SELECT * FROM objects WHERE status = 'pending' AND created_at < %s",
            (cutoff,),
        )

    def set_status(self, oid: str, status: str) -> None:
        self._run(
            "UPDATE objects SET status = %s, updated_at = %s WHERE id = %s",
            (status, self.now(), oid),
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
                "ORDER BY name",
                (owner_id,),
            )
        return self._all(
            "SELECT * FROM folders WHERE owner_id = %s AND parent_id = %s ORDER BY name",
            (owner_id, parent_id),
        )

    def list_all_folders(self, *, owner_id: str) -> list:
        # Flat listing of the owner's whole tree in one query (#62 follow-up).
        # Ordered by name for a deterministic payload; the client rebuilds the
        # hierarchy from parent_id. Owner-scoped, so no cross-user leak.
        return self._all(
            "SELECT * FROM folders WHERE owner_id = %s ORDER BY name, id", (owner_id,)
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
        return int(self._one(
            "SELECT COUNT(*) AS n FROM objects WHERE folder_id = %s AND owner_id = %s",
            (fid, owner_id),
        )["n"])

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
