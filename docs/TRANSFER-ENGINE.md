# AURA Vault Transfer Engine (M03)

**Status:** implemented in code (`api/transfer.py`, `api/main.py`, `api/s3.py`,
`api/migrations.py`, `web/src/lib/transfer.ts`, `web/src/lib/api.ts`,
`web/src/pages/ObjectsPage.tsx`) and covered by offline tests
(`tests/test_transfer_engine.py`) and browser tests
(`web/e2e/transfer-engine.spec.ts`, `web/e2e/upload-flow.spec.ts`).
Validated on SQLite and an in-process S3 stub. **Not yet validated against
PostgreSQL or the pinned SeaweedFS release** — see *Test matrix*.

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
| 3. API issues a short-lived URL | `api/s3.py::presigned_put` | SigV4, exact bucket/key, signed `Content-Length` + `Content-Type` |
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
  checks the size and computes SHA-256.
- `available` — **only** reached when commit returned success. The UI never
  infers success from the upload PUT alone.
- `failed` / `cancelled` — terminal, with the reason shown.

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
| Adaptive parallelism + paced starts | the queue shrinks its effective parallelism after repeated congestion failures (network/5xx/expired, never fatal/cancelled) and restores it after sustained success; parallel PUT starts are staggered (`QueueOptions.startStaggerMs`). JDownLoader-inspired, adapted from chunks to whole files |
| Distinguish upload / validation / availability / failure | the five phases above |
| Handle expired URLs and network errors | 403 → new intent; network/5xx → retry; both bounded |
| Clean local state after failure | `failed`/`cancelled` states; a new submit mints a new idempotency key |
| No success before backend confirmation | phase `available` is set only after `commit` resolves |
| Server-side size/type limits | `api/transfer.py::validate_upload_policy` (see below) |

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
| Frontend state machine (success, retry, expiry, cancel, never-fake-success, adaptive parallelism, paced starts) | `web/e2e/transfer-engine.spec.ts` (22) | executed, no browser |
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

## Open questions / pending decisions

- AURA does not enforce a per-app/per-tenant quota or rate limit on byte
  transfers yet; only a per-scope pending-intent cap and the login/M2M rate
  limiters exist. This is tracked in `SECURE-BULK-TRANSFERS.md` (P0/P1) and is
  **not** part of this change.
- Quarantine/AV scanning is not implemented; objects go straight from `pending`
  to `available` after integrity checks.
