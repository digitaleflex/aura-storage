"""PostgreSQL catalogue implementing the same Repository interface as db.py (#19)."""
import time
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from . import ids
from .migrations import (
    DEFAULT_APPLICATION_NAME,
    DEFAULT_ENVIRONMENT,
    DEFAULT_SPACE_NAME,
    apply_migrations,
)

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


class Repository:
    dialect = "postgres"

    def __init__(self, dsn: str):
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

    def create_space(self, application_id: str, name: str, environment: str) -> str:
        sid = self.new_id()
        self._run(
            "INSERT INTO spaces (id, application_id, name, environment, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
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
        return self._one(
            "SELECT * FROM buckets WHERE space_id = %s "
            "ORDER BY is_default DESC, created_at ASC LIMIT 1",
            (space_id,),
        )

    def get_bucket_by_name(self, name: str) -> Optional[dict]:
        return self._one("SELECT * FROM buckets WHERE name = %s", (name,))

    def list_buckets(self, space_id: str) -> list:
        return self._all(
            "SELECT * FROM buckets WHERE space_id = %s ORDER BY created_at", (space_id,)
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
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self._run(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at, actor_kind, actor_id, application_id, space_id,
               environment, intent_expires_at)
               VALUES (%s, %s, %s, %s, %s, -1, '', %s, %s, 'private', 'pending', %s, %s,
                       %s, %s, %s, %s, %s, %s)""",
            (oid, bucket, object_key, display_name, content_type, folder_id, owner_id,
             now, now, actor_kind, actor_id, application_id, space_id, environment,
             intent_expires_at),
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
        folder_id: Optional[str] = None, limit: int = 50, offset: int = 0,
    ):
        # ``folder_id`` narrows the list when supplied: an empty string means
        # "not filed in any folder" (folder_id IS NULL), a uuid means that
        # folder. Omitting it keeps the previous behaviour (every object).
        sql = "SELECT * FROM objects WHERE space_id = %s"
        params = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = %s"
            params.append(owner_id)
        if folder_id is not None:
            if folder_id == "":
                sql += " AND folder_id IS NULL"
            else:
                sql += " AND folder_id = %s"
                params.append(folder_id)
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
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

    # -- observability (#40) ----------------------------------------------
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
