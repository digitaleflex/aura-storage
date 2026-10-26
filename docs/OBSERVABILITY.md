# AURA — Observability: audit, usage, supervision (M07)

**Status:** implemented in `api/audit.py`, `api/main.py` (`/admin/audit`,
`/admin/audit/prune`, `/admin/usage`, `/admin/health`), `api/db.py`,
`api/db_pg.py`; covered offline by `tests/test_m07_observability.py` and
surfaced in the admin console (`web/src/pages/AdminPage.tsx`). No database
model or migration was needed: the audit trail stays an append-only
JSON-lines file (O(1) appends, bounded-tail reads) and usage is derived from
live catalogue queries.

## Audit log

- **Content:** `{ts, actor, action, result}` plus flat scalar extras (IDs,
  bucket names, statuses, TTLs, counts). Passwords, secrets, session/CSRF
  tokens and (presigned) URLs are never recorded, not even truncated
  (`api/audit.py` whitelist; asserted by tests).
- **Correlation:** every response carries `X-Request-Id` (a safe client value
  echoed, otherwise a server-minted UUID v4); every in-request event stores
  it. Pre-authentication events (failed logins) correlate by request id but
  carry no tenant. Post-authentication events are attributed with the
  caller's `space_id` / `application_id` by the authorization layer; explicit
  event fields always win.
- **Search** (`GET /api/v1/admin/audit`, `admin:read`): newest-first filters
  `since`, `until` (epoch seconds, `since <= until` else 422). `space_id` and
  `application_id` are canonical UUID v4 filters (malformed → 422); `actor`
  (substring) and `action` / `result` / `request_id` (exact) are plain string
  filters and never 422. A missing log file is an empty history, never an
  error.
- **Pagination:** `limit` is **clamped** server-side to 1..500 (default 100) —
  an out-of-range value is clamped, not 422, even though OpenAPI lists
  `minimum`/`maximum`; `offset` counts matches (a negative `offset`
  clamps to 0, never 422). `total` counts matches **inside the scanned
  window**; `scanned` is the window size and `truncated: true` means the
  window was full, so older history *may* exist beyond it (conservative:
  may over-warn, never under-warn). The window is
  `AURA_AUDIT_MAX_SCAN_LINES` (default 20000).
- **Retention:** `POST /api/v1/admin/audit/prune` (`admin:write`) drops lines
  older than `AURA_AUDIT_RETENTION_DAYS` (default 90) via an atomic rewrite
  and returns `{kept, dropped, cutoff, retention_days}`. Lines without a
  valid timestamp are **kept**: audit data is never deleted silently.
- **Storage location:** the API appends to `AURA_AUDIT_LOG`
  (`/var/lib/aura/audit/aura-audit.jsonl` in the Compose stack), backed by the
  dedicated `api-audit` volume so the trail survives container recreation and
  redeploys. `prune` rewrites that same file.

## Usage / quotas (real values only)

`GET /api/v1/admin/usage` (`admin:read`, optional `space_id` filter, 404 on
unknown space) returns:

- `measured_at` — live query time (epoch seconds); this is the freshness
  marker, there is no cache.
- `limits` — configured technical ceilings (`max_object_bytes`,
  `max_pending_intents`, `intent_ttl`, `allow_empty_objects`).
- `period` — UTC month (`YYYY-MM`) the counters below belong to.
- `totals` + per-space entries — verified **available** bytes
  (`SUM(size_bytes)` over `available` rows; pending intents carry no
  committed bytes), available/pending counts, objects by status.
- `month` per space — `egress_bytes`, `download_intents`, `preview_intents`,
  `share_redemptions`. **Estimate, not an edge measurement:** AURA never
  proxies object bytes, so one issued intent or share redemption counts the
  object's full size once. Range/multipart transfers are not decomposed.
- `quota` per space — monthly `storage_bytes` and `egress_bytes_monthly`
  (`null` = no quota). Storage is enforced at upload intent (`429 storage
  quota exceeded`); egress is enforced before issuing an intent or redeeming a
  share (`429 monthly egress quota exceeded`, or the uniform 404 on the public
  share route). Quotas are set with
  `PUT /api/v1/admin/spaces/{sid}/quotas` and audited as
  `admin.space.quotas`.

There is still no per-application quota and no transfer-rate quota beyond the
existing server-side ceilings and edge rate limit.

## Politique retry côté serveur (#86, partielle)

- Les 429 à fenêtre temporelle portent `Retry-After` : login
  (`AURA_LOGIN_RATE_LIMIT`/`AURA_LOGIN_RATE_WINDOW`) et M2M
  (`AURA_M2M_RATE_LIMIT`/`AURA_M2M_RATE_WINDOW`). Le 429 « trop d'intentions
  en attente » n'a pas de fenêtre : le client doit solder (commit/abandon)
  avant de réessayer, jamais réessayer en boucle.
- Les 401/403/409/410/413/422 sont définitifs : ne jamais les réessayer sans
  changer la requête (le client web les classe `fatal`/`expired`, jamais
  `retryable`).
- Les 5xx et erreurs réseau sont réessayables avec backoff exponentiel
  plafonné + jitter côté client ; le serveur n'ordonnance aucun retry
  automatique d'opération non idempotente. La classification complète vit
  dans `web/src/lib/transfer.ts` (`classifyError`) et est exercée offline.

## Supervision

`GET /api/v1/admin/health` (`admin:read`) always answers 200 with
per-component `ok`/`down` and a top-level `ok`/`degraded`:

| Component | Probe | Meaning |
|---|---|---|
| `api` | process uptime + version | the API answers at all |
| `database` | `SELECT 1` + latency | catalogue reachable |
| `storage` | S3 `list_buckets` + latency | S3 **reachable** — not a full upload/download round-trip |
| `disk` | `disk_usage` bytes | **local** process volume — not the object-store capacity |
| `recent_errors` | non-`success` audit events in `AURA_AUDIT_ERROR_WINDOW_S` (default 3600 s), max 5, tenant-safe projection | what failed lately |

Error labels stay generic (`unreachable`/`unreadable`): no endpoint,
credential or tenant data. Degraded storage means uploads/downloads will
fail; the data-plane proof is the live S3 smoke test (see below).

## Unavailable metrics (documented, never invented)

- Transfer bandwidth / throughput per app or space: not measured anywhere.
- Object-store total capacity / fill percentage: unknown to the API
  (SeaweedFS capacity is not queried); only local disk bytes are reported.
- Per-request S3 latency history: presigning is local crypto; only the
  health-check latency is sampled.
- Client-side upload/download success rates: the API authorizes transfers
  but never sees the bytes; `commit` outcomes (`available`/`failed`) are the
  only transfer truth, visible per object and in `objects_by_status`.

## Validations requiring real infrastructure (not run offline)

- S3 reachability flavor of `/admin/health` against the pilot SeaweedFS
  (offline the endpoint is unreachable by design → `degraded`).
- Full upload/download round-trip (`tests/test-s3-smoke-validation.sh` logic
  and `tests/s3-smoke-test.sh`): proves presigned PUT/GET + commit on real
  bytes; needs the pilot endpoint and AWS CLI.
- PostgreSQL parity of the new `ping` / `space_usage` / `stored_bytes`
  queries (`tests/test_pg_parity.py` needs `AURA_TEST_PG_DSN`).
- Disk figures against the VPS volume layout (`docs/SERVER-PROFILE.md`).
