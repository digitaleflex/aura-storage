"""Issue #35: additive migrations preserve existing catalogue data and are idempotent.

Runs entirely on a disposable SQLite file; no PostgreSQL or S3 endpoint needed.
"""
import sqlite3

from api import migrations
from api.db import SCHEMA

OLD_SCHEMA = """
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE folders (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES users(id),
  parent_id TEXT REFERENCES folders(id),
  name TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE objects (
  id TEXT PRIMARY KEY,
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT -1,
  checksum_sha256 TEXT NOT NULL DEFAULT '',
  folder_id TEXT REFERENCES folders(id),
  owner_id TEXT NOT NULL REFERENCES users(id),
  visibility TEXT NOT NULL DEFAULT 'private',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (bucket, object_key)
);
"""


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO users VALUES ('u1', 'admin', 'hash', 1)")
    conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, status, created_at, updated_at) "
        "VALUES ('o1', 'aura', 'legacy-key', 'legacy.txt', 'text/plain', 'u1', "
        "'pending', 1, 1)"
    )
    conn.commit()
    return conn


def test_migration_adds_columns_and_preserves_rows(tmp_path):
    conn = _make_legacy_db(tmp_path / "legacy.db")
    # schema.sql runs first in production (CREATE TABLE IF NOT EXISTS), then migrations.
    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn, "sqlite")

    # New columns exist...
    assert {"role", "application_id", "space_id"} <= _columns(conn, "users")
    assert {
        "actor_kind", "actor_id", "application_id", "space_id", "environment",
        "intent_expires_at",
    } <= _columns(conn, "objects")

    # ...and old data is untouched, then backfilled into the default space.
    row = conn.execute("SELECT username, role, space_id FROM users WHERE id = 'u1'").fetchone()
    assert row[0] == "admin" and row[1] == "user" and row[2] == migrations.DEFAULT_SPACE_ID
    obj = conn.execute("SELECT bucket, space_id, environment, status FROM objects WHERE id = 'o1'").fetchone()
    assert obj[0] == "aura"
    assert obj[1] == migrations.DEFAULT_SPACE_ID
    assert obj[2] == migrations.DEFAULT_ENVIRONMENT
    assert obj[3] == "pending"

    # Default tenant model seeded exactly once.
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM buckets").fetchone()[0] == 1
    conn.close()


def test_migrations_are_idempotent(tmp_path):
    conn = _make_legacy_db(tmp_path / "legacy.db")
    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn, "sqlite")
    migrations.apply_migrations(conn, "sqlite")  # second run must be a no-op
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


def test_rollback_reads_original_columns(tmp_path):
    """Rollback strategy: the previous release only reads the original columns.

    Since migrations never drop or rewrite anything, a simulated old reader keeps
    working after the upgrade.
    """
    conn = _make_legacy_db(tmp_path / "legacy.db")
    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn, "sqlite")
    legacy_columns = "id, bucket, object_key, display_name, content_type, owner_id, status"
    row = conn.execute(f"SELECT {legacy_columns} FROM objects WHERE id = 'o1'").fetchone()
    assert row[0] == "o1" and row[6] == "pending"
    conn.close()
