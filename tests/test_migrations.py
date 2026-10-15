"""Issue #35: additive migrations preserve existing catalogue data and are idempotent.

Runs entirely on a disposable SQLite file; no PostgreSQL or S3 endpoint needed.
"""
import sqlite3

from api import ids, migrations
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
    default_application_id, default_space_id = migrations.resolve_default_ids(conn)
    assert ids.is_canonical(default_application_id)
    assert ids.is_canonical(default_space_id)
    row = conn.execute("SELECT username, role, space_id FROM users WHERE id = 'u1'").fetchone()
    assert row[0] == "admin" and row[1] == "user" and row[2] == default_space_id
    obj = conn.execute("SELECT bucket, space_id, environment, status FROM objects WHERE id = 'o1'").fetchone()
    assert obj[0] == "aura"
    assert obj[1] == default_space_id
    assert obj[2] == migrations.DEFAULT_ENVIRONMENT
    assert obj[3] == "pending"

    # Default tenant model seeded exactly once, with generated UUID v4 ids.
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM buckets").fetchone()[0] == 1
    app_id = conn.execute("SELECT id FROM applications").fetchone()[0]
    bucket_id = conn.execute("SELECT id FROM buckets").fetchone()[0]
    assert ids.is_canonical(app_id) and ids.is_canonical(bucket_id)
    conn.close()


def test_migrations_are_idempotent(tmp_path):
    conn = _make_legacy_db(tmp_path / "legacy.db")
    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn, "sqlite")
    migrations.apply_migrations(conn, "sqlite")  # second run must be a no-op
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


def _make_sentinel_db(path):
    """A catalogue seeded by an earlier release with the fixed ``0000…`` ids."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO applications (id, name, status, created_at) "
        "VALUES (?, 'aura', 'active', 1)",
        (migrations.LEGACY_APPLICATION_ID,),
    )
    conn.execute(
        "INSERT INTO spaces (id, application_id, name, environment, created_at) "
        "VALUES (?, ?, 'default', 'prod', 1)",
        (migrations.LEGACY_SPACE_ID, migrations.LEGACY_APPLICATION_ID),
    )
    conn.execute(
        "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
        "VALUES (?, ?, 'aura', 1, 1)",
        (migrations.LEGACY_BUCKET_ID, migrations.LEGACY_SPACE_ID),
    )
    conn.execute(
        "INSERT INTO service_identities (id, application_id, space_id, name, "
        "secret_hash, scopes, created_at) VALUES ('svc-1', ?, ?, 'svc', 'h', '', 1)",
        (migrations.LEGACY_APPLICATION_ID, migrations.LEGACY_SPACE_ID),
    )
    conn.execute(
        "INSERT INTO users (id, username, pass_hash, created_at) "
        "VALUES ('u1', 'admin', 'hash', 1)"
    )
    conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, status, created_at, updated_at) "
        "VALUES ('o1', 'aura', 'k', 'a.txt', 'text/plain', 'u1', 'pending', 1, 1)"
    )
    conn.commit()
    return conn


def test_legacy_sentinel_ids_are_canonicalized(tmp_path):
    """The one-time rewrite replaces the fixed seed ids with UUID v4 everywhere."""
    conn = _make_sentinel_db(tmp_path / "sentinel.db")
    migrations.apply_migrations(conn, "sqlite")

    app_id, space_id = migrations.resolve_default_ids(conn)
    assert ids.is_canonical(app_id) and ids.is_canonical(space_id)
    assert app_id != migrations.LEGACY_APPLICATION_ID
    assert space_id != migrations.LEGACY_SPACE_ID

    # The sentinel rows are gone; the unique names and counts survive.
    for table, legacy in (
        ("applications", migrations.LEGACY_APPLICATION_ID),
        ("spaces", migrations.LEGACY_SPACE_ID),
        ("buckets", migrations.LEGACY_BUCKET_ID),
    ):
        assert conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE id = ?", (legacy,)
        ).fetchone()[0] == 0
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    assert conn.execute("SELECT name FROM applications").fetchone()[0] == "aura"
    assert conn.execute("SELECT name FROM spaces").fetchone()[0] == "default"
    assert conn.execute("SELECT name FROM buckets").fetchone()[0] == "aura"

    # Every foreign key was repointed to the new ids.
    assert conn.execute("SELECT application_id FROM spaces").fetchone()[0] == app_id
    assert conn.execute("SELECT space_id FROM buckets").fetchone()[0] == space_id
    assert conn.execute(
        "SELECT application_id, space_id FROM service_identities WHERE id = 'svc-1'"
    ).fetchone() == (app_id, space_id)
    assert conn.execute(
        "SELECT application_id, space_id FROM users WHERE id = 'u1'"
    ).fetchone() == (app_id, space_id)
    assert conn.execute(
        "SELECT application_id, space_id FROM objects WHERE id = 'o1'"
    ).fetchone() == (app_id, space_id)
    assert ids.is_canonical(conn.execute("SELECT id FROM buckets").fetchone()[0])
    conn.close()


def test_canonicalization_is_idempotent(tmp_path):
    conn = _make_sentinel_db(tmp_path / "sentinel.db")
    migrations.apply_migrations(conn, "sqlite")
    first = migrations.resolve_default_ids(conn)
    migrations.apply_migrations(conn, "sqlite")  # second run must not re-mint ids
    assert migrations.resolve_default_ids(conn) == first
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM buckets").fetchone()[0] == 1
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


# ---------------------------------------------------------------------------
# #10: the postgres placeholder translation must be quote/operator aware.
# ---------------------------------------------------------------------------
def test_placeholder_translation_replaces_only_real_placeholders():
    t = migrations._translate_placeholders
    assert t("SELECT * FROM t WHERE a = ? AND b = ?") == \
        "SELECT * FROM t WHERE a = %s AND b = %s"
    # A '?' inside a string literal or a quoted identifier is preserved.
    assert t("UPDATE t SET note = 'why?' WHERE id = ?") == \
        "UPDATE t SET note = 'why?' WHERE id = %s"
    assert t("SELECT 'it''s ok?' WHERE id = ?") == \
        "SELECT 'it''s ok?' WHERE id = %s"
    assert t('SELECT "weird?col" FROM t WHERE id = ?') == \
        'SELECT "weird?col" FROM t WHERE id = %s'
    # jsonb existence operators are not placeholders.
    assert t("SELECT data ?| array['a'] FROM t WHERE id = ?") == \
        "SELECT data ?| array['a'] FROM t WHERE id = %s"
    assert t("SELECT data ?& array['a'] FROM t WHERE id = ?") == \
        "SELECT data ?& array['a'] FROM t WHERE id = %s"
    # No placeholders, nothing to do.
    assert t("SELECT 1") == "SELECT 1"


class _FakeCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql, self.params = sql, params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakePostgresConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.executed = []

    def cursor(self):
        return self.cur

    def execute(self, sql, params=()):  # sqlite-style path
        self.executed.append((sql, params))
        return self


def test_runner_translates_placeholders_for_postgres_only():
    pg = _FakePostgresConn()
    migrations._Runner(pg, "postgres").exec(
        "UPDATE t SET note = 'a?b' WHERE id = ?", ("1",)
    )
    assert pg.cur.sql == "UPDATE t SET note = 'a?b' WHERE id = %s"
    assert pg.cur.params == ("1",)

    sq = _FakePostgresConn()
    migrations._Runner(sq, "sqlite").exec("UPDATE t SET x = ? WHERE id = ?", (1, 2))
    assert sq.executed == [("UPDATE t SET x = ? WHERE id = ?", (1, 2))]
