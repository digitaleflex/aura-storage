"""SQLite catalogue behind a small Repository interface (#18; PostgreSQL in #19)."""
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from .migrations import (
    DEFAULT_APPLICATION_ID,
    DEFAULT_SPACE_ID,
    apply_migrations,
)

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def _as_dict(row):
    return dict(row) if row is not None else None


class Repository:
    dialect = "sqlite"

    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        apply_migrations(self.conn, "sqlite")

    def now(self) -> int:
        return int(time.time())

    def new_id(self) -> str:
        return str(uuid.uuid4())

    # -- users ------------------------------------------------------------
    def get_user_by_name(self, username: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def get_user(self, uid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    def create_user(
        self, username: str, pass_hash: str, role: str = "user",
        space_id: Optional[str] = None, application_id: Optional[str] = None,
    ) -> str:
        uid = self.new_id()
        self.conn.execute(
            "INSERT INTO users (id, username, pass_hash, created_at, role, "
            "application_id, space_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, username, pass_hash, self.now(), role,
             application_id or DEFAULT_APPLICATION_ID, space_id or DEFAULT_SPACE_ID),
        )
        self.conn.commit()
        return uid

    def ensure_admin(self, uid: str) -> None:
        self.conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (uid,))
        self.conn.execute(
            "UPDATE users SET application_id = ? WHERE id = ? AND application_id IS NULL",
            (DEFAULT_APPLICATION_ID, uid),
        )
        self.conn.execute(
            "UPDATE users SET space_id = ? WHERE id = ? AND space_id IS NULL",
            (DEFAULT_SPACE_ID, uid),
        )
        self.conn.commit()

    # -- sessions ---------------------------------------------------------
    def create_session(self, user_id: str, csrf: str, expires_at: int) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO sessions (id, user_id, csrf, expires_at) VALUES (?, ?, ?, ?)",
            (sid, user_id, csrf, expires_at),
        )
        self.conn.commit()
        return sid

    def get_session(self, sid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND expires_at > ?",
            (sid, self.now()),
        ).fetchone()

    def delete_session(self, sid: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        self.conn.commit()

    # -- applications / spaces / buckets (#35) ----------------------------
    def create_application(self, name: str) -> str:
        aid = self.new_id()
        self.conn.execute(
            "INSERT INTO applications (id, name, status, created_at) VALUES (?, ?, 'active', ?)",
            (aid, name, self.now()),
        )
        self.conn.commit()
        return aid

    def get_application(self, aid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM applications WHERE id = ?", (aid,)
        ).fetchone())

    def get_application_by_name(self, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM applications WHERE name = ?", (name,)
        ).fetchone())

    def list_applications(self) -> list:
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT * FROM applications ORDER BY created_at"
        ).fetchall()]

    def create_space(self, application_id: str, name: str, environment: str) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO spaces (id, application_id, name, environment, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, application_id, name, environment, self.now()),
        )
        self.conn.commit()
        return sid

    def get_space(self, sid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM spaces WHERE id = ?", (sid,)
        ).fetchone())

    def list_spaces(self, application_id: Optional[str] = None) -> list:
        if application_id:
            rows = self.conn.execute(
                "SELECT * FROM spaces WHERE application_id = ? ORDER BY created_at",
                (application_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM spaces ORDER BY created_at"
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def create_bucket(self, space_id: str, name: str, is_default: bool = False) -> str:
        bid = self.new_id()
        self.conn.execute(
            "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bid, space_id, name, 1 if is_default else 0, self.now()),
        )
        self.conn.commit()
        return bid

    def get_bucket_for_space(self, space_id: str, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? AND name = ?", (space_id, name)
        ).fetchone())

    def get_default_bucket(self, space_id: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? "
            "ORDER BY is_default DESC, created_at ASC LIMIT 1",
            (space_id,),
        ).fetchone())

    def get_bucket_by_name(self, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE name = ?", (name,)
        ).fetchone())

    def list_buckets(self, space_id: str) -> list:
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? ORDER BY created_at", (space_id,)
        ).fetchall()]

    # -- service identities (#38) -----------------------------------------
    def create_identity(
        self, iid: str, application_id: str, space_id: str, name: str,
        secret_hash: str, scopes: str, expires_at: Optional[int] = None,
    ) -> str:
        self.conn.execute(
            "INSERT INTO service_identities (id, application_id, space_id, name, "
            "secret_hash, scopes, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, application_id, space_id, name, secret_hash, scopes, self.now(), expires_at),
        )
        self.conn.commit()
        return iid

    def get_identity(self, iid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM service_identities WHERE id = ?", (iid,)
        ).fetchone())

    def list_identities(self, space_id: Optional[str] = None) -> list:
        if space_id:
            rows = self.conn.execute(
                "SELECT * FROM service_identities WHERE space_id = ? ORDER BY created_at",
                (space_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM service_identities ORDER BY created_at"
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def update_identity_secret(self, iid: str, secret_hash: str) -> None:
        self.conn.execute(
            "UPDATE service_identities SET secret_hash = ?, rotated_at = ? WHERE id = ?",
            (secret_hash, self.now(), iid),
        )
        self.conn.commit()

    def revoke_identity(self, iid: str) -> None:
        self.conn.execute(
            "UPDATE service_identities SET revoked_at = ? WHERE id = ?",
            (self.now(), iid),
        )
        self.conn.commit()

    def touch_identity(self, iid: str, ts: int) -> None:
        self.conn.execute(
            "UPDATE service_identities SET last_used_at = ? WHERE id = ?", (ts, iid)
        )
        self.conn.commit()

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, *, space_id: str, application_id: Optional[str], environment: Optional[str],
        bucket: str, object_key: str, display_name: str, content_type: str,
        owner_id: Optional[str], actor_id: str, actor_kind: str,
        intent_expires_at: Optional[int], folder_id: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self.conn.execute(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at, actor_kind, actor_id, application_id, space_id,
               environment, intent_expires_at)
               VALUES (?, ?, ?, ?, ?, -1, '', ?, ?, 'private', 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (oid, bucket, object_key, display_name, content_type, folder_id, owner_id,
             now, now, actor_kind, actor_id, application_id, space_id, environment,
             intent_expires_at),
        )
        self.conn.commit()
        return oid

    def get_object(self, oid: str, *, space_id: str, owner_id: Optional[str] = None):
        sql = "SELECT * FROM objects WHERE id = ? AND space_id = ?"
        params = [oid, space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        return self.conn.execute(sql, params).fetchone()

    def list_objects(
        self, *, space_id: str, owner_id: Optional[str] = None,
        limit: int = 50, offset: int = 0,
    ):
        sql = "SELECT * FROM objects WHERE space_id = ?"
        params = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self.conn.execute(sql, params).fetchall()

    def count_pending(self, *, space_id: str, owner_id: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM objects WHERE status = 'pending' AND space_id = ?"
        params = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        return int(self.conn.execute(sql, params).fetchone()["n"])

    def mark_available(self, oid: str, size_bytes: int, checksum_sha256: str) -> None:
        self.conn.execute(
            "UPDATE objects SET status = 'available', size_bytes = ?, checksum_sha256 = ?, updated_at = ? WHERE id = ?",
            (size_bytes, checksum_sha256, self.now(), oid),
        )
        self.conn.commit()

    def list_pending_before(self, cutoff: int):
        return self.conn.execute(
            "SELECT * FROM objects WHERE status = 'pending' AND created_at < ?",
            (cutoff,),
        ).fetchall()

    def set_status(self, oid: str, status: str) -> None:
        self.conn.execute(
            "UPDATE objects SET status = ?, updated_at = ? WHERE id = ?",
            (status, self.now(), oid),
        )
        self.conn.commit()

    def delete_object_row(self, oid: str) -> None:
        self.conn.execute("DELETE FROM objects WHERE id = ?", (oid,))
        self.conn.commit()

    # -- observability (#40) ----------------------------------------------
    def stats(self) -> dict:
        objects = {
            row["status"]: row["n"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM objects GROUP BY status"
            ).fetchall()
        }
        return {
            "objects_by_status": objects,
            "applications": self.conn.execute(
                "SELECT COUNT(*) AS n FROM applications"
            ).fetchone()["n"],
            "spaces": self.conn.execute("SELECT COUNT(*) AS n FROM spaces").fetchone()["n"],
            "buckets": self.conn.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"],
            "service_identities": self.conn.execute(
                "SELECT COUNT(*) AS n FROM service_identities"
            ).fetchone()["n"],
            "active_service_identities": self.conn.execute(
                "SELECT COUNT(*) AS n FROM service_identities WHERE revoked_at IS NULL"
            ).fetchone()["n"],
        }
