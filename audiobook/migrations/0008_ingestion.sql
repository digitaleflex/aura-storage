-- M2 ingestion items. Files are staged, validated and imported through AURA.
-- This migration does not publish anything and never exposes staging paths.

CREATE TABLE IF NOT EXISTS ingest_batches (
  id UUID PRIMARY KEY,
  source TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_items (
  id UUID PRIMARY KEY,
  batch_id UUID REFERENCES ingest_batches(id) ON DELETE SET NULL,
  source TEXT NOT NULL CHECK (source IN ('manual','shelfmark','partner')),
  source_ref TEXT NOT NULL DEFAULT '',
  original_filename TEXT NOT NULL,
  staging_path TEXT NOT NULL,
  declared_content_type TEXT NOT NULL DEFAULT '',
  detected_content_type TEXT NOT NULL DEFAULT '',
  size_bytes BIGINT NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL CHECK (kind IN ('audiobook','ebook')),
  state TEXT NOT NULL DEFAULT 'received'
    CHECK (state IN ('received','validating','awaiting_rights','importing',
                     'retryable_failed','completed','rejected')),
  idempotency_key TEXT NOT NULL UNIQUE,
  storage_object_id TEXT,
  asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
  target_edition_id UUID REFERENCES editions(id) ON DELETE SET NULL,
  track_position INTEGER,
  track_title TEXT NOT NULL DEFAULT '',
  duration_ms BIGINT,
  error_code TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  request_id TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (source, source_ref, sha256)
);
CREATE INDEX IF NOT EXISTS idx_ingest_items_state
  ON ingest_items(state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_items_sha
  ON ingest_items(sha256);
