"""PostgreSQL catalogue implementing the same Repository interface as db.py (#19)."""
import time
import uuid
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


class Repository:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA)

    def now(self) -> int:
        return int(time.time())

    def new_id(self) -> str:
        return str(uuid.uuid4())

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, bucket: str, object_key: str, display_name: str,
        content_type: str, owner_id: str, folder_id: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
                   size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
                   created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, -1, '', %s, %s, 'private', 'pending', %s, %s)""",
                (oid, bucket, object_key, display_name, content_type, folder_id,
                 owner_id, now, now),
            )
        return oid

    def get_object(self, oid: str, owner_id: str) -> Optional[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM objects WHERE id = %s AND owner_id = %s", (oid, owner_id)
            )
            return cur.fetchone()

    def list_objects(self, owner_id: str, limit: int = 50, offset: int = 0):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM objects WHERE owner_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (owner_id, limit, offset),
            )
            return cur.fetchall()

    def mark_available(self, oid: str, size_bytes: int, checksum_sha256: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE objects SET status = 'available', size_bytes = %s, checksum_sha256 = %s, updated_at = %s WHERE id = %s",
                (size_bytes, checksum_sha256, self.now(), oid),
            )

    def list_pending_before(self, cutoff: int):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM objects WHERE status = 'pending' AND created_at < %s",
                (cutoff,),
            )
            return cur.fetchall()

    def set_status(self, oid: str, status: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE objects SET status = %s, updated_at = %s WHERE id = %s",
                (status, self.now(), oid),
            )

    def delete_object_row(self, oid: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM objects WHERE id = %s", (oid,))
