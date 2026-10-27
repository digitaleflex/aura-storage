"""Additive schema migrations shared by the SQLite (dev/test) and PostgreSQL
(pilot) catalogue backends (#35, #38).

Design rules:
- **Additive only.** New tables live in ``schema.sql`` (CREATE TABLE IF NOT
  EXISTS). New columns are added here only when missing, so an existing
  catalogue keeps every row.
- **Idempotent.** Safe to run on every process start; a version row is recorded
  in ``schema_migrations``.
- **One documented exception.** ``_canonicalize_legacy_ids`` rewrites the three
  fixed ``0000…0001/2/3`` seed rows (application/space/bucket) to fresh UUID v4
  values and repoints their foreign keys. That is a deliberate one-time data
  migration, not an additive column change: see ``docs/DATA-MODEL.md`` and the
  identifier rule in ``api/ids.py``. It only ever touches those exact, known ids
  and is skipped once they are gone, so it stays idempotent.
- **Rollback.** Column additions add nothing the previous release reads, so the
  documented rollback for a bad release is "redeploy the previous image/volume".
  A restore-from-backup path is described in ``docs/BACKUP-RESTORE.md``.

Seeding creates the default application/space/bucket and backfills any legacy
user/object rows created before #35 so that current behaviour is preserved.
"""
import time

from . import ids

# Seed identity, resolved by name so the default rows carry a generated UUID v4
# instead of a fixed sentinel. Never used to derive an id.
DEFAULT_APPLICATION_NAME = "aura"
DEFAULT_SPACE_NAME = "default"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_BUCKET_NAME = "aura"

# Fixed ids written by releases before identifiers were canonicalized. Only ever
# read to detect and rewrite those rows; never inserted.
LEGACY_APPLICATION_ID = "00000000-0000-0000-0000-000000000001"
LEGACY_SPACE_ID = "00000000-0000-0000-0000-000000000002"
LEGACY_BUCKET_ID = "00000000-0000-0000-0000-000000000003"

SCHEMA_VERSION = "0010_object_analytics"

# (table, column, declaration) added only if absent. A constant DEFAULT is
# allowed by both engines on ADD COLUMN, so existing rows are filled with the
# default and new inserts keep working even before the backfill runs.
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
        # Transfer engine (M03): declared size is kept distinct from the verified
        # ``size_bytes`` (which stays -1 until commit), and an optional opaque
        # client idempotency key dedupes accidental double submits.
        ("expected_size_bytes", "BIGINT"),
        # Stable publication slug (kept across content replacement) and the
        # generated preview metadata.
        ("public_slug", "TEXT"),
        ("published_at", "INTEGER"),
        ("thumbnail_key", "TEXT"),
        ("duration_seconds", "REAL"),
        ("idempotency_key", "TEXT"),
        # Multipart session (#72): backend upload id while parts are being
        # sent (cleared once completed) and the server-chosen part size.
        ("multipart_upload_id", "TEXT"),
        ("multipart_part_bytes", "INTEGER"),
        # Transfer booster S5: optional zstd compression (never transparent).
        ("content_encoding", "TEXT"),
        # Asynchronous integrity check (N5): the object waits in 'verifying'
        # until a worker holding the lease has hashed it. The ETag seen at
        # commit detects bytes replaced before or during hashing.
        ("verify_etag", "TEXT"),
        ("verify_lease_until", "INTEGER"),
        ("verify_attempts", "INTEGER DEFAULT 0"),
        # Periodic integrity scrub: when the stored bytes were last re-hashed,
        # what that found ('ok', 'mismatch', 'missing') and the scrub lease.
        ("scrubbed_at", "INTEGER"),
        ("scrub_result", "TEXT"),
        ("scrub_lease_until", "INTEGER"),
        # Transfer booster S2: compare-and-set versioning + terminal-since for
        # automatic cleanup of terminal statuses.
        ("version", "INTEGER NOT NULL DEFAULT 1"),
        ("terminal_since", "INTEGER"),
        # Content revisions (docs/CONTENT-REVISIONS.md, phase 1 — schema only).
        # `revision_count` is a denormalised count for listing, `current_revision_id`
        # points at the latest archived generation and `replaced_at` records when the
        # head was last replaced, which is what the crash-recovery invariant keys on.
        # Nothing writes these yet.
        ("revision_count", "INTEGER DEFAULT 0"),
        ("current_revision_id", "TEXT"),
        ("replaced_at", "INTEGER"),
    ],
    # Master mode: a session-bound, short-lived elevation for bulk destructive
    # actions, granted only after re-entering the password (step-up).
    "sessions": [
        ("master_until", "INTEGER"),
    ],
    # #M04: a space is soft-disabled, never deleted. Pre-existing spaces are
    # backfilled to 'active' in `_seed`.
    "spaces": [
        ("status", "TEXT DEFAULT 'active'"),
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

    def has_column(self, table: str, column: str) -> bool:
        return column in self.columns(table)

    def get(self, sql: str, params: tuple = ()):
        """Return one row as a column->value dict, or ``None``."""
        if self.dialect == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(_translate_placeholders(sql), params)
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
        else:
            cur = self.conn.execute(sql, params)
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        return dict(zip(cols, row))

    def scalar(self, sql: str, params: tuple = ()):
        row = self.get(sql, params)
        return None if row is None else next(iter(row.values()))

    def commit(self):
        if self.dialect != "postgres":
            self.conn.commit()


def resolve_default_ids(conn, dialect: str = "sqlite"):
    """Return ``(application_id, space_id)`` of the seeded default tenant.

    Either element is ``None`` when the corresponding row is absent (for example
    on a catalogue that has not finished seeding). The rows are looked up by
    name because their ids are generated UUID v4 values, not fixed sentinels.
    """
    runner = _Runner(conn, dialect)
    application_id = runner.scalar(
        "SELECT id FROM applications WHERE name = ?", (DEFAULT_APPLICATION_NAME,)
    )
    if application_id is None:
        return None, None
    space_id = runner.scalar(
        "SELECT id FROM spaces WHERE application_id = ? AND name = ? "
        "AND environment = ? ORDER BY created_at LIMIT 1",
        (application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT),
    )
    return application_id, space_id


def apply_migrations(conn, dialect: str = "sqlite") -> None:
    """Add missing columns, canonicalize legacy ids, seed and record the version."""
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
    # Partial unique index: a slug is unique when set, and any number of rows
    # may have no slug. Supported by both SQLite and PostgreSQL.
    runner.exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_objects_slug "
        "ON objects(public_slug) WHERE public_slug IS NOT NULL"
    )
    # Every upload intent looks up its Idempotency-Key; without this index that
    # is a scan of the whole catalogue (14.8 ms at 100k rows, growing linearly).
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_objects_idem ON objects(actor_id, idempotency_key)"
    )
    # The background workers (verifier, scrubber yield, reconciler, upload
    # gating) only care about the few in-flight rows: a partial index keeps
    # those probes constant-time however large the catalogue grows.
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_objects_inflight ON objects(status, created_at) "
        "WHERE status IN ('pending', 'verifying')"
    )
    # `schema.sql` only runs when the database is created, so an upgraded
    # catalogue needs the revisions table created here. Kept byte-identical to
    # schema.sql: `tests/test_migrations.py` compares the two.
    runner.exec(
        "CREATE TABLE IF NOT EXISTS object_revisions ("
        "id TEXT PRIMARY KEY, "
        "object_id TEXT NOT NULL REFERENCES objects(id) ON DELETE RESTRICT, "
        "revision_number INTEGER NOT NULL, "
        "bucket TEXT NOT NULL, "
        "storage_key TEXT NOT NULL, "
        "size_bytes INTEGER NOT NULL, "
        "checksum_sha256 TEXT NOT NULL DEFAULT '', "
        "content_type TEXT NOT NULL DEFAULT 'application/octet-stream', "
        "created_at INTEGER NOT NULL, "
        "created_by_id TEXT, "
        "created_by_kind TEXT, "
        "keep_forever INTEGER NOT NULL DEFAULT 0, "
        "purged_at INTEGER, "
        "UNIQUE (object_id, revision_number))"
    )
    # Partner integrations: metadata only, the credential stays the service
    # identity. Created here for upgraded catalogues (schema.sql runs only on a
    # fresh database).
    runner.exec(
        "CREATE TABLE IF NOT EXISTS partner_sites ("
        "id TEXT PRIMARY KEY, "
        "space_id TEXT NOT NULL REFERENCES spaces(id), "
        "identity_id TEXT NOT NULL REFERENCES service_identities(id), "
        "name TEXT NOT NULL, "
        "site_url TEXT NOT NULL, "
        "default_ttl_seconds INTEGER, "
        "notes TEXT NOT NULL DEFAULT '', "
        "created_by TEXT, "
        "created_at INTEGER NOT NULL, "
        "updated_at INTEGER NOT NULL, "
        "UNIQUE (space_id, name))"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_partner_sites_space "
        "ON partner_sites(space_id)"
    )
    # Tags and ordered packs (Sprint 2). Additive tables for upgraded catalogues.
    runner.exec(
        "CREATE TABLE IF NOT EXISTS object_tags ("
        "object_id TEXT NOT NULL, tag TEXT NOT NULL, "
        "PRIMARY KEY (object_id, tag))"
    )
    runner.exec(
        "CREATE TABLE IF NOT EXISTS collections ("
        "id TEXT PRIMARY KEY, space_id TEXT NOT NULL, owner_id TEXT, "
        "slug TEXT NOT NULL, title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', published_at INTEGER, "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
        "UNIQUE (slug))"
    )
    runner.exec(
        "CREATE TABLE IF NOT EXISTS collection_items ("
        "collection_id TEXT NOT NULL, object_id TEXT NOT NULL, "
        "position INTEGER NOT NULL, PRIMARY KEY (collection_id, object_id))"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_object_tags_tag ON object_tags(tag)"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_collection_items_pos "
        "ON collection_items(collection_id, position)"
    )
    # Per-object monthly analytics (Sprint 3).
    runner.exec(
        "CREATE TABLE IF NOT EXISTS object_usage_monthly ("
        "object_id TEXT NOT NULL, period TEXT NOT NULL, "
        "views INTEGER NOT NULL DEFAULT 0, downloads INTEGER NOT NULL DEFAULT 0, "
        "share_opens INTEGER NOT NULL DEFAULT 0, "
        "egress_bytes BIGINT NOT NULL DEFAULT 0, last_access_at INTEGER, "
        "PRIMARY KEY (object_id, period))"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_object_usage_period "
        "ON object_usage_monthly(period)"
    )
    # Monthly quotas and usage per space: created here for upgraded catalogues.
    runner.exec(
        "CREATE TABLE IF NOT EXISTS space_quotas ("
        "space_id TEXT PRIMARY KEY REFERENCES spaces(id), "
        "storage_bytes INTEGER, "
        "egress_bytes_monthly INTEGER, "
        "updated_at INTEGER NOT NULL, "
        "updated_by TEXT)"
    )
    runner.exec(
        "CREATE TABLE IF NOT EXISTS space_usage_monthly ("
        "space_id TEXT NOT NULL REFERENCES spaces(id), "
        "period TEXT NOT NULL, "
        "egress_bytes INTEGER NOT NULL DEFAULT 0, "
        "download_intents INTEGER NOT NULL DEFAULT 0, "
        "preview_intents INTEGER NOT NULL DEFAULT 0, "
        "share_redemptions INTEGER NOT NULL DEFAULT 0, "
        "updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (space_id, period))"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_space_usage_period "
        "ON space_usage_monthly(period)"
    )
    # Byte counts must be 64-bit: a 5 GiB object already overflows PostgreSQL's
    # INTEGER (2 147 483 647), and quotas are set in TiB. SQLite INTEGER is
    # already 64-bit, so only PostgreSQL needs the cast. Idempotent: casting a
    # BIGINT column to BIGINT is a no-op.
    if runner.dialect == "postgres":
        for table, column in (
            ("objects", "size_bytes"),
            ("objects", "expected_size_bytes"),
            ("space_quotas", "storage_bytes"),
            ("space_quotas", "egress_bytes_monthly"),
            ("space_usage_monthly", "egress_bytes"),
        ):
            if column in runner.columns(table):
                runner.exec(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT"
                )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_revisions_object "
        "ON object_revisions(object_id, revision_number)"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_revisions_storage "
        "ON object_revisions(bucket, storage_key)"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_revisions_keep "
        "ON object_revisions(keep_forever) WHERE keep_forever = 1"
    )
    runner.exec(
        "CREATE INDEX IF NOT EXISTS idx_revisions_purge "
        "ON object_revisions(purged_at, created_at) WHERE purged_at IS NULL"
    )
    runner.commit()
    _canonicalize_legacy_ids(runner)
    _seed(runner)
    runner.exec(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        (SCHEMA_VERSION, int(time.time())),
    )
    runner.commit()


def _canonicalize_legacy_ids(runner: _Runner) -> None:
    """Rewrite the fixed ``0000…0001/2/3`` seed rows to UUID v4, once.

    Earlier releases seeded the default application/space/bucket with constant
    ids. This step renames each of those three rows to a fresh canonical UUID v4
    and repoints every foreign key, so an upgraded catalogue matches one seeded
    from scratch. It is skipped when the legacy ids are not present, so it is
    safe to run on every start. ``applications.name`` and ``spaces`` are unique,
    so the old row is renamed to a temporary label before the new id is inserted
    and the old row deleted — the foreign keys never point at a missing row.
    """
    _canonicalize_application(runner)
    _canonicalize_space(runner)
    _canonicalize_bucket(runner)


def _canonicalize_application(runner: _Runner) -> None:
    row = runner.get(
        "SELECT name, status, created_at FROM applications WHERE id = ?",
        (LEGACY_APPLICATION_ID,),
    )
    if row is None:
        return
    new_id = ids.new_id()
    runner.exec(
        "UPDATE applications SET name = ? WHERE id = ?",
        (f"__legacy__{new_id}", LEGACY_APPLICATION_ID),
    )
    runner.exec(
        "INSERT INTO applications (id, name, status, created_at) VALUES (?, ?, ?, ?)",
        (new_id, row["name"], row["status"], row["created_at"]),
    )
    for table in ("spaces", "users", "objects", "service_identities"):
        if runner.has_column(table, "application_id"):
            runner.exec(
                f"UPDATE {table} SET application_id = ? WHERE application_id = ?",
                (new_id, LEGACY_APPLICATION_ID),
            )
    runner.exec("DELETE FROM applications WHERE id = ?", (LEGACY_APPLICATION_ID,))


def _canonicalize_space(runner: _Runner) -> None:
    row = runner.get(
        "SELECT application_id, name, environment, created_at FROM spaces WHERE id = ?",
        (LEGACY_SPACE_ID,),
    )
    if row is None:
        return
    new_id = ids.new_id()
    runner.exec(
        "UPDATE spaces SET name = ? WHERE id = ?",
        (f"__legacy__{new_id}", LEGACY_SPACE_ID),
    )
    runner.exec(
        "INSERT INTO spaces (id, application_id, name, environment, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (new_id, row["application_id"], row["name"], row["environment"], row["created_at"]),
    )
    for table in ("buckets", "users", "objects", "service_identities"):
        if runner.has_column(table, "space_id"):
            runner.exec(
                f"UPDATE {table} SET space_id = ? WHERE space_id = ?",
                (new_id, LEGACY_SPACE_ID),
            )
    runner.exec("DELETE FROM spaces WHERE id = ?", (LEGACY_SPACE_ID,))


def _canonicalize_bucket(runner: _Runner) -> None:
    # Nothing references ``buckets.id`` (objects locate a bucket by name), so the
    # primary key can be updated in place without a temporary rename.
    row = runner.get("SELECT 1 FROM buckets WHERE id = ?", (LEGACY_BUCKET_ID,))
    if row is None:
        return
    runner.exec(
        "UPDATE buckets SET id = ? WHERE id = ?", (ids.new_id(), LEGACY_BUCKET_ID)
    )


def _seed(runner: _Runner) -> None:
    """Ensure the default application/space/bucket and backfill legacy rows.

    Ids are generated UUID v4 values. Each INSERT is guarded by a name lookup and
    carries ``ON CONFLICT DO NOTHING`` so two processes racing on first start
    cannot create duplicates; the winning row is then re-read.
    """
    now = int(time.time())
    application_id = runner.scalar(
        "SELECT id FROM applications WHERE name = ?", (DEFAULT_APPLICATION_NAME,)
    )
    if application_id is None:
        runner.exec(
            "INSERT INTO applications (id, name, status, created_at) "
            "VALUES (?, ?, 'active', ?) ON CONFLICT DO NOTHING",
            (ids.new_id(), DEFAULT_APPLICATION_NAME, now),
        )
        application_id = runner.scalar(
            "SELECT id FROM applications WHERE name = ?", (DEFAULT_APPLICATION_NAME,)
        )
    space_id = runner.scalar(
        "SELECT id FROM spaces WHERE application_id = ? AND name = ? "
        "AND environment = ? ORDER BY created_at LIMIT 1",
        (application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT),
    )
    if space_id is None:
        runner.exec(
            "INSERT INTO spaces (id, application_id, name, environment, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (ids.new_id(), application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT, now),
        )
        space_id = runner.scalar(
            "SELECT id FROM spaces WHERE application_id = ? AND name = ? "
            "AND environment = ? ORDER BY created_at LIMIT 1",
            (application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT),
        )
    bucket_id = runner.scalar(
        "SELECT id FROM buckets WHERE space_id = ? AND name = ?",
        (space_id, DEFAULT_BUCKET_NAME),
    )
    if bucket_id is None:
        runner.exec(
            "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
            "VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING",
            (ids.new_id(), space_id, DEFAULT_BUCKET_NAME, now),
        )
    # Backfill legacy users/objects so pre-#35 data keeps working.
    runner.exec("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''")
    # #M04: a space added before the status column is active by default.
    runner.exec("UPDATE spaces SET status = 'active' WHERE status IS NULL OR status = ''")
    runner.exec(
        "UPDATE users SET application_id = ? WHERE application_id IS NULL",
        (application_id,),
    )
    runner.exec("UPDATE users SET space_id = ? WHERE space_id IS NULL", (space_id,))
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
