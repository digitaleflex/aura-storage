-- Add schema_version to outbox events (required by event envelope).

ALTER TABLE outbox_events
  ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;
