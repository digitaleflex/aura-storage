# AURA Vault Transfer Engine (M03)

**Status:** implemented in code (`api/transfer.py`, `api/main.py`, `api/s3.py`,
`api/migrations.py`, `web/src/lib/transfer.ts`, `web/src/lib/api.ts`,
`web/src/pages/ObjectsPage.tsx`) and covered by offline tests
(`tests/test_transfer_engine.py`) and browser tests
(`web/e2e/transfer-engine.spec.ts`, `web/e2e/upload-flow.spec.ts`).
Validated on SQLite and an in-process S3 stub. The transfer-engine-specific
matrix rows for PostgreSQL parity and live multipart/Range remain open (*Test
matrix*); the pilot has partial dated live evidence — the API runs on the pilot
PostgreSQL and an SSE-S3 smoke test PASSed on the pinned SeaweedFS 4.48
(2026-10-15 and 2026-10-16 logs linked from `README.md`).

> **Update 2026-10-22.** The engine changed substantially after an audit of slow
> uploads: default concurrency, commit/upload retry separation, slot release
> during verification, verification after uploads, scrubber behaviour, progress
> coalescing and a per-file detail view. See
> [CHANGES-2026-10-22-transfer-and-ui.md](CHANGES-2026-10-22-transfer-and-ui.md)
> for the list with reasons, and [MEASURE-TRANSFER.md](MEASURE-TRANSFER.md) to
> measure the effect. **None of this has been measured on the pilot yet.**

This document is the transfer-engine companion to the contract in
[File Transfer Contract](FILE-TRANSFER.md) and the plan in
[Secure and Efficient Bulk Transfers](SECURE-BULK-TRANSFERS.md). Where they
describe intent, this document states what the engine actually does today and
what it explicitly does **not** do.

## Architecture (as implemented)

The mission's six-step flow maps onto existing AURA routes one-to-one:

| Step | Route / code | Notes |
|---|---|---|
| 1. Frontend asks for a transfer intention | `POST /api/v1/objects/upload-intents` | `web/src/lib/api.ts` |
| 2. API authenticates + authorizes | `api/authz.py` (`authorize(OBJECTS_WRITE)`) | session cookie + CSRF, or Bearer service identity |
| 3. API issues a short-lived URL | `api/s3.py::presigned_put` | SigV4, exact bucket/key, signed `Content-Length` + `Content-Type` + `x-amz-server-side-encryption: AES256` |
| 4. Browser moves bytes directly to S3 | `putToPresignedUrl` (XHR) in `web/src/lib/api.ts` | bytes never traverse FastAPI |
| 5. Frontend finalizes | `POST /api/v1/objects/{oid}/commit` | idempotent |
| 6. Backend verifies size + integrity | `commit_object` + `stream_sha256` | object only becomes `available` here |

Downloads are the mirror image: `POST /api/v1/objects/{oid}/download-intent`
returns a short-lived presigned GET; the browser performs the transfer and the
API never proxies the bytes.

## Upload state machine

`web/src/lib/transfer.ts::runTransfer` is a single, side-effect-free-by-injection
state machine. Phases:

```
idle → requesting-intent → uploading → validating → available
                                  ↘ failed / cancelled
```

- `requesting-intent` — the API authorized a bounded upload.
- `uploading` — direct browser → S3 PUT. Real progress is shown from the XHR
  `upload.onprogress` event (`role="progressbar"`, `aria-valuenow`).
- `validating` — the browser calls commit; the backend streams the object,
  checks the size and computes SHA-256. `TransferState.verifyMode` says what the
  server is doing: `inline` (the commit request is re-reading and hashing) or
  `background` (bytes stored, the integrity check waits in the server's queue and
  the client polls, `202 verifying`).
- `available` — **only** reached when commit returned success. The UI never
  infers success from the upload PUT alone. `TransferState.checksum` then holds
  the SHA-256 recorded by the server.
- `failed` / `cancelled` — terminal, with the reason shown. A failure also
  records `failureKind` (`retryable`, `expired`, `fatal`, `aborted`) so the
  queue can tell an outage from a decision the server will never reverse.

Every phase change is stamped: `phaseSince` (start of the current phase) and
`phaseLog` (every phase with its start time) feed the "since 0:42" labels and
the per-file detail view.

**Upload and commit are retried separately.** Once the PUT succeeded, a failing
commit (5xx, network) retries the commit only; resending the whole file would hit
`412` (the PUT is conditional, `If-None-Match: *`) or `409` and end `failed` with
intact bytes. A `412` on the PUT means the object already exists on that key, so
the engine goes straight to the commit. A `504` still re-uploads, because the
server may have discarded the bytes.

Errors are classified (`classifyError`) into `retryable`, `expired`, `aborted`
and `fatal`, so the UI retries only what can succeed and never loops on an
authorization or validation error.

## Required behaviours and where they live

| Requirement | Implementation |
|---|---|
| Real progress where the browser allows it | XHR upload progress; download progress is browser-managed and the UI reports the launched intent |
| Show size, name, state, errors | transfer panel in `ObjectsPage.tsx`; declared size shown while `pending` via `expected_size_bytes` |
| Block accidental double submit | submit disabled while active; stable `Idempotency-Key` per submission dedupes at the API |
| Cancel only when the backend supports it | `POST /api/v1/objects/{oid}/abort` exists, so the UI offers cancel and calls it; no fake client-only cancel |
| Controlled retries with backoff + jitter | `backoffDelay` (equal jitter, exponential, capped) for network/5xx; expired URLs get a fresh intent (bounded) |
| Adaptive parallelism + paced starts | default ceiling **4** files at once (was 10: ten PUTs split one uplink ten ways, hit the proxy's 1200 s read timeout sooner and trigger ten commit re-reads on the same disk). The queue shrinks its effective parallelism after repeated congestion failures (network/5xx/expired, never fatal/cancelled) and restores it after sustained success; parallel PUT starts are staggered (`QueueOptions.startStaggerMs`). JDownLoader-inspired, adapted from chunks to whole files |
| Per-file retry + stuck-intent abandon | `retryItem(id)` restarts one failed/cancelled file as a fresh submission; catalogue rows stuck `pending` offer "Abandonner l'envoi" (backend abort + partial bytes removed), and `aborted` is a listed status |
| Distinguish upload / validation / availability / failure | the five phases above |
| Handle expired URLs and network errors | 403 → new intent; network/5xx → retry; both bounded |
| Clean local state after failure | `failed`/`cancelled` states; a new submit mints a new idempotency key |
| Survive a connectivity loss without a click | the queue suspends scheduling on `offline` (in-flight PUTs are not aborted) and, on `online`, replays every file whose `failureKind` is `retryable` (`QueueOptions.autoRetryOnReconnect`, capped by `maxReconnectRetries`, announced through `onAutoRetry`) |
| No success before backend confirmation | phase `available` is set only after `commit` resolves |
| Server-side size/type limits | `api/transfer.py::validate_upload_policy` (see below) |

## Connectivity loss: what recovers by itself, and what does not

A cut in the middle of a PUT is not a decision: the bytes were never refused.
The queue therefore treats it as recoverable and rewinds it without asking.

- `offline` suspends the scheduler. Files that had not started stay `idle`
  ("En attente"); no new connection is opened on a dead link.
- An in-flight PUT still fails (the transport has no way to resume a single
  PUT), so `runTransfer` exhausts its own bounded retries and the item ends
  `failed` with `failureKind: "retryable"`.
- The queue keeps its `online` listener attached even once every file has
  settled. On `online` it resumes the scheduler and calls `retryTransient()`,
  which puts back only the `retryable` failures, with the same idempotency key
  (a multipart session keeps the parts already stored). The tray announces the
  replay, so a background recovery is never silent.
- `fatal` (bytes rejected, storage full, integrity failure), `expired` and
  `aborted` are never replayed: retrying them cannot succeed or would override
  a human decision. They keep the manual "Réessayer les échecs" control.
- `maxReconnectRetries` (default 3) bounds the automatic attempts per file, so a
  broken link cannot loop forever; a manual retry resets that budget.

Limits, stated plainly:

- The page must stay open. After a reload the browser cannot reopen a file by
  itself: the journal (`uploadJournal.ts`) keeps the metadata and the user
  re-selects the same files, and only the unconfirmed ones are sent again.
- A server that is unreachable while the browser still reports `onLine` raises
  no `online` event; those files stay `failed` and need the manual retry.

## Server-side transfer policy (authoritative)

`validate_upload_policy` runs before any intent row or presigned URL exists:

- **Media type**: normalized (lowercased/collapsed); a malformed type is `422`.
  An optional deployment allow-list (`AURA_ALLOWED_CONTENT_TYPES`, e.g.
  `image/png,application/pdf,text/*`) is enforced server-side. Empty = every
  valid type. A frontend `accept` attribute is never the policy.
- **Size**: `0 ≤ size ≤ AURA_MAX_OBJECT_BYTES`. The declared size is signed into
  the presigned PUT as `Content-Length`, and commit re-checks the actual stored
  size (defence in depth). `AURA_MAX_OBJECT_BYTES` must stay at or below the
  backend single-PUT limit until multipart is implemented.
- **Empty objects**: refused by default; `AURA_ALLOW_EMPTY_OBJECTS=1` enables
  them (commit still verifies `sha256("")`).

## Integrity: SHA-256, never ETag-as-checksum

The durable content fingerprint is the full-object SHA-256 computed by the
backend during commit (`stream_sha256`, bounded memory, one chunk at a time).
The presigned PUT is bound to a signed `Content-Length` and `Content-Type`, so
the gateway rejects a different size/type than the API authorized.

- ETag is **not** treated as SHA-256 and never becomes `checksum_sha256`.
- For a single PUT the ETag is often the object MD5, but AURA does not rely on
  that; a multipart ETag is explicitly a digest of part digests, not the file
  hash. `scripts/seaweedfs-compat-probe.py` demonstrates the distinction when
  run against a real endpoint.
- The API reports `checksum_algorithm: "sha256"` wherever a checksum is returned.

### The size contract is checked server-side, not only by the gateway

The signed `Content-Length` is a *gateway* control: it is enforced by the S3
backend, and that enforcement is verified live, not offline. The commit
therefore cross-checks the catalogue against the storage:

- the size declared at intent time (`expected_size_bytes`) must equal the size
  the gateway reports (`HEAD`), and the streamed total must equal it too;
- a mismatch marks the intent `failed`, drops the bytes best-effort (the
  reconciliation sweep retries a failed delete) and answers `422` — an object
  whose stored size differs from the authorised one never becomes `available`.

## Bounded commits (no unbounded wait)

A commit streams the object twice (HEAD, then the hash), so it can take minutes
on a large object. Three layers bound it, in this order:

1. the S3 client (`api/s3.py::make_client`) uses `connect_timeout=10`,
   `read_timeout=60` and adaptive retries (3) — a stalled backend fails instead
   of hanging the request;
2. the commit itself has a global deadline, `AURA_COMMIT_DEADLINE_S` (default
   300 s), checked between chunks: past it the object is **handed to the
   verification worker** (`202 verifying`) instead of being deleted. A slow disk
   under load is not corruption, and the former behaviour (mark `failed`, delete
   the bytes, `504`) discarded valid files;
3. the app proxy (`app/nginx.conf`) gives the commit route a 310 s read/send
   timeout (the default 60 s would cut the response and hide the API's own
   outcome), and Traefik's entrypoint allows `TRAEFIK_READ_TIMEOUT` (3600 s by default).

The API deadline stays below the proxy timeout on purpose, so the API's own
answer reaches the client instead of the proxy's generic `504`. Raise one,
raise all three.

### A PUT that runs long and then dies

Observed on the pilot (2026-10-22): 64 videos of 0.6-1.2 GB, four uploads in
parallel, aggregate ~1.5 MB/s. Each file got ~0.38 MB/s, so a PUT lasted longer
than Traefik's `readTimeout` (then 1200 s) and was cut at ~460 MB, restarted from
zero ("Nouvelle tentative (4)") and cut again: none could ever complete.

* `TRAEFIK_READ_TIMEOUT` (default now 3600 s) sets that limit; raise it for larger
  files or slower links.
* The engine detects the pattern: a single PUT that fails after at least
  `TransferConfig.longPutMs` (10 min) calls `onLongPutCut`, the queue drops its
  effective parallelism to 1 (the file gets the whole uplink) and retries once.
  A second cut stops the file as `failed`/`fatal` with an explicit message instead
  of looping for hours.
* The tray has an **Envois simultanés** selector (1-4, remembered per browser,
  `queue.setConcurrency`) and says when large files make parallel uploads a bad
  idea. Progress, rate and ETA are not shown while files are being re-sent
  ("estimation indisponible"): a retry restarts from zero.
* The real fix for files that cannot finish in one request is multipart (each part
  is a short request, a cut resumes at the failed part): see
  [MULTIPART-UPLOAD-PLAN.md](MULTIPART-UPLOAD-PLAN.md); it stays off until
  validated on SeaweedFS 4.48.

### Verification is deferred, and does not hold a queue slot

* From `AURA_VERIFY_ASYNC_THRESHOLD_BYTES` (32 MiB) `commit` answers
  `202 verifying`; the verifier (`api/verifier.py`) re-reads and hashes outside
  the request. A file is not downloadable or shareable until it is `available`.
* While an upload intent younger than `AURA_VERIFY_PAUSE_WINDOW_S` is pending, the
  verifier waits (`AURA_VERIFY_PAUSE_WHILE_UPLOADING`): the re-read costs 37-45 %
  of the PUT time when idle and was measured 5.8-7.1x slower under four
  concurrent writes (`engineering/commit-latency-bench.md`).
* In the browser, a file that gets `202` calls `onVerifying` and releases its
  upload slot (polling is capped at 5 s and does not block the next uploads).
* The antivirus hook runs on the synchronous commit and inside the verifier, so
  no path publishes an object without it.
* The periodic scrubber stamps a freshly verified object as just checked and
  yields while uploads are in flight, so a bulk import is not read a third time.

## Large files and multipart: analysis, gaps, proposal

**Decision: multipart is NOT implemented. No resumable/multipart behaviour is
simulated.** The mission explicitly requires examining the contract and the
pinned backend before implementing it, and forbids faking resume.

### What the contract and the pinned release allow

- The pinned image is `chrislusf/seaweedfs:4.48` (`.env.example`,
  `docker-compose.yml`). Its S3 gateway is documented to expose the standard
  multipart operations (`CreateMultipartUpload`, `UploadPart`,
  `CompleteMultipartUpload`, `AbortMultipartUpload`, `ListParts`) and Range GET.
  *This is documentation about SeaweedFS, not a verification of our deployment.*
- AURA's single-PUT path currently signs `Content-Length`. That is correct and
  complete for a single request, but it cannot resume: a dropped connection
  restarts the whole file, and a single request is bounded by the backend's
  single-PUT limit (`AURA_MAX_OBJECT_BYTES` defaults to 5 GiB).

### Known incompatibilities / unknowns (must be tested, not assumed)

1. **Presigning individual parts** must be verified on 4.48 (some S3-compatible
   servers differ on which headers a part URL may sign).
2. **Part checksum headers** (`x-amz-checksum-*`) and composite checksums have
   seen compatibility fixes in SeaweedFS; a closed upstream issue does not prove
   the pinned tag contains the fix or that the client sends the right headers.
3. **Multipart ETag ≠ full-file MD5/SHA-256**; commit must still compute
   SHA-256 itself (AURA already does).
4. **Abort/expiry cleanup** semantics and the maximum part size/count must be
   measured on 4.48; AWS limits (`≥5 MiB` parts, `≤10 000` parts) are not
   automatically SeaweedFS limits.
5. **Concurrency/part-size tuning** is a benchmark question, not a code guess.

### Proposed, testable implementation (not built here)

Follows `SECURE-BULK-TRANSFERS.md` and the P1 sequence there. The concrete,
checklist-style follow-up is in
[Multipart upload plan](MULTIPART-UPLOAD-PLAN.md).

1. Add a server-side multipart session bound to the upload intent (upload id,
   part size, expected size, intent expiry) — never trust a client-supplied
   upload id or key.
2. Presign each `UploadPart` (or a tightly scoped `CompleteMultipartUpload`)
   after re-authorization; persist part numbers/sizes/ETags server-side.
3. Client uploads parts with bounded concurrency, retries only failed parts and
   resumes from persisted part state; refresh only expired part URLs.
4. `Complete` only after validating the expected part list; then run the same
   SHA-256 commit verification as the single-PUT path.
5. Abort abandoned sessions after a documented grace period; reconcile them.
6. Gate the entire feature behind a compatibility test against 4.48 (below)
   before enabling it, and keep the single-PUT path as the default.

`scripts/seaweedfs-compat-probe.py` is the proposed compatibility gate: it is a
manual, guarded probe that verifies PUT/HEAD/GET/Range, presigned expiry,
multipart create/upload/complete/abort and the ETag-vs-SHA-256 distinction
against a real endpoint. It is **not** run in CI and was **not** run here.

## Security properties

- **Presigned URLs are bearer capabilities and are never logged.** Audit events
  carry object ids, buckets, sizes and statuses only (`api/audit.py` whitelist),
  and tests assert `X-Amz-Signature` never appears in the audit log.
- **No S3 credentials reach the browser.** Only per-object, short-lived,
  method-scoped URLs are returned; the signing keys stay server-side.
- **Signed headers and size are verified** by the gateway and re-checked at
  commit; the bucket comes from the space allow-list.
- **Double commits and timeouts** are safe: commit is idempotent, an upload that
  succeeded but was not committed stays `pending` for reconcile, and an
  accidental double submit cannot create a second object (`Idempotency-Key`).
- **Isolation is enforced on every route**: abort/commit/download all filter by
  the caller's space (and owner for humans); cross-space access is a 404, an
  unregistered bucket a 403.

## Test matrix — simulated vs. real

| Scenario | Test | Kind |
|---|---|---|
| Success, SHA-256 verified, signed headers | `tests/test_transfer_engine.py::test_upload_success_…`, `…signed_content_length_and_type` | offline, simulated S3 |
| Empty file (default refuse / enabled accept) | `test_empty_file_…` | offline, simulated S3 |
| Too large (intent 422 and commit 413) | `test_size_over_cap_…`, `test_object_larger_than_declared_…` | offline, simulated S3 |
| Interrupted storage (head/get error) | `test_storage_unreachable_…`, `test_unreadable_storage_…` | offline, simulated S3 |
| Expired intent | `test_expired_intent_…` | offline, simulated S3 |
| Repeated commit (idempotent) | `test_repeated_commit_…` | offline, simulated S3 |
| Validation error (size mismatch) | `test_truncated_upload_…` | offline, simulated S3 |
| Forbidden access (cross-space, read-only, anon) | `test_abort_and_commit_deny_cross_space`, `test_read_only_identity_…`, `test_anonymous_abort_…` | offline, simulated S3 |
| Abort/cancel semantics | `test_abort_…` (3 tests) | offline, simulated S3 |
| Content-type policy + normalization | `test_content_type_…` (3 tests) | offline, pure |
| Idempotent double submit | `test_same_idempotency_key_…`, `…scoped_to_the_actor`, `…invalid_…` | offline, simulated S3 |
| Audit log has no presigned URL/key | `test_audit_log_never_records_presigned_urls` | offline, simulated S3 |
| Frontend state machine (success, retry, expiry, cancel, never-fake-success, adaptive parallelism, paced starts, per-file retry) | `web/e2e/transfer-engine.spec.ts` (25) | executed, no browser |
| Frontend page (progress/phase, double-submit guard, error surfacing, expired-URL recovery, cancel) | `web/e2e/upload-flow.spec.ts` (5) | executed, mocked network + real Chromium |
| **PostgreSQL catalogue parity** (incl. new columns) | `tests/test_pg_parity.py` | **NOT run here** — needs `AURA_TEST_PG_DSN` |
| **Live SeaweedFS** round trip + presigned expiry | `tests/test_api.py::test_live_round_trip_with_integrity` | **NOT run here** — needs `AURA_LIVE_S3=1` |
| **Live multipart / checksum / Range compatibility** | `scripts/seaweedfs-compat-probe.py` | **NOT run here** — needs an explicit real endpoint |

### Explicitly not executed (reasons)

- **PostgreSQL**: no disposable PostgreSQL was available in this environment;
  the SQLite repository is exercised instead. The new columns are additive and
  written by both `api/db.py` and `api/db_pg.py`; `tests/test_pg_parity.py`
  should be run against a disposable database before the pilot.
- **SeaweedFS**: no real endpoint may be contacted from this environment
  (AGENTS.md prohibits touching the VPS). The single-PUT signed-header
  enforcement and multipart compatibility remain acceptance gates to run on the
  pilot, not claims of this change.

## Configuration added

| Variable | Default | Meaning |
|---|---|---|
| `AURA_ALLOW_EMPTY_OBJECTS` | `0` | Accept 0-byte intents when `1` |
| `AURA_ALLOWED_CONTENT_TYPES` | empty | Server-side media-type allow-list (`image/*`, `text/plain`, …) |
| `AURA_IDEMPOTENCY_KEY_MAX` | `200` | Max accepted `Idempotency-Key` length |

The verification, antivirus, scrubber, quota and SeaweedFS cache settings added
since are listed in
[ENVIRONMENT-CONFIGURATION.md](ENVIRONMENT-CONFIGURATION.md#transfer-and-integrity-settings-reference).

## Open questions / pending decisions

- Daily per-space quotas exist (`AURA_QUOTA_*_PER_DAY`, off by default) but the
  counter is in memory and per process; there is no per-tenant byte-rate limit.
  See `SECURE-BULK-TRANSFERS.md`.
- Antivirus scanning is an optional hook (`AURA_AV_SCAN_CMD`, off by default),
  not a quarantine workflow: an infected object is marked `failed` and its bytes
  deleted. It has only been exercised with a shell stub, not a real scanner.
- Whether the browser could send the SHA-256 with the PUT
  (`x-amz-checksum-sha256`) and let SeaweedFS 4.48 verify it, which would remove
  the re-read, has not been proven.
