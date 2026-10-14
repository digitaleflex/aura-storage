"""SQLite catalogue behind a small Repository interface (#18; PostgreSQL in #19)."""
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


class Repository:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def now(self) -> int:
        return int(time.time())

    def new_id(self) -> str:
        return str(uuid.uuid4())

    # -- users ------------------------------------------------------------
    def get_user_by_name(self, username: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def create_user(self, username: str, pass_hash: str) -> str:
        uid = self.new_id()
        self.conn.execute(
            "INSERT INTO users (id, username, pass_hash, created_at) VALUES (?, ?, ?, ?)",
            (uid, username, pass_hash, self.now()),
        )
        self.conn.commit()
        return uid

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

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, bucket: str, object_key: str, display_name: str,
        content_type: str, owner_id: str, folder_id: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self.conn.execute(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, -1, '', ?, ?, 'private', 'pending', ?, ?)""",
            (oid, bucket, object_key, display_name, content_type, folder_id,
             owner_id, now, now),
        )
        self.conn.commit()
        return oid

    def get_object(self, oid: str, owner_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM objects WHERE id = ? AND owner_id = ?", (oid, owner_id)
        ).fetchone()

    def list_objects(self, owner_id: str, limit: int = 50, offset: int = 0):
        return self.conn.execute(
            "SELECT * FROM objects WHERE owner_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (owner_id, limit, offset),
        ).fetchall()

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
