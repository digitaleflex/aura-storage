-- Lot 1 completion: categories, editorial/personal collections, admin flag.

ALTER TABLE listeners ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS categories (
  id UUID PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS work_categories (
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (work_id, category_id)
);
CREATE INDEX IF NOT EXISTS idx_work_categories_category
  ON work_categories(category_id, position);

CREATE TABLE IF NOT EXISTS editorial_collections (
  id UUID PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','published','archived')),
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS editorial_collection_items (
  collection_id UUID NOT NULL REFERENCES editorial_collections(id) ON DELETE CASCADE,
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE RESTRICT,
  position INTEGER NOT NULL DEFAULT 0,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (collection_id, edition_id),
  UNIQUE (collection_id, position)
);
CREATE INDEX IF NOT EXISTS idx_editorial_collection_items_edition
  ON editorial_collection_items(edition_id);

CREATE TABLE IF NOT EXISTS personal_collections (
  id UUID PRIMARY KEY,
  listener_id UUID NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_personal_collections_listener
  ON personal_collections(listener_id, created_at DESC);

CREATE TABLE IF NOT EXISTS personal_collection_items (
  collection_id UUID NOT NULL REFERENCES personal_collections(id) ON DELETE CASCADE,
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE RESTRICT,
  position INTEGER NOT NULL DEFAULT 0,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (collection_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_personal_collection_items_collection
  ON personal_collection_items(collection_id, position, added_at);
