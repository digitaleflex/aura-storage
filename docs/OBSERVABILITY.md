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
  `since`, `until` (epoch seconds, `since <= until` else 422), `actor`
  (substring), `action` / `result` (exact), `space_id`, `application_id`,
  `request_id` (exact; malformed UUID filters are 422). A missing log file
  is an empty history, never an error.
- **Pagination:** `limit` clamped to 1..500 (default 100), `offset` counts
  matches. `total` counts matches **inside the scanned window**; `scanned`
  is the window size and `truncated: true` warns that older history exists
  beyond it. The window is `AURA_AUDIT_MAX_SCAN_LINES` (default 20000).
- **Retention:** `POST /api/v1/admin/audit/prune` (`admin:write`) drops lines
  older than `AURA_AUDIT_RETENTION_DAYS` (default 90) via an atomic rewrite
  and returns `{kept, dropped, cutoff, retention_days}`. Lines without a
  valid timestamp are **kept**: audit data is never deleted silently.

## Usage / quotas (real values only)

`GET /api/v1/admin/usage` (`admin:read`, optional `space_id` filter, 404 on
unknown space) returns:

- `measured_at` — live query time (epoch seconds); this is the freshness
  marker, there is no cache.
- `limits` — configured technical ceilings (`max_object_bytes`,
  `max_pending_intents`, `intent_ttl`, `allow_empty_objects`).
- `totals` + per-space entries — verified **available** bytes
  (`SUM(size_bytes)` over `available` rows; pending intents carry no
  committed bytes), available/pending counts, objects by status.

AURA enforces no per-application byte quota and no transfer-rate quota
(server-side ceilings only), so none is displayed.

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
