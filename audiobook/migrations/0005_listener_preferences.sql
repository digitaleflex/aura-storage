-- Listener preferences for personalized recommendations.

CREATE TABLE IF NOT EXISTS listener_preferences (
  listener_id UUID PRIMARY KEY REFERENCES listeners(id) ON DELETE CASCADE,
  preferred_languages TEXT[] NOT NULL DEFAULT '{}',
  preferred_category_slugs TEXT[] NOT NULL DEFAULT '{}',
  preferred_authors TEXT[] NOT NULL DEFAULT '{}',
  preferred_narrators TEXT[] NOT NULL DEFAULT '{}',
  min_duration_ms BIGINT,
  max_duration_ms BIGINT,
  prefer_completed BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (min_duration_ms IS NULL OR min_duration_ms >= 0),
  CHECK (max_duration_ms IS NULL OR max_duration_ms >= 0),
  CHECK (
    min_duration_ms IS NULL OR max_duration_ms IS NULL
    OR min_duration_ms <= max_duration_ms
  )
);

CREATE INDEX IF NOT EXISTS idx_work_categories_work
  ON work_categories(work_id, category_id);
