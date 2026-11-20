# AURA Storage — Structured Map for Product/Engineering Suggestions

**Repository**: AURA Storage (private S3-compatible storage with SeaweedFS, Traefik, FastAPI, PostgreSQL, React/Vite)
**Scope**: Codebase analysis from README, audit docs, decision files, and main code entrypoints
**Date**: 2026-11-05 (based on latest audit documents)

---

## 1. Core Components & Stack

| Layer | Files/Paths | Description |
|-------|-------------|-------------|
| **API** | `api/main.py` (≈450 routes), `api/config.py`, `api/authz.py`, `api/audit.py`, `api/lifecycle.py`, `api/transfer.py`, `api/s3.py`, `api/store.py`, `api/reconciler.py`, `api/verifier.py`, `api/scrubber.py` | FastAPI application with 97+ HTTP routes. Handles auth, object/folder CRUD, shares, transfers, multipart, admin, audit, reconciliation, verifier, scrubber. |
| **Web (UI)** | `web/src/`, `web/src/pages/`, `web/src/components/`, `web/src/lib/` | React + Vite + TanStack Router. 11+ screens: Files, Transferts, Dashboard, Partages, Corbeille, Paramètres, Aide, Onboarding, Diagnostic, Administration. |
| **Infra** | `docker-compose.yml`, `config/traefik/`, `config/seaweedfs/`, `scripts/` | Docker Compose with Traefik (HTTPS, Let's Encrypt), SeaweedFS master/volume/filer (S3 gateway), PostgreSQL catalogue, nginx app proxy. |
| **Scripts** | `scripts/` | Host bootstrap, config generation, preflight diagnostics, backup/restore, VPS validation. |
| **Tests** | `tests/` | 377 backend tests + 30 frontend unit tests. |

### Key Capabilities Implemented
- **Auth**: Session cookie (HttpOnly, Secure, SameSite=Strict) + CSRF double-submit; M2M Bearer tokens with scoped capabilities; default-deny role→scopes map; master mode (password-confirmed elevation, 15 min TTL).
- **Objects & Folders**: Upload-intent → PUT presigned → commit; `download-intent` with `Content-Disposition: attachment`; `preview-intent` with allow-list; soft-delete/restore/purge; folder CRUD, size calculation, sharing, tags (max 20), moves.
- **Shares**: Public object links (`/s/{token}`), public folder links (`/f/{token}`), stable media URLs (`/m/{slug}`), redeem with usage counting and revocation.
- **Transfers/Multipart**: Single-PUT uploads (< 5 GiB). Multipart enabled via `AURA_MULTIPART_ENABLED=1` (off by default), threshold 100 MB, part size 16 MB, session TTL 7 days, max 1 TiB. Abort, resume, retry supported.
- **Transfer Engine**: Upload state machine, progress, retries, cancellation, integrity (SHA-256 at commit), async verification (N5 worker), reencryption CLI, verifier/scrubber periodic workers.
- **Audit**: Append-only JSONL file (`api/audit.py`), searchable via `GET /api/v1/admin/audit`, retention pruning, correlation via `X-Request-Id`.
- **Reconciliation/Verifier/Scrubber**: Automatic sweep (`api/reconciler.py`), async verification worker (`api/verifier.py`), periodic integrity scrub (`api/scrubber.py`), orphan cleanup (`api/storage_reconcile.py`).
- **AV Scan**: Hook `AURA_AV_SCAN_CMD` (CLEAN/INFECTED/TIMEOUT).
- **Reencryption**: `api/reencrypt.py` for rotating the SSE-S3 KEK.
- **Media Worker**: HLS packaging (`api/media_worker.py`), thumbnails, subtitles.

---

## 2. Current Limitations / Gaps

### From `docs/AUDIT-COMPLET-2026-10-24.md` (5 Critical + 20 Medium + 13 Low)

**Critical Risks (P0)**:
1. **API uses S3 `aura-bootstrap-admin` identity** — full storage compromise if API is compromised. SeaweedFS identity is `Admin, Read, Write, List` with no bucket isolation.
2. **Session TTL 90 days hardcoded in docker-compose** — `AURA_SESSION_TTL: "7776000"` literal in compose, code default is 8h (28800). Stolen cookie valid 90 days without rolling renewal.
3. **`download-intent` serves active content inline** — no `content_disposition=attachment`; `text/html`, `image/svg+xml`, `*xml` accepted when `AURA_ALLOWED_CONTENT_TYPES` empty; executable content on S3 domain.
4. **Production serves `./web/dist` from worktree** — local build instantly publishes; no immutable release artifacts; no rollback traceability.
5. **Security docs missing** — `SECURITY.md`, `AUTHORIZATION-MATRIX.md`, `BACKUP-RESTORE.md`, `DEPLOYMENT.md` deleted from tree; guarantees not auditabile.

**Medium Risks (P1)**:
- S3 Admin identity logged in access logs (presigned URL params visible).
- Landing S3 page missing security headers.
- HSTS absent from Traefik dashboard.
- No container runtime hardening (no `user:`, `read_only`, `cap_drop` in compose for all services).
- Docker socket mounted in Traefik — compromise → root host.
- `AURA_TRUSTED_PROXIES` covers entire RFC1918 — any private-network container can forge `X-Forwarded-For`.
- Compression/caching absent on assets.
- Healthchecks missing on `app`, `swagger-ui`, Seaweed services.
- `scripts/reconcile-cron.sh` has parasitic `EOF` (systemd unit fails).
- README describes API surface that doesn't match reality.

**Low Risks (P2/Info)**:
- No `Permissions-Policy`/COOP/CORP on app.
- Version banners exposed (`nginx/1.28.3`, `SeaweedFS 30GB 4.48`).
- No CAA record on `eurinhash.com`.
- Local artefacts world-readable (`aura-audit.jsonl`, `aura-catalogue.db`).
- GitHub actions not pinned by SHA.
- `DASHBOARD_PASSWORD` in clear in `.env` unused.
- S3 `GET /?list-type=2` lands on landing HTML.
- `/health/ready` triggers `list_buckets()` on every call.
- `/api/v1/diag/download` serves 25 Mo random per auth'd request without quota.

### From `docs/ISSUES-AUDIT-2026-11.md` (Production Gates — manual validation required on VPS)
- **ISSUE-002**: Backup & restore — scripts exist but never executed on pilot; no independent restore test.
- **ISSUE-003**: SSH key-only + host firewall — not configured on VPS.
- **ISSUE-004**: Persistence after host reboot — not re-proven on pilot.

### From `docs/ETAT-DES-FONCTIONNALITES.md` (Feature Gaps)
- **Multipart**: Code present, `AURA_MULTIPART_ENABLED=0` by default, SeaweedFS 4.48 compatibility gate has 2 UNKNOWNs (disk reclaim after abort, 10,000-part completion).
- **Import jobs**: API routes partially implemented (creation/list/cancel) but **no worker** to treat jobs (`api/main.py:4321`).
- **Revisions of content**: Schema + repository only, **no API routes** (`tests/test_revisions.py` missing).
- **FTPS**: Specification only, no code (`ISSUE-018`).
- **OpenBooks integration**: Specification only, no code (`ISSUE-019`).
- **Axiom integration**: Specification only, no code (`ISSUE-020`).
- **Better Auth / Google OAuth**: Deferred (`docs/DECISION-BETTER-AUTH.md`).
- **Independent backup**: Deferred (`docs/DECISION-BACKUP-DEFERRED.md`).
- **Advanced transfer features**: All deferred (`docs/DECISION-ADVANCED-TRANSFER-FEATURES.md`).

### From `docs/DECISION-*` files
- **Better Auth**: Deferred — pilot uses admin-only auth via `/api/v1/login`; no external user need yet.
- **Backup**: Deferred — pilot phase; will be before production.
- **Advanced transfer features**: All deferred until pilot validated in production.

### Code TODOs / Known Issues (sample from audit)
- `_RESP_CACHE` in `api/main.py:1256-1278`: unsynchronized iteration/eviction → possible `RuntimeError` under concurrent commits; stale responses after purge.
- `api/db_pg.py:696`: SQL `IN (%%s)` produces no placeholders — SQL invalid (branche morte today but natural guard of A9).
- `LoginIn` without `max_length` (`main.py:379-382`): username written as-is in audit JSONL → injection volume.
- `master_mode_on` doesn't reset failure budget after success (`main.py:783-800`).
- `verifier.py:132-135`: ignores `rowcount` of `mark_available`, audits success for purged object.
- `audit.py:267-278`: purge with `os.replace` keeping lock on old inode → events lost in multi-process.
- `preview-intent` doesn't do `HEAD` control that `download-intent` does.
- S3 `GET /?list-type=2` returns landing HTML instead of S3 response; CORS allows `*` methods/headers.

---

## 3. Observability, Automation, and "Intelligence" Hooks

### Existing Audit/Logging
- **Audit log** (`api/audit.py`): Append-only JSONL at `/var/lib/aura/audit/aura-audit.jsonl`. Events: `{ts, actor, action, result}` + flat scalar extras (IDs, bucket names, statuses, TTLs, counts). Passwords/secrets/URLs never recorded (whitelist enforced).
- **Correlation**: Every response carries `X-Request-Id` (client-echoed or server-minted UUID v4). In-request events store it. Pre-auth events correlate by request id (no tenant). Post-auth events attributed with `space_id`/`application_id`.
- **Search**: `GET /api/v1/admin/audit` with filters `since`/`until` (epoch seconds), `space_id`, `application_id`, `actor` (substring), `action`, `result`, `request_id` (exact). Pagination clamped to 1..500 (default 100). Window bounded by `AURA_AUDIT_MAX_SCAN_LINES` (default 20000).
- **Retention**: `POST /api/v1/admin/audit/prune` (`admin:write`) drops lines older than `AURA_AUDIT_RETENTION_DAYS` (default 90). Lines without valid timestamp are kept.
- **Usage** (`GET /api/v1/admin/usage`): Live counters — stored bytes, pending intents, objects by status, egress, share redemptions per space. Estimates, not edge measurements.
- **Health** (`GET /api/v1/admin/health`): Per-component `ok`/`down`: `api`, `database`, `storage` (S3 `list_buckets` latency), `disk` (local process volume), `recent_errors` (max 5, tenant-safe, window 3600s).

### Existing Automation / Workers
- **Reconciliation sweep** (`api/reconciler.py`): Background thread, runs every `AURA_RECONCILE_INTERVAL_S` (default 300s). Bounded to `AURA_RECONCILE_LIMIT` (default 500) intents per run. Expires stale pending intents, finishes interrupted purges, purges transfer history.
- **Verifier worker** (`api/verifier.py`): Asynchronous integrity check. Threshold `AURA_VERIFY_ASYNC_THRESHOLD_BYTES` (default 32 MB). Mode: `"inline"` (worker thread in API process) or `"off"` (run standalone). Marks objects `verifying` during check, then `available` or `suspect`.
- **Scrubber** (`api/scrubber.py`): Periodic re-hash of available objects, read-only, within byte budget per hour (`AURA_SCRUB_BYTES_PER_RUN`, default ~10 GB). Oldest check first. Does not delete/rewrite.
- **Storage reconcile** (`api/storage_reconcile.py`): Detects orphaned bytes (no catalogue row) and multipart intents past TTL; cleanup encadré.

### "Intelligence" / ML/AI — **Absent**
- No on-device or server-side ML models.
- No predictive analytics, classification, or recommendation features.
- No computer vision (thumbnail generation is ffmpeg-based, not learned).
- No smart search beyond substring `q` filter on `display_name`.
- No automated anomaly detection on transfer patterns.

### Gaps for "Smart" Features
- **Per-application quotas** — only per-space quotas exist; no per-app quota.
- **Transfer-rate quota** — only edge rate limit (30 req/s burst 60); no per-app or per-space bandwidth cap.
- **Transfer success/decomposition** — API never sees bytes; only commit outcomes (`available`/`failed`) visible per object.
- **Object-store capacity awareness** — `disk_usage` in health reports local volume, not SeaweedFS total capacity.
- **Predictive lifecycle** — no ML-predicted expiry or automatic tiering.
- **Anomaly detection** on audit/log patterns — manual today.

---

## 4. UX/Product Surface (Web App)

| Screen | Route | Key Capabilities |
|--------|-------|-----------------|
| **Files** (`/`)/Objects | `/` | List/grid view, breadcrumb, filters (folder/statut/type/taille/dates/Tag), upload, sharing, bulk select, folder management, ZIP download, drag-and-drop, virtualized list (≥50 rows). |
| **Transferts** (`/transfers`) | `/transfers` | File list with progression, débit/ETA, pause/reprise/annulation, URL filtres, CSV export, virtualized list, tooltips on all buttons, open-file action from completed lines (issue ISSUE-010). |
| **Dashboard** (`/dashboard`) | `/dashboard` | Usage: storage used/quota, egress monthly, object counts by status, recent transfers, alerts; admin-only detailed stats (spaces, buckets, identities, quotas, integrity, orphans). |
| **Partages** (`/shares`) | `/shares` | List active public links with expiration & usage count, create links for objects/folders, revoke individual links. |
| **Corbeille** (`/trash`) | `/trash` | List soft-deleted objects with deletion date, restore per object, bulk purge (master mode), empty trash. |
| **Paramètres** (`/settings`) | `/settings` | Theme light/dark, account info, password change, logout. |
| **Aide** (`/help`) | `/help` | Contextual help on import/partage/sécurité. |
| **Onboarding** (`/onboarding`) | `/onboarding` | 3-4 screen tour at first login; explains import, share, restore; dismissible (localStorage). |
| **Diagnostic** (`/diagnostic`) | `/diagnostic` | RTT, downlink/uplink speed test, local history. |
| **Administration** (`/admin`) | `/admin` | Spaces CRUD, quotas, identities, partners, integrity, orphans, audit log search, reconcile operations. |

### Notable UX Gaps (from ISSUES-AUDIT-2026-11.md and ETAT-DES-FONCTIONNALITES.md)
- **No dashboard aggregate view** until ISSUE-006 (planned).
- **No share management UI** until ISSUE-007 (planned).
- **No trash UI** until ISSUE-008 (planned).
- **No user settings page** beyond theme until ISSUE-009 (planned).
- **No "open file" action from completed transfers** — ISSUE-010 (implemented in diff but virtualization not yet).
- **CSV formula injection** — ISSUE-013 (not escaped `=`, `+`, `-`, `@` prefixes).
- **CSP blocks inline theme bootstrap** — ISSUE-F1.
- **No global 401 handling** in frontend — ISSUE-F4.
- **Timeout on presigned PUT never armed** — ISSUE-F5.
- **localStorage not protected** — ISSUE-F6.
- **Partial logout** — ISSUE-F7.
- **window.open after await blocked by pop-up blockers** — ISSUE-F8.

---

## 5. Security / Reliability Posture

### Strengths (Verified)
- **TLS**: Valid Let's Encrypt chain on all public hosts; TLS 1.2/1.3 enforced.
- **Security headers**: CSP, HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy` on app and landing (partially).
- **Default-deny authorization**: 65 routes audited; only `health/live`, `health/ready`, `login`, `/s/{token}` are public. Admin routes require `ADMIN_READ`/`ADMIN_WRITE`. Machine identities (`service` kind) can never exercise `admin:*` capabilities.
- **Cookie security**: `HttpOnly; Secure; SameSite=Strict`; Argon2 password hashing; CSRF double-submit; login rate-limited 10/60s per IP.
- **Presign TTL short**: 60–900 s; `x-amz-server-side-encryption: AES256` required at commit.
- **Object-key generation server-side**: No client-controlled paths to S3 bucket escalation.
- **Scopes isolation**: Machine identities limited to `SERVICE_SCOPES = {objects:read, objects:write, objects:delete}` — no `objects:purge`, no `admin:*`.
- **Audit trail**: Append-only JSONL, searchable, retention-bounded, never deletes lines without valid timestamp.
- **SSE-S3 AES256**: Explicitly required and verified at commit; KEK (`WEED_S3_SSE_KEK`) generated offline, kept protected.
- **CSP on app**: Present (though inline theme bootstrap blocked per F1).
- **No secrets in git**: `.env` gitignored; `config/seaweedfs/s3.json` not tracked.

### Open Gates / Unconfirmed Risks
- **API S3 `Admin` identity** (S1 critical) — must create dedicated SeaweedFS identity with bucket-scoped permissions; retire `aura-bootstrap-admin` from routine traffic.
- **Session TTL 90 days** (S2 critical) — make `AURA_SESSION_TTL` configurable via `.env` with default 8h; invalidate existing sessions on value change.
- **`download-intent` inline content** (A1 critical) — enforce `content_disposition=attachment`; refuse active content types when allow-list empty.
- **`./web/dist` in production** (D1 critical) — publish immutable artefacts per release; never mount worktree; verify deployed hash.
- **Landing S3 missing headers** (S4 medium) — mount `landing/nginx.conf` in compose; add CSP, HSTS, security headers.
- **HSTS absent from dashboard** (S5 medium) — add `aura-hsts` middleware to Traefik dashboard router.
- **Containers not hardened** (S6 critical) — add `user: 10001:10001`, `read_only: true`, `tmpfs`, `cap_drop: [ALL]`, memory/CPU limits per service.
- **Docker socket in Traefik** (S7 critical) — replace with filtered socket-provider or file-based provider.
- **`AURA_TRUSTED_PROXIES` too broad** (S8 medium) — restrict to actual proxy subnets (`172.30.0.0/24`, `172.31.0.0/24`, loopback/::1).
- **Compression/caching absent** (D2 medium) — add `gzip`/`brotli` and `Cache-Control: immutable` on hashed assets.
- **Healthchecks missing** (D3 medium) — add healthchecks on `app`, `swagger-ui`, Seaweed services; add `depends_on: service_healthy`.
- **Backup/restore not validated** (P0 gate) — execute `scripts/aura-backup.sh`; test restore on isolated environment; verify SHA-256 checksums.
- **SSH key-only + host firewall** (P0 gate) — configure `~/.ssh/authorized_keys`; harden `sshd_config`; `ufw`/`nft` rules; confirm console recovery.
- **Persistence after host reboot** (P0 gate) — reboot host; verify all containers restart with data intact; functional upload/download test.
- **E2E real on VPS** — not yet executed; start API + front real and play critical paths.
- **multipart SeaweedFS 4.48 gate** — 2 UNKNOWNs: disk reclaim after abort, 10,000-part completion.

### Documentation Gaps
- `SECURITY.md`, `AUTHORIZATION-MATRIX.md`, `BACKUP-RESTORE.md`, `DEPLOYMENT.md` deleted from tree — must be restored or references removed.
- `API-ROUTES-AUDIT.md` is false (announces 59 routes, code has 62; lists 10 non-existent, omits 13 real).
- README references expired "open gates" (external HTTPS, internal ports) that are actually validated.
- Better Auth + Google OAuth deferred; decision documented but no reactivation path visible.

---

## Recommended High-Impact Action Areas

| Priority | Area | Rationale |
|----------|------|-----------|
| **P0** | **Replace `aura-bootstrap-admin` S3 identity** with dedicated bucket-scoped key; regenerate `.env` + `s3.json`; retire admin from routine traffic. | Critical — full storage compromise risk if API hit. |
| **P0** | **Fix session TTL**: make configurable via `.env`, default to 8h (28800s); invalidate sessions on config change. | Critical — stolen cookie valid 90 days without renewal. |
| **P0** | **Enforce `content_disposition=attachment` on `download-intent`**; refuse active content types. | Critical — executable content on S3 domain (phishing). |
| **P0** | **Publish immutable web artefacts**; never mount `./web/dist` from worktree; add deployment hash verification. | Critical — non-deterministic production code. |
| **P1** | **Harden containers**: add `user`, `read_only`, `tmpfs`, `cap_drop` to all services in `docker-compose.yml`. | Critical — RCE in API → root in container. |
| **P1** | **Fix Traefik Docker socket** — replace with filtered proxy or file-based provider. | Critical — compromise Traefik → root host. |
| **P1** | **Add security headers to landing page**; mount `landing/nginx.conf` in compose. | High — missing CSP/HSTS on public S3 endpoint. |
| **P1** | **Restrict `AURA_TRUSTED_PROXIES`** to actual proxy subnets only. | High — IP spoofing → rate-limiter bypass. |
| **P1** | **Implement import-jobs worker**; complete multipart compatibility verification on SeaweedFS 4.48. | High — unfinished core features. |
| **P2** | **Add per-application quotas** and **transfer-rate quotas** beyond edge limit. | Medium — missing operational controls. |
| **P2** | **Add "intelligence" features**: anomaly detection on audit patterns, predictive lifecycle, smart search beyond substring. | Medium — "smarter" platform differentiation. |
| **Docs** | **Restore deleted docs** (`SECURITY.md`, `AUTHORIZATION-MATRIX.md`, `BACKUP-RESTORE.md`, `DEPLOYMENT.md`). | High — auditability depends on documented guarantees. |
| **Docs** | **Regenerate `API-ROUTES-AUDIT.md`** from actual code + OpenAPI. | High — documentation must match reality. |

---
*Map generated from analysis of: README.md, AUDIT-COMPLET-2026-10-24.md, ISSUES-AUDIT-2026-11.md, ETAT-DES-FONCTIONNALITES.md, DECISION-BETTER-AUTH.md, DECISION-BACKUP-DEFERRED.md, DECISION-ADVANCED-TRANSFER-FEATURES.md, OBSERVABILITY.md, api/ entrypoints, web/ entrypoints, docker-compose.yml.*