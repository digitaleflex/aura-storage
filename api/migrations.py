"""Additive schema migrations shared by the SQLite (dev/test) and PostgreSQL
(pilot) catalogue backends (#35, #38).

Design rules:
- **Additive only.** New tables live in ``schema.sql`` (CREATE TABLE IF NOT
  EXISTS). New columns are added here only when missing, so an existing
  catalogue keeps every row.
- **Idempotent.** Safe to run on every process start; a version row is recorded
  in ``schema_migrations``.
- **Rollback.** Because no column, table or row is dropped or rewritten, the
  documented rollback for a bad release is "redeploy the previous image/volume":
  the older code simply ignores the added columns. A restore-from-backup path is
  described in ``docs/BACKUP-RESTORE.md``.

Seeding creates the default application/space/bucket and backfills any legacy
user/object rows created before #35 so that current behaviour is preserved.
"""
import time

DEFAULT_APPLICATION_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_SPACE_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_BUCKET_ID = "00000000-0000-0000-0000-000000000003"
DEFAULT_APPLICATION_NAME = "aura"
DEFAULT_SPACE_NAME = "default"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_BUCKET_NAME = "aura"
SCHEMA_VERSION = "0001_multiplatform"

# (table, column, declaration) added only if absent.
ADDED_COLUMNS = {
    "users": [
        ("role", "TEXT"),
        ("application_id", "TEXT"),
        ("space_id", "TEXT"),
    ],
    "objects": [
        ("actor_kind", "TEXT"),
        ("actor_id", "TEXT"),
        ("application_id", "TEXT"),
        ("space_id", "TEXT"),
        ("environment", "TEXT"),
        ("intent_expires_at", "INTEGER"),
    ],
}


def _translate_placeholders(sql: str) -> str:
    """Translate ``?`` placeholders to PostgreSQL ``%s`` (finding #10).

    A plain ``str.replace('?', '%s')`` would also rewrite a ``?`` that sits inside
    a string literal or a quoted identifier, corrupting the statement. This
    scanner only rewrites ``?`` characters that are actual placeholders, leaving
    quoted regions and the jsonb existence operators (``?|``, ``?&``) intact. A
    bare jsonb ``?`` operator is not supported in migration SQL — use
    ``jsonb_exists()`` if it is ever needed.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    quote = ""  # active quote character ("" when outside a quoted region)
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:  # escaped '' or ""
                    out.append(quote)
                    i += 2
                    continue
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            if i + 1 < n and sql[i + 1] in "|&":
                out.append(ch)  # jsonb operator (?| or ?&), not a placeholder
            else:
                out.append("%s")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class _Runner:
    """Thin dialect adapter: ``?`` placeholders are translated for PostgreSQL."""

    def __init__(self, conn, dialect: str):
        self.conn = conn
        self.dialect = dialect

    def exec(self, sql: str, params: tuple = ()):
        if self.dialect == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(_translate_placeholders(sql), params)
                return cur
        return self.conn.execute(sql, params)

    def columns(self, table: str) -> set:
        if self.dialect == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s",
                    (table,),
                )
                return {
                    (row["column_name"] if isinstance(row, dict) else row[0])
                    for row in cur.fetchall()
                }
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}

    def commit(self):
        if self.dialect != "postgres":
            self.conn.commit()


def apply_migrations(conn, dialect: str = "sqlite") -> None:
    """Add missing columns, seed the default tenant model, record the version."""
    runner = _Runner(conn, dialect)
    for table, columns in ADDED_COLUMNS.items():
        existing = runner.columns(table)
        if not existing:
            continue  # schema.sql has not run yet; nothing to alter
        for name, declaration in columns:
            if name not in existing:
                runner.exec(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    runner.commit()
    runner.exec("CREATE INDEX IF NOT EXISTS idx_objects_space ON objects(space_id, status)")
    runner.commit()
    _seed(runner)
    runner.exec(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        (SCHEMA_VERSION, int(time.time())),
    )
    runner.commit()


def _seed(runner: _Runner) -> None:
    """Ensure the default application/space/bucket and backfill legacy rows."""
    now = int(time.time())
    runner.exec(
        "INSERT INTO applications (id, name, status, created_at) "
        "VALUES (?, ?, 'active', ?) ON CONFLICT DO NOTHING",
        (DEFAULT_APPLICATION_ID, DEFAULT_APPLICATION_NAME, now),
    )
    runner.exec(
        "INSERT INTO spaces (id, application_id, name, environment, created_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (DEFAULT_SPACE_ID, DEFAULT_APPLICATION_ID, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT, now),
    )
    runner.exec(
        "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
        "VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING",
        (DEFAULT_BUCKET_ID, DEFAULT_SPACE_ID, DEFAULT_BUCKET_NAME, now),
    )
    # Backfill legacy users/objects so pre-#35 data keeps working.
    runner.exec("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''")
    runner.exec(
        "UPDATE users SET application_id = ? WHERE application_id IS NULL",
        (DEFAULT_APPLICATION_ID,),
    )
    runner.exec("UPDATE users SET space_id = ? WHERE space_id IS NULL", (DEFAULT_SPACE_ID,))
    runner.exec(
        "UPDATE objects SET space_id = "
        "(SELECT space_id FROM users WHERE users.id = objects.owner_id) "
        "WHERE space_id IS NULL"
    )
    runner.exec(
        "UPDATE objects SET application_id = "
        "(SELECT application_id FROM users WHERE users.id = objects.owner_id) "
        "WHERE application_id IS NULL"
    )
    runner.exec(
        "UPDATE objects SET environment = ? WHERE environment IS NULL",
        (DEFAULT_ENVIRONMENT,),
    )
