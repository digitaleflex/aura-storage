# AURA Catalogue — data model

**Status:** the entities below marked **(implemented)** exist in the shared schema
(`api/schema.sql` + additive migrations in `api/migrations.py`) and are covered by
offline tests. Items marked **(proposal)** remain design drafts. The API
authorization model built on this schema is documented in
`docs/AUTHORIZATION-MATRIX.md`.

## Identifiers (implemented)

Every identifier AURA stores or returns — `id` columns and every `*_id` foreign
key — is a **canonical UUID v4**: lowercase hexadecimal, `8-4-4-4-12`, 36
characters. `api/ids.py` is the single source of truth for generating,
validating and normalizing them:

- `new_id()` mints a fresh UUID v4; every repository `new_id()` delegates to it.
- `canonical(value)` accepts the alternate spellings `uuid.UUID` understands
  (upper case, braces, `urn:uuid:`, un-hyphenated) and returns the canonical
  lowercase form, or `None` for anything that is not a v4 UUID.
- Request bodies and path/query parameters are validated at the API boundary
  (`api/main.py`): a malformed identifier is refused with `422` rather than
  silently treated as a not-found lookup. A non-canonical id inside a machine
  token is rejected too (`api/identity.py`).

The default application/space/bucket are seeded with generated UUID v4 ids, not
fixed sentinels. Releases before this rule seeded them with
`00000000-…-0001/0002/0003`; `api/migrations.py::_canonicalize_legacy_ids`
rewrites those three rows (and every foreign key that points at them) once, on
upgrade. This is the one deliberate, non-additive step in the migration chain:
it never drops or rewrites any other row. The database stores the values as
`TEXT` with no `CHECK` constraint — SQLite cannot add one to an existing table,
so the format is enforced in code, not in DDL.

## Multi-platform isolation (implemented, #35)

### Application
- `id`, `name` (unique), `status`, `created_at`.
- One platform that consumes AURA. AURA does not manage the platform's users,
  subscriptions or billing.

### Space
- `id`, `application_id`, `name`, `environment` (`dev`/`staging`/`prod`/…),
  `status` (`active`/`disabled`), `created_at`; unique on
  `(application_id, name, environment)`.
- The tenant/data boundary. Objects, buckets and service identities belong to a
  space; every catalogue query is filtered by the caller's space.
- `status` is a **soft** lifecycle flag (M04): a space is never deleted through
  the API. Disabling it refuses new uploads and new identities while the existing
  rows stay readable. `application_id` is immutable — a space is never moved to
  another application — and a space can only be attached to an **active**
  application. Added additively on upgrade (`0003_space_status`), backfilled to
  `active`.

### Bucket
- `id`, `space_id`, `name` (unique), `is_default`, `created_at`.
- Object-store bucket registered to a space. A caller can only use a bucket
  registered to its own space; the bucket is never chosen arbitrarily by a client.
- M04: a bucket is registered additively (validated S3 name, globally unique) and
  its `is_default` flag is toggled with `PATCH`; setting one default clears the
  flag on the space's other buckets. Buckets are never deleted through the API,
  and the catalogue stores **no** S3 credential (the access key/secret live only
  in the deployment environment).

### ServiceIdentity (implemented, #38)
- `id`, `application_id`, `space_id`, `name`, `secret_hash` (SHA-256 of the secret),
  `scopes` (comma-separated capabilities), `role`, `created_at`, `expires_at`,
  `last_used_at`, `revoked_at`, `rotated_at`.
- Machine-to-machine identity. Only the secret fingerprint is stored; the token is
  shown once at creation/rotation. There is no clear-text secret column.

### PartnerSite (implemented, admin "Intégrations")
- `id`, `space_id`, `identity_id` (FK to `service_identities`), `name` (unique per
  space), `site_url` (normalized https origin), `default_ttl_seconds` (media-TTL
  recommendation for the partner's stable redirect), `notes`, `created_by`,
  `created_at`, `updated_at`.
- Metadata only: **the credential remains the service identity**, so rotation and
  revocation keep using the identity routes and every audit entry names an
  identity. The row is never used for authentication.

### SpaceQuota / SpaceUsageMonthly (implemented)
- `space_quotas`: `space_id` (PK), `storage_bytes` (nullable), `egress_bytes_monthly`
  (nullable), `updated_at`, `updated_by`. `null` means no quota, never zero.
- `space_usage_monthly`: `space_id` + `period` (`YYYY-MM`, UTC) primary key,
  `egress_bytes`, `download_intents`, `preview_intents`, `share_redemptions`,
  `updated_at`. Additive counters, never rewritten downwards.
- Egress is an **estimate**: one issued intent or share redemption adds the
  object's full size once, because AURA never proxies the bytes. Storage is
  measured live from `objects`; the quota is checked at upload intent.

### ObjectTag / Collection (implemented, Sprint 2)
- `object_tags(object_id, tag)`: normalized lowercase tags, PK (object, tag).
- `collections`: ordered course pack (`slug` globally unique, title, description,
  `published_at`, owner/space). `collection_items` keeps `position`; the public
  manifest is `/p/<slug>.json` and only exposes each item's `/m/<slug>` URL when
  that object is itself published.

### ObjectUsageMonthly (implemented, Sprint 3)
- `object_id` + `period` (YYYY-MM) PK, `views`, `downloads`, `share_opens`,
  `egress_bytes` (BIGINT estimate), `last_access_at`. One intent/opening counts
  the object's full size once; AURA never proxies bytes.

### User (implemented; extended by #35)
- `id`, `username` (unique), `pass_hash`, `created_at`, plus `role`
  (`user`/`operator`/`admin`), `application_id`, `space_id`.
- Human operator/consumer account. Effective capabilities come from `role`.

### Session (implemented)
- `id`, `user_id`, `csrf`, `expires_at`.

## Object and folder (implemented)

### Object
- `id`: canonical UUID v4 primary key generated by AURA (see *Identifiers*).
- `bucket`, `object_key`: unique storage locator, private to the service. The key is
  always generated server-side as `aura/<space>/<actor>/<uuid>`.
- `display_name`, `content_type`, `size_bytes`, `checksum_sha256`.
- `expected_size_bytes`: the size declared at intent time, kept distinct from the
  verified `size_bytes` (which stays `-1` until commit). Added by the M03 transfer
  engine migration.
- `idempotency_key`: optional opaque client key deduping an accidental double
  submit (scoped to actor + space). Never logged. Added by M03.
- `folder_id`: nullable foreign key to logical folder.
- `owner_id` (nullable) / `actor_id` + `actor_kind` / `space_id` / `application_id` /
  `environment`: ownership and isolation boundary.
- `public_slug` / `published_at`: stable public URL (`/m/<slug>`) and its
  publication time. The slug survives a content replacement.
- `thumbnail_key` / `duration_seconds`: generated poster/thumbnail (stored in
  the same bucket) and measured media duration.
- `visibility` (private by default), `status`
  (`pending`/`available`/`failed`/`expired`/`aborted`/`deleted`), `intent_expires_at`,
  `created_at`, `updated_at`. `aborted` is the terminal state of a client-cancelled
  pending intent (see `docs/TRANSFER-ENGINE.md`); `failed` and `expired` are terminal
  too and are never downloadable.

### Folder
- `id`, `owner_id`, `parent_id`, `name`, `created_at`.

### ObjectShare (implemented)
- `id`: canonical UUID v4 primary key.
- `object_id`: the shared object. **No foreign key on purpose**: `objects:purge`
  removes the object row, and a share must then be a harmless dangling row that
  answers 404 rather than a constraint that blocks a purge. `api/lifecycle.py`
  deletes the share rows explicitly, before the object row.
- `token_hash`: SHA-256 of the link token. The token itself is never stored, so a
  catalogue dump cannot be replayed as working links.
- `space_id`, `created_by`, `created_by_kind`: attribution and audit scope,
  copied at creation for the unauthenticated redemption path (no principal).
- `content_disposition`: `attachment` (default) or `inline` (non-executable types
  only).
- `expires_at` (mandatory), `max_uses` (nullable), `use_count`, `revoked_at`,
  `last_used_at`, `created_at`. `max_uses` is enforced inside the redemption
  UPDATE, so concurrent redemptions cannot exceed it.

## Proposal (not implemented)

### ImportJob
- `id`, `tenant_id`, `created_by`, `status`, `total_items`, `processed_items`,
  `failed_items`, timestamps, sanitized summary.
- Jobs must be retryable/idempotent and should support cancellation where safe.

### AuditEvent (partially implemented)
- Actor/service identity, action, target ID, outcome, request ID, timestamp, and safe
  metadata. Implemented today as an append-only JSON-lines log (`api/audit.py`);
  never records secrets, signed URLs, authorization headers, or full private content.

## Consistency and reconciliation

S3 upload and PostgreSQL metadata writes are not one atomic transaction. Use a lifecycle:
1. Create a pending upload intent in PostgreSQL.
2. Issue a short-lived upload URL scoped to a generated object key.
3. Verify upload completion and object metadata/checksum.
4. Mark the catalogue object available.
5. Reconcile expired pending uploads and orphaned objects after a safe grace period.

Deletion should first mark an object as deleting/deleted and retain a recoverable window. A separate purge job can permanently delete bytes after policy checks. Log all destructive operations.

## Indexing and scale

Index tenant/owner, folder, status, created_at, and normalized display name. Use cursor pagination for large catalogues. Add full-text search only after measuring actual needs. Store file bytes in SeaweedFS, not PostgreSQL.
