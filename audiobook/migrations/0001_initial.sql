-- Audiobook bounded context — initial schema (PostgreSQL).
-- Applied inside the schema selected by AUDIOBOOK_SCHEMA (default: audiobook).
-- All timestamps are UTC (timestamptz). All money, when introduced, uses integer
-- minor units. This migration is additive and idempotent.

CREATE TABLE IF NOT EXISTS listeners (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL,
  email_normalized TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','suspended','blocked','pending_deletion','deleted')),
  locale TEXT NOT NULL DEFAULT 'fr',
  timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deletion_requested_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS listener_identities (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  subject TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, subject)
);

CREATE TABLE IF NOT EXISTS devices (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('pending','active','lost','revoked')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_devices_listener ON devices(listener_id, status);

CREATE TABLE IF NOT EXISTS listener_sessions (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
  token_hash TEXT NOT NULL UNIQUE,
  csrf_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_listener_sessions_listener
  ON listener_sessions(listener_id, expires_at);

CREATE TABLE IF NOT EXISTS contributors (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  sort_name TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS works (
  id UUID PRIMARY KEY,
  title TEXT NOT NULL,
  original_title TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  publication_year INTEGER,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','approved','retired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  retired_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS work_contributors (
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  contributor_id UUID NOT NULL REFERENCES contributors(id) ON DELETE RESTRICT,
  role TEXT NOT NULL CHECK (role IN ('author','narrator','translator','adapter','illustrator','other')),
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (work_id, contributor_id, role)
);
CREATE INDEX IF NOT EXISTS idx_work_contributors_role
  ON work_contributors(work_id, role, position);

CREATE TABLE IF NOT EXISTS assets (
  id UUID PRIMARY KEY,
  storage_object_id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'source'
    CHECK (kind IN ('source','hls','cover','subtitle','derivative')),
  content_type TEXT NOT NULL DEFAULT '',
  size_bytes BIGINT NOT NULL DEFAULT -1,
  checksum_sha256 TEXT NOT NULL DEFAULT '',
  duration_ms BIGINT,
  codec TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'initiated'
    CHECK (status IN ('initiated','uploaded','quarantined','validating','ready','rejected','blocked','superseded','deleted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ready_at TIMESTAMPTZ,
  blocked_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);

CREATE TABLE IF NOT EXISTS editions (
  id UUID PRIMARY KEY,
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE RESTRICT,
  title TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  publisher TEXT NOT NULL DEFAULT '',
  publication_date DATE,
  description TEXT NOT NULL DEFAULT '',
  slug TEXT NOT NULL UNIQUE,
  duration_ms BIGINT NOT NULL DEFAULT 0,
  cover_asset_id UUID,
  access_model TEXT NOT NULL DEFAULT 'free'
    CHECK (access_model IN ('free','paid','subscription')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','metadata_complete','assets_pending','validation','approved','published','suspended','retired')),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ,
  suspended_at TIMESTAMPTZ,
  retired_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_editions_work ON editions(work_id);
CREATE INDEX IF NOT EXISTS idx_editions_status ON editions(status, published_at);

CREATE TABLE IF NOT EXISTS tracks (
  id UUID PRIMARY KEY,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  start_ms BIGINT NOT NULL DEFAULT 0,
  end_ms BIGINT NOT NULL DEFAULT 0,
  asset_id UUID REFERENCES assets(id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','ready','unavailable','blocked')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (edition_id, position),
  CHECK (end_ms >= start_ms)
);
CREATE INDEX IF NOT EXISTS idx_tracks_edition ON tracks(edition_id, position);

CREATE TABLE IF NOT EXISTS chapters (
  id UUID PRIMARY KEY,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  start_ms BIGINT NOT NULL,
  end_ms BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (edition_id, position),
  CHECK (end_ms > start_ms)
);
CREATE INDEX IF NOT EXISTS idx_chapters_edition ON chapters(edition_id, position);

CREATE TABLE IF NOT EXISTS rights_windows (
  id UUID PRIMARY KEY,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  territory_code TEXT NOT NULL DEFAULT 'WORLD',
  channel TEXT NOT NULL DEFAULT 'stream'
    CHECK (channel IN ('stream','download','preview')),
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned','active','suspended','expired','terminated')),
  max_downloads INTEGER,
  allowed_formats TEXT[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_rights_edition
  ON rights_windows(edition_id, status, starts_at, ends_at);

CREATE TABLE IF NOT EXISTS library_entries (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE RESTRICT,
  preferred_edition_id UUID REFERENCES editions(id) ON DELETE SET NULL,
  source TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('manual','purchase','subscription','import','promotion')),
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  removed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_library_active
  ON library_entries(listener_id, work_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_library_listener
  ON library_entries(listener_id, removed_at);

CREATE TABLE IF NOT EXISTS favorites (
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (listener_id, work_id)
);

CREATE TABLE IF NOT EXISTS entitlements (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL
    CHECK (source_type IN ('purchase','subscription','free','promotion','manual','personal_import')),
  source_id TEXT NOT NULL DEFAULT '',
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('edition','work','plan_catalog','personal_asset')),
  scope_id TEXT NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL,
  valid_until TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','active','suspended','revoked','expired','canceled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ,
  revocation_reason TEXT,
  CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlement_source
  ON entitlements(listener_id, source_type, source_id, scope_type, scope_id)
  WHERE status IN ('pending','active','suspended');
CREATE INDEX IF NOT EXISTS idx_entitlements_active
  ON entitlements(listener_id, scope_type, scope_id, status, valid_until);

CREATE TABLE IF NOT EXISTS access_decisions (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  resource_type TEXT NOT NULL DEFAULT 'edition',
  resource_id UUID NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('stream','preview','download')),
  decision TEXT NOT NULL CHECK (decision IN ('allow','deny')),
  reason_code TEXT NOT NULL,
  sources JSONB NOT NULL DEFAULT '[]'::jsonb,
  policy_version TEXT NOT NULL,
  territory_code TEXT NOT NULL DEFAULT 'WORLD',
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_access_decisions_listener
  ON access_decisions(listener_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_decisions_resource
  ON access_decisions(resource_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS playback_sessions (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
  state TEXT NOT NULL DEFAULT 'active'
    CHECK (state IN ('active','paused','stale','ended','abandoned')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  client_started_at TIMESTAMPTZ,
  last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_client_seq INTEGER NOT NULL DEFAULT 0,
  active_lease_until TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_playback_active
  ON playback_sessions(listener_id, edition_id) WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_playback_listener
  ON playback_sessions(listener_id, edition_id, started_at DESC);

CREATE TABLE IF NOT EXISTS listening_events (
  id UUID PRIMARY KEY,
  event_id UUID NOT NULL UNIQUE,
  session_id UUID NOT NULL REFERENCES playback_sessions(id) ON DELETE CASCADE,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  track_id UUID REFERENCES tracks(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('start','heartbeat','seek','pause','resume','ended','takeover')),
  client_seq INTEGER NOT NULL,
  occurred_at_client TIMESTAMPTZ,
  received_at_server TIMESTAMPTZ NOT NULL DEFAULT now(),
  position_ms BIGINT NOT NULL,
  duration_ms BIGINT,
  playback_rate NUMERIC(4,2) NOT NULL DEFAULT 1.0,
  applied BOOLEAN NOT NULL DEFAULT true,
  reason_code TEXT NOT NULL DEFAULT 'applied',
  UNIQUE (session_id, client_seq),
  CHECK (position_ms >= 0)
);
CREATE INDEX IF NOT EXISTS idx_listening_events_session
  ON listening_events(session_id, client_seq);
CREATE INDEX IF NOT EXISTS idx_listening_events_listener
  ON listening_events(listener_id, edition_id, received_at_server DESC);

CREATE TABLE IF NOT EXISTS listening_progress (
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  position_ms BIGINT NOT NULL DEFAULT 0,
  track_id UUID REFERENCES tracks(id) ON DELETE SET NULL,
  active_session_id UUID,
  last_event_id UUID,
  version INTEGER NOT NULL DEFAULT 1,
  completed_at TIMESTAMPTZ,
  last_completed_position_ms BIGINT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (listener_id, edition_id),
  CHECK (position_ms >= 0)
);

CREATE TABLE IF NOT EXISTS outbox_events (
  id BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','processed','failed','dead_letter')),
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
  ON outbox_events(status, available_at, id);

CREATE TABLE IF NOT EXISTS audit_events (
  id UUID PRIMARY KEY,
  actor_type TEXT NOT NULL,
  actor_id TEXT,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('success','denied','failed')),
  reason TEXT NOT NULL DEFAULT '',
  request_id TEXT NOT NULL DEFAULT '',
  before_hash TEXT,
  after_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_type, actor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  request_hash TEXT NOT NULL DEFAULT '',
  response JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
