-- AURA catalogue schema, shared by SQLite (#18) and PostgreSQL (#19).
-- Column types use TEXT/INTEGER portable across both engines.
-- Ownership references the Better Auth "user"(id) by convention (no hard FK:
-- Better Auth migrates its tables independently; integrity is enforced by the API).
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  parent_id TEXT,
  name TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS objects (
  id TEXT PRIMARY KEY,
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT -1,
  checksum_sha256 TEXT NOT NULL DEFAULT '',
  folder_id TEXT REFERENCES folders(id),
  owner_id TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'private',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (bucket, object_key)
);
CREATE INDEX IF NOT EXISTS idx_objects_owner ON objects(owner_id, status);
