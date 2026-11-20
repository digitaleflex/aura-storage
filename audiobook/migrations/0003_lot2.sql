-- Lot 2: contracts, listener territory, access-decision indexes.

ALTER TABLE listeners
  ADD COLUMN IF NOT EXISTS territory_code TEXT NOT NULL DEFAULT 'WORLD';

CREATE TABLE IF NOT EXISTS contracts (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  licensor TEXT NOT NULL DEFAULT '',
  territory_scope TEXT NOT NULL DEFAULT 'WORLD',
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','active','suspended','expired','terminated')),
  notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status, ends_at);

ALTER TABLE rights_windows
  ADD COLUMN IF NOT EXISTS contract_id UUID REFERENCES contracts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_rights_contract ON rights_windows(contract_id);

CREATE INDEX IF NOT EXISTS idx_access_decisions_denied
  ON access_decisions(decision, reason_code, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_decisions_listener_recent
  ON access_decisions(listener_id, resource_id, action, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_entitlements_listener_scope
  ON entitlements(listener_id, status, valid_until);
