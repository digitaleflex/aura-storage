# Content revisions with retention

**Status: PROPOSED — not implemented; pending owner approval.**

Repo: `/home/aura-admin/aura-storage` (FastAPI + PostgreSQL/SQLite, SeaweedFS 4.48 S3, React). Design only.

## 1) Where revisions live — pick one

**Decision (proposed): (b) `object_revisions` table + copy-on-write S3 keys managed by the app (separate key per revision), NOT S3 native versioning on the bucket.**

Rationale:
- SeaweedFS 4.48 S3 compatibility: versioning is mentioned in the ecosystem docs but **not configured or used** in this stack (`docker-compose.yml:153-195` has no `-s3.versioning`/bucket versioning config; `config/seaweedfs/s3.json` not read here shows no versioning). The audits call out “no object versioning / object-lock” as absent/unknown exploitability (`docs/engineering/transfer-engine-audit.md:320-321, 412`, `.slim/deepwork/transfer-engine/audit.md:315-316,407,509`). The app never lists/deletes old versions. **Assume SeaweedFS 4.48 S3 bucket versioning is not enabled/configurable safely here or not relied on**; do not depend on it.
- App currently assumes **one live key per object**: `objects.object_key` is unique with bucket via `UNIQUE(bucket,object_key)` (`api/schema.sql:49`), `has_object` checks that pair (`api/db.py:329-335`, `api/db_pg.py:301-307`), `object_states_for_keys` maps keys to rows (`api/db.py:724-744`, `api/db_pg.py:643-660`), `reconcile_reverse` treats keys with no catalogue row as orphans (`api/lifecycle.py:99-144`), storage-orphan scans/reporting (`api/storage_reconcile.py:43-109`, `api/main.py:2304-2367`, tests `tests/test_storage_orphans.py`), and scrubber/verifier/hash against `objects.bucket/object_key` (`api/scrubber.py:48-69`, `api/main.py:1449-1535, 1896-1954`). **S3 native versioning would break all of these**: old versions appear as extra objects/versions (orphan scans would see them as unaccounted), `list_objects_v2` would need version-aware handling, delete/purge must target a specific version, and “one live key per object” invariants fail. Reconciliation/orphan sweeps would misclassify versions as storage orphans or miss deletes. Also the app has no code to enumerate/delete non-current versions.
- (c) revisions table storing only metadata while old bytes stay under versioned keys managed by app is effectively (b). (a) is not feasible to integrate safely now.

So **use app-managed copy-on-write keys**: on overwrite/replace, move old bytes to a revision key (or copy then delete old) and create `object_revisions` row; head stays on `objects.object_key`. This keeps `objects` as head metadata, preserves existing one-key assumptions for head, and makes old versions explicit to the catalogue.

## 2) Data model — concrete DDL, additive migrations

**Additive migration style**: follow `api/migrations.py` — new tables in `schema.sql` as `CREATE TABLE IF NOT EXISTS`, new columns via `ADDED_COLUMNS` + `ALTER TABLE ... ADD COLUMN`, indexes created after columns exist, idempotent, record in `schema_migrations` (`api/migrations.py:5-19,42-96,219-251`). Both SQLite and Postgres must work; use portable types (TEXT/INTEGER) and `?`/`%s` via `_translate_placeholders` (`api/migrations.py:98-137`). Parity required (`tests/test_pg_parity.py`).

### New table `object_revisions` (add to `schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS object_revisions (
  id TEXT PRIMARY KEY,                -- UUID v4
  object_id TEXT NOT NULL REFERENCES objects(id) ON DELETE RESTRICT,
  revision_number INTEGER NOT NULL,   -- monotonic per object (1-based), head becomes rev N after create
  bucket TEXT NOT NULL,
  storage_key TEXT NOT NULL,          -- S3 key for these bytes (old object_key or key/vN)
  size_bytes INTEGER NOT NULL,
  checksum_sha256 TEXT NOT NULL,
  content_type TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  created_by_id TEXT,                -- actor who caused this revision (upload/replace)
  created_by_kind TEXT,
  keep_forever INTEGER NOT NULL DEFAULT 0,
  purged_at INTEGER                  -- set when bytes deleted by retention/purge
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_object_revisions_obj_rev ON object_revisions(object_id, revision_number);
CREATE INDEX IF NOT EXISTS idx_object_revisions_object ON object_revisions(object_id, created_at);
CREATE INDEX IF NOT EXISTS idx_object_revisions_storage ON object_revisions(bucket, storage_key);
CREATE INDEX IF NOT EXISTS idx_object_revisions_keep ON object_revisions(keep_forever) WHERE keep_forever = 1;
CREATE INDEX IF NOT EXISTS idx_object_revisions_purge ON object_revisions(purged_at, created_at) WHERE purged_at IS NULL;
```

Notes:
- `object_id` FK with `ON DELETE RESTRICT` so deleting object row requires revisions handled explicitly (see purge). 
- `storage_key` is the actual S3 key holding bytes for this revision (app-managed). 
- `keep_forever` is integer flag (0/1) like `buckets.is_default` (`api/schema.sql:73`).
- Uniqueness `(object_id, revision_number)`. Indexes support listing per object and retention sweeps.

### Additive columns to `objects` (via `migrations.ADDED_COLUMNS`)

```python
# in ADDED_COLUMNS["objects"]
("revision_count", "INTEGER DEFAULT 0"),      # denorm for listing
("current_revision_id", "TEXT"),              # points to latest revision row (or NULL for first version)
("replaced_at", "INTEGER"),                   # when head was replaced last
```

Also consider `revision_retention_days`/`revision_retention_count` not needed as global defaults; policy is per-object defaults + keep_forever. Do **not** repurpose `objects.version` (it’s optimistic-concurrency counter incremented on STATUS changes per `api/db.py:750-767`, `api/db_pg.py:664-681` — rename not necessary, leave as-is; it must keep its meaning).

### Migration behavior
- Bump `SCHEMA_VERSION` (e.g. `"0005_object_revisions"`) in `api/migrations.py:40` and insert into `schema_migrations` as before.
- Add indexes in `apply_migrations` after ensuring columns exist (`api/migrations.py:230-243`).
- Backfill: for existing `objects` with `status IN ('available','deleted')`, create revision 0 or rev 1 representing current head bytes if we want history? **No** — requirement says “there are no content revisions today”. Do **not** auto-create revisions for existing objects (would duplicate storage/cost and change semantics). Revisions only created going forward on overwrite/replace operations. Set `revision_count=0`, `current_revision_id=NULL` for existing rows.

## 3) Retention policy — concrete defaults

**Defaults (mature products):** Google Drive-like — **keep up to 100 revisions OR 30 days**, whichever comes first? Or “30 days or 100 revisions”. Propose **default: keep last 100 revisions per object, and/or revisions newer than 30 days; also allow keep_forever**. Drive states “up to 100 revisions” and trash retention varies; common is 30 days for trash, revisions often retained longer with caps. **Concrete defaults:**
- `REVISION_RETENTION_DAYS_DEFAULT = 30`
- `REVISION_RETENTION_MAX_COUNT_DEFAULT = 100` (counted **per object**)
- `REVISION_KEEP_FOREVER_MAX_PER_USER = 200` (Drive-like up to 200 keep-forever; enforce cap)
- Revisions created by overwriting an **available** object count toward caps. 

**Counting:** **per object** (not per user). Rationale: different objects have different importance; user-level caps are coarse and easy to game. Enforce `keep_forever` cap **per user** (max 200) to prevent abuse.

**Survival on purge/delete:**
- **Soft delete (`DELETE /objects/{oid}` sets status `deleted`, `api/main.py:1674-1688`)**: revisions remain intact (bytes stay in storage under revision keys). Object can be restored via `POST /objects/{oid}/restore` which sets status back to `available` if `size_bytes>=0` (`api/main.py:1691-1708`) — head is still the current key; revisions stay for history.
- **Trash empty / purge**: when object is purged permanently (`POST /objects/{oid}/purge`, `api/main.py:1868-1883`, `lifecycle.purge_object` `api/lifecycle.py:147-192`), **revisions do NOT survive by default**. Purge must delete all revision bytes and revision rows (or mark purged). **Owner decision required** (see Open questions): whether to block purge if any revision has `keep_forever=1` and require explicit deletion of those revisions first, or handle otherwise.
- **Retention purge algorithm:** background job (extend `reconcile_terminal` or new `reconcile_revisions`, run by reconciler `api/reconciler.py` started at `api/main.py:146-159`):
  1. Find revisions where `purged_at IS NULL` and object is in terminal/deleted/trash state past grace OR object still exists but over caps/days
  2. For each candidate: if `keep_forever=1` skip (unless explicitly allowed by owner policy); else if object purged and no keep-forever revisions remain -> delete bytes + row; else apply policy: delete oldest revisions beyond `max_count` per object, or older than `retention_days` (counting from `created_at`)
  3. Order: **oldest first**. Delete S3 bytes via `s3ops.delete_object` (handle 404), set `purged_at`, delete row or keep row with `purged_at` (prefer delete row after bytes deleted, like `reconcile_terminal` does `api/lifecycle.py:65-96`)
  4. Interact with two-phase purge: `purge_object` moves to `purging` then deletes shares then row (`api/lifecycle.py:167-192`). Must also delete all revision bytes before deleting object row; if any keep-forever exists, behavior must follow owner decision.
  5. Orphan sweeps: revision keys must be **excluded** from “storage orphan” classification (they are accounted for by `object_revisions`), similar to how soft-deleted object keys are treated (trash bytes kept intentionally).

**Who can set keep-forever:** only the **owner** of the object (`owner_id` on object; service identities own objects but have no folders/shares in same way — follow existing rules). Require `OBJECTS_WRITE` + human for UI actions, similar to shares/folders (`api/main.py:1736-1801, 1995-2155`). Enforce per-user cap (200). Audit all changes.

## 4) Write path — overwrite without breaking upload flow

**Flow:** presigned PUT → commit → verify (unchanged). **“Old bytes become a revision” happens at the moment of overwrite/replace.**

**Where:** when creating a **new version** of an existing object. Options:
- Explicit “replace” endpoint: `PUT /objects/{oid}/content` or `POST /objects/{oid}/replace` that issues new presigned PUT for same logical object (new key) then commit moves head.
- Or implicit: if uploading to same `object_key` not allowed (UNIQUE prevents), better explicit replace creating new key for head.
- **Recommendation:** explicit replace flow: `POST /api/v1/objects/{oid}/revisions` or `POST /api/v1/objects/{oid}/replace` creates new pending object/intent for replacement? Or reuse upload-intent but target existing object. Simpler: create **new upload intent** with `replace_object_id` (add column to objects or pass header/body) — on commit, if replacing existing available object, **archive old head** into revision first (copy-on-write).

**Copy vs rename:**
- **Copy old bytes to revision key** (safer): `s3ops.copy_object` from `old_key` to `revision_key` (e.g. `aura/{space}/{actor}/{uuid}/rev/{revnum}` or append suffix), verify, create revision row, then update head to new key and delete old key? Or keep old key as revision storage_key. 
- **Rename** is not atomic across S3/catalogue; better copy then delete old head key after revision row committed.
- **Copy-on-write**: create revision key as copy of current head bytes, insert revision row (with old checksum/size/key), update `objects.object_key` to new key, update head metadata from new upload, increment `revision_count`, set `current_revision_id`. Do in order with retries.

**Multipart uploads:** must work. Multipart sessions live on the object row (`multipart_upload_id`, `multipart_part_bytes`, `intent_expires_at` extended for multipart per `api/main.py:1115-1148`, `api/migrations.py:63-66`). On replace with multipart, same flow applies — parts uploaded to **new** object_key (new pending object/intent), completion assembles into new key, commit verifies, then archiving happens. **No change to part-level resume logic** except using new intent/object.

**Process dies between “new object available” and “old bytes archived”:** 
- Recovery path: reconciler/scanner detects objects where head was updated but no revision created for previous head? Or track state via `objects.replaced_at` + missing revision. On startup/reconcile, find objects with `replaced_at` set and `revision_count` not incremented for that replacement, or find “orphan” old keys that belong to replaced objects. Also use idempotency key on replace operation.
- **Idempotency key:** add `replace_idempotency_key` (or reuse header `Idempotency-Key` scoped to replace operation) stored on the replacement intent; on commit, if replacement already applied (revision exists for this generation), return existing result. Also use DB transaction where possible and retry logic.

**Critical invariant:** **old bytes must become a revision before or atomically with head update, or be recoverable**. If crash after head points to new key but before revision created and before deleting old key — old key becomes an **unaccounted** key relative to head but contains previous version bytes. Must be detected by reconcile as “previous version candidate” and recovered into revision (or moved). This is the highest-risk point.

## 5) Read path and API — minimal shape

Reuse existing authz scopes (`OBJECTS_READ/WRITE/DELETE/PURGE`), `Repository` pattern, space scoping.

**Endpoints to add/change:**
- `GET /api/v1/objects/{oid}/revisions` — list revisions (newest first). Return: `id`, `revision_number`, `size_bytes`, `checksum_sha256`, `content_type`, `created_at`, `created_by_id`, `created_by_kind`, `keep_forever`. No storage keys.
- `GET /api/v1/objects/{oid}/revisions/{rid}` — get single revision metadata.
- `GET /api/v1/objects/{oid}/revisions/{rid}/download-intent` — presigned GET for that revision’s bytes (same authz as object read, check object in same scope; revision must exist and not purged). Use `revision.storage_key`.
- `POST /api/v1/objects/{oid}/revisions/{rid}/restore` — restore revision as new head. **Creates a new revision** (copy current head to new revision, make restored revision’s bytes the new head). Never “move” head in place — preserves history. Requires `OBJECTS_WRITE`. Audit.
- `DELETE /api/v1/objects/{oid}/revisions/{rid}` — delete one revision (respect keep-forever; if object purged, allowed if user owns). Requires appropriate scope.
- `PUT /api/v1/objects/{oid}/revisions/{rid}/keep-forever` / `DELETE .../keep-forever` — set/unset keep_forever, enforce per-user cap (200), audit.

**Sharing:** `/s/{token}` points at object head (`api/main.py:725-788` looks up share’s object and checks `status == AVAILABLE`, redirects to `obj["bucket"]/obj["object_key"]`). **Sharing cannot point at a revision** by default — shares are for the current object. If needed later, add `revision_id` to shares (big change), not recommended now.

**Docs updates:**
- `docs/openapi.yaml` — add revision endpoints, schemas, examples.
- `docs/API-SPECIFICATION.md` — document revisions, retention, restore semantics.

## 6) Interactions and invariants

| Area | Change | Notes |
|---|---|---|
| **checksum/scrubber/verifier** | Scrubber must verify **head only by default** (cost). Optionally verify revisions on-demand or sampled; full verification of all revisions expensive. Verifier only verifies objects being committed/verified (head). | **Owner decision required** (see Open questions): whether revisions should be verified by the scrubber at all (cost). |
| **dedup** | **Keep no dedup** (as today). Revisions are different versions of same logical object; dedup across objects/revisions not worth complexity. | Explicitly unchanged. |
| **objects.version counter** | **Leave unchanged**. It increments on STATUS changes (`mark_available`, `set_status` in `api/db.py:750-767, 816-834`). Revision creation is not a status change of head in the same sense — or increment on replace; but better not repurpose. Document meaning. | Keep existing semantics. |
| **sharing** | **Shares point at head only**. No change to share model. Restoring revision creates new head; existing shares remain valid for new head. | See above. |
| **quotas** | **Owner decision required** (see Open questions): whether an overwrite consumes daily quota once or twice. Quota charged at upload-intent creation (`_charge_quota` in `api/main.py:97-119, 1112-1114`). Replace creates new intent/objects row? Or reuses; archiving is internal copy. | Must be decided explicitly. |
| **audit log** | Add audit events: `revision.create`, `revision.restore`, `revision.delete`, `revision.keep_forever.set/unset`, `object.replace`. | Follow `api/audit.py` patterns. |
| **capacity guard** | Capacity checked on intent creation (`_check_capacity` `api/main.py:1182-1194`). Replace needs capacity for new bytes; archiving doesn’t require new capacity beyond existing. | Fine. |
| **reconcile/orphans** | **Critical.** Revision keys look like orphans to naive sweep. Must exclude keys that exist in `object_revisions.storage_key`. Update `object_states_for_keys` to also return revision membership, or have separate lookup. Update `storage_reconcile.scan_bucket` to check revisions table. Update `reconcile_reverse` (`api/lifecycle.py:99-144`) to not delete keys owned by revisions. Orphan cleanup must not touch revision keys. | Highest risk integration point — see §9. |

## 7) Phasing — independently shippable/testable

### Phase 1: Schema + migrations (no behavior change)
- Add `object_revisions` table to `schema.sql`
- Add columns to `objects` via `migrations.ADDED_COLUMNS`
- Add indexes, bump `SCHEMA_VERSION`
- Extend `Repository` interface (add methods: `create_revision`, `list_revisions`, `get_revision`, etc.) in both `api/db.py` and `api/db_pg.py` with identical signatures
- **Tests:** extend `tests/test_migrations.py` (add revision columns/table), `tests/test_pg_parity.py` (parity for new methods)
- **Ship/test:** migrations idempotent, existing tests pass

### Phase 2: Archival on replace (write path)
- Add replace endpoint/flow
- On commit of replacement, archive old head to revision (copy to revision key, create row, update head)
- Handle multipart, idempotency, crash recovery (reconciler marks missing revisions)
- **Tests:** extend `tests/test_multipart.py` (replace with multipart), `tests/test_transfer_engine.py` (replace flow, crash recovery), add replace tests
- **Ship/test:** replacing file creates revision, old bytes recoverable

### Phase 3: API + read path + retention
- Add revision endpoints, download intents, restore (creates new revision), delete revision, keep-forever
- Implement retention sweeper (extend reconciler)
- Enforce caps, audit
- **Tests:** new tests for revision API, retention, keep-forever caps
- **Ship/test:** full feature works

### Phase 4: Reconcile/orphan hardening
- Update orphan detection to exclude revision keys
- Update reverse reconcile to ignore revisions
- Update scrubber/verifier policy (per owner decision)
- **Tests:** extend `tests/test_storage_orphans.py` (revision keys not reported as orphans), `tests/test_reconcile*` (if exist) or add reconcile tests
- **Ship/test:** no false positives/negatives

**Files to extend:** `tests/test_migrations.py`, `tests/test_multipart.py`, `tests/test_transfer_engine.py`, `tests/test_pg_parity.py`, `tests/test_storage_orphans.py` (and add `tests/test_revisions.py`, `tests/test_retention.py`).

## 8) What NOT to build

- **Per-block delta storage** — complex, error-prone, minimal benefit at this scale
- **Cross-object dedup of revisions** — dedup none today; revisions often differ significantly, storage cheap enough, complexity high
- **Revision branching/merging** — overcomplicated for file storage
- **Versioning via S3 native** — not portable/reliable here, breaks app invariants (`UNIQUE(bucket,object_key)`, reverse-reconcile, orphan sweeps)
- **Storing revisions in DB** — bytes go in object storage only

## 9) Risk & invariant to test

**Single biggest risk:** **Archival crash** — process dies between updating head to new key and creating revision row / moving old bytes. Old bytes exist under old key but head points elsewhere; revision not recorded. Orphan sweeps/reconcile will see old key as unaccounted or misclassify.

**Must-test invariant:** **Every object with `replaced_at` set must have a corresponding revision for the previous generation, or the old key must be recoverable into a revision.** 
- Test: crash simulation (kill process mid-replace), run reconciler, verify revision exists with correct checksum/size/bytes, head intact.
- Also test: revision keys never appear in storage-orphan reports; purge with keep-forever revisions blocked per owner policy; restore creates new revision not move; idempotent replace.

**Key guardrails:**
- Never delete old head key until revision row committed and bytes verified
- Reconciler must be able to recover from partial state
- All revision operations audited
- Keep `objects.version` semantics unchanged

**Citations:** `api/schema.sql:49`, `api/migrations.py:40,219-251`, `api/db.py:329-335,724-744,750-767,816-834`, `api/db_pg.py:301-307,643-660,664-681,722-739`, `api/main.py:725-788,1115-1148,1449-1535,1674-1708,1868-1883`, `api/lifecycle.py:65-192`, `api/scrubber.py:48-69`, `api/storage_reconcile.py:43-158`, `docker-compose.yml:153-195`, `docs/engineering/transfer-engine-audit.md:320-321,412`.

## Open questions for the owner

- **Purge while keep-forever revisions exist:** Should `POST /objects/{oid}/purge` be blocked while any revision has `keep_forever=1` (requiring explicit deletion of those revisions first), or should a different policy apply?
- **Quota on overwrite:** Does an overwrite/replace consume the daily quota once (only for new bytes) or twice (new bytes plus archiving/internal operations)? Current quota is charged at upload-intent creation (`_charge_quota` in `api/main.py:97-119,1112-1114`).
- **Scrubber verification of revisions:** Should the scrubber verify old revisions at all, or only head objects by default (cost)? Full verification of all revisions could be expensive; need owner decision on trade-off between cost and integrity coverage.