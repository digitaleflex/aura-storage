-- M1 metadata candidates and provenance. Suggestions only: this migration
-- does not grant rights, create catalogue entries or publish anything.

CREATE TABLE IF NOT EXISTS metadata_candidates (
  id UUID PRIMARY KEY,
  provider TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'unknown'
    CHECK (kind IN ('ebook','audiobook','unknown')),
  normalized_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_hash TEXT NOT NULL,
  confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
  fetched_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'new'
    CHECK (status IN ('new','applied','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_id)
);
CREATE INDEX IF NOT EXISTS idx_metadata_candidates_status
  ON metadata_candidates(status, fetched_at DESC);

CREATE TABLE IF NOT EXISTS external_identifiers (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('work','edition')),
  entity_id UUID NOT NULL,
  provider TEXT NOT NULL,
  id_kind TEXT NOT NULL,
  external_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, id_kind, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_identifiers_entity
  ON external_identifiers(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS metadata_reviews (
  id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES metadata_candidates(id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('link_existing','reject')),
  target_entity_type TEXT,
  target_entity_id UUID,
  reviewer_id TEXT NOT NULL DEFAULT 'admin',
  reason TEXT NOT NULL DEFAULT '',
  request_id TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_metadata_reviews_candidate
  ON metadata_reviews(candidate_id, created_at DESC);
