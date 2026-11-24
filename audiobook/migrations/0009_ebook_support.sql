-- M4 foundation: one edition is either an audiobook or a digital book.
-- Existing rows remain audiobooks and keep their current publication rules.

ALTER TABLE editions
  ADD COLUMN IF NOT EXISTS publication_kind TEXT NOT NULL DEFAULT 'audiobook';
ALTER TABLE editions DROP CONSTRAINT IF EXISTS editions_publication_kind_check;
ALTER TABLE editions ADD CONSTRAINT editions_publication_kind_check
  CHECK (publication_kind IN ('audiobook','ebook'));

ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_kind_check;
ALTER TABLE assets ADD CONSTRAINT assets_kind_check
  CHECK (kind IN ('source','hls','cover','subtitle','derivative','ebook'));

CREATE TABLE IF NOT EXISTS ebook_assets (
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  format TEXT NOT NULL CHECK (format IN ('epub','pdf')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (edition_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_ebook_assets_edition ON ebook_assets(edition_id);
