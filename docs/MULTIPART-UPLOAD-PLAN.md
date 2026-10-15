# Follow-up proposal — S3 multipart upload for large objects (not implemented)

**Status:** proposal / issue draft. **Nothing here is implemented.** The M03
transfer engine deliberately ships single presigned PUT only; no multipart or
resumable behaviour is simulated. See [Vault transfer engine](TRANSFER-ENGINE.md)
for what exists today and [Secure and Efficient Bulk Transfers](SECURE-BULK-TRANSFERS.md)
for the broader plan. This document turns the "large files" gap into a concrete,
testable work item.

## Problem

Today a single presigned PUT carries a signed `Content-Length` and is verified at
commit. That is correct and complete for one request, but:

- a dropped connection restarts the whole file;
- a single request is bounded by the backend single-PUT limit, so
  `AURA_MAX_OBJECT_BYTES` (default 5 GiB) cannot grow safely;
- slow/unstable links cannot resume at part granularity.

The pinned image is `chrislusf/seaweedfs:4.48`. Its S3 gateway is *documented* to
expose multipart and Range, but that has not been verified on our deployment.
AWS limits and SeaweedFS limits must not be assumed interchangeable.

### Measured constraint: the edge proxy deadline (2026-10-15)

The pilot runs behind Traefik, whose default `respondingTimeouts.readTimeout`
is **60s** — the maximum time it spends reading a request, body included. A
presigned PUT carries the whole object as one request, so on the pilot any
upload whose body takes more than 60s is cut mid-transfer: the proxy answers
HTTP 502 and the browser XHR reports a network error (`xhr.onerror`, status 0,
"Réseau interrompu." in the UI). This was reproduced against the live pilot with
throttled PUTs of a single 37.5 MB object:

| Client rate | Result | Wall time |
|---|---|---|
| 300 KB/s | HTTP 502, 18.4 MB of 37.5 MB sent | 60.05 s |
| 500 KB/s | HTTP 502, 30.9 MB sent | 60.53 s |
| 1024 KB/s | HTTP 200, completed | 35.5 s |
| slow download (>60s) | HTTP 200 | — |

The cutoff is **request-direction only** (a download over 60s completes), which
matches `readTimeout` semantics rather than a total connection lifetime. The
current mitigation is a bounded `readTimeout` (1200s) in `docker-compose.yml`;
that buys time but a single request per object remains the wrong shape. It also
sizes multipart parts: each part PUT is itself a request through the same proxy,
so `part_size_bytes / worst_case_bandwidth` must stay comfortably below
`readTimeout`, independently of the backend's own part limits.

## Goals

- Upload large objects as independently retransmittable parts, resuming without
  resending completed parts.
- Keep the API as the control plane: server-generated keys, server-issued part
  capabilities, server-side session state.
- Preserve the existing integrity contract: full-object SHA-256 is computed and
  verified by the backend at commit; ETag is never treated as SHA-256.
- Fail safely: bounded memory in the API, idempotent completion, abort and
  reconcile abandoned sessions.

## Non-goals

- No tus gateway (only if a future requirement cannot use presigned S3 multipart).
- No client-side envelope encryption, no cross-tenant dedup.
- No change to the single-PUT default for small/medium files.

## Compatibility gate (do this first — blocks the rest)

Run `scripts/seaweedfs-compat-probe.py` against a **disposable** bucket on the
exact pinned `chrislusf/seaweedfs:4.48`, then against a candidate client library.
Record the image tag and results. Confirm specifically:

1. `CreateMultipartUpload` / `UploadPart` / `CompleteMultipartUpload` /
   `AbortMultipartUpload` / `ListParts` succeed.
2. **Presigning individual part URLs works** and the gateway enforces the signed
   headers/size on each part.
3. `x-amz-checksum-*` behaviour on parts and on completion (composite vs full),
   including any known upstream fixes; decide whether to rely on it at all.
4. Multipart ETag ≠ full-object MD5/SHA-256 (the probe prints this).
5. Minimum part size, maximum part count, and Range GET on a completed object.
6. Part-URL PUTs **through the edge proxy** (Traefik), not only directly against
   the S3 gateway, plus the largest part size that completes within the
   configured `readTimeout` at the slowest client rate to support.

Do not start implementation before 1–6 are recorded; do not reuse AWS numbers as
if they were SeaweedFS numbers.

## Contract additions (draft)

Proposed routes, extending the existing upload-intent model:

- `POST /api/v1/objects/upload-intents` — add `upload_mode: "single" | "multipart"`
  and, for multipart, a `part_size_bytes` chosen **server-side** (client may send
  a preference; the server decides). The response adds
  `multipart: { upload_id?, part_size_bytes, max_parts }` once the session exists.
- `POST /api/v1/objects/{oid}/multipart` — create/return the pending session and
  a bounded batch of presigned `UploadPart` URLs (part numbers are server-assigned
  and range-checked against `expected_size_bytes`).
- `POST /api/v1/objects/{oid}/multipart/parts` — request presigned URLs for
  specific, still-missing part numbers after re-authorization (resume/refresh).
- `POST /api/v1/objects/{oid}/commit` — unchanged semantics: the server validates
  the expected part list, completes the multipart upload itself, then streams and
  verifies the full-object SHA-256 before `available`. Alternatively a dedicated
  `.../multipart/complete` that finishes by calling the same commit verification.
- `POST /api/v1/objects/{oid}/abort` — already exists; must also
  `AbortMultipartUpload` the session.

No client-supplied `upload_id`, `bucket`, `key` or arbitrary part numbers are
trusted; all are validated against server-side session state.

## Server-side state

Add a `multipart_uploads` table (additive migration, SQLite + PostgreSQL parity):

- `id` (session id, canonical UUID v4), `object_id` → `objects.id`,
  `upload_id` (backend upload id, never returned except as needed), `part_size`,
  `expected_parts`, `created_at`, `expires_at`, `status`
  (`initiated`/`completing`/`completed`/`aborted`/`expired`).
- `multipart_parts`: `session_id`, `part_number`, `size_bytes`, `etag`,
  `checksum` (nullable), `uploaded_at` — server-side record of what was accepted.

The object row keeps `status='pending'` until commit verification passes.

## Client flow and recovery (web/src/lib/transfer.ts)

Extend the existing state machine rather than adding a second one:

- Phases: `requesting-intent → (initiating-multipart) → uploading-parts →
  completing → validating → available` (plus `failed`/`cancelled`).
- Bounded part concurrency (start 3–4, tunable); retry only failed parts with the
  existing exponential backoff + jitter; never retry auth/checksum failures.
- Persist nothing beyond the current session in memory (or IndexedDB with a
  threat review, TBD); a reload re-authorizes and asks for still-missing parts.
- Aggregate progress from per-part progress; show parts done / total.
- Cancel aborts the in-flight part XHRs and calls the backend `abort`, which
  aborts the multipart session.

## Integrity

- Per-part checksums only if the compatibility gate proves them; otherwise rely
  on the TLS transfer plus the final full-object SHA-256.
- `CompleteMultipartUpload` is followed by the same bounded-memory
  `stream_sha256` verification as the single-PUT path.
- Store `checksum_algorithm: "sha256"`; never compare an ETag to a SHA-256.

## Lifecycle and reconciliation

- Abort abandoned sessions after a documented grace period (extend
  `api/lifecycle.py::reconcile_pending`).
- A multipart object that succeeded in S3 but failed commit stays `pending` and
  is retried/resolved by reconciliation; never mark `available` on progress alone.

## Acceptance criteria

- [ ] Compatibility gate (1–6 above) passed and recorded with the image tag.
- [ ] API memory stays bounded as object size grows (part URLs only in memory).
- [ ] Interrupted transfer resumes at part granularity; completed parts are not
  retransmitted.
- [ ] Duplicate `complete`/`commit` is idempotent; duplicate part number is
  rejected or overwritten deterministically.
- [ ] Abandoned sessions are aborted after the grace period and never leak bytes.
- [ ] Full-object SHA-256 verified before `available`; ETag never used as SHA-256.
- [ ] No S3 credentials in the browser; part URLs are bounded, per-part,
  short-lived capabilities.
- [ ] Isolation unchanged: cross-space access is 404, unregistered bucket 403.

## Test plan

**Offline (CI, simulated S3):** expected-part-list validation, missing/extra part
rejection, duplicate complete idempotency, expired session, abort, checksum
mismatch, part-size/count limits, bounded memory, cross-space denial. Extend
`tests/test_transfer_engine.py` and add `tests/test_multipart.py`.

**PostgreSQL:** extend `tests/test_pg_parity.py` for the two new tables, plus the
offline interface guard `tests/test_repository_parity.py`.

**Live (manual, disposable bucket on the pinned release):** the compatibility
probe, an end-to-end multipart upload with a forced mid-transfer interruption and
resume, an expired part-URL refresh, and an abandoned-session abort. These are
acceptance gates, not CI.

## Rollout

Ship behind a server flag (`AURA_MULTIPART_ENABLED`, default off, plus a
size threshold such as 64–100 MiB chosen from the benchmark). Keep the single-PUT
path as the default until the gate and the live tests pass.

## Risks / open questions

- SeaweedFS part-checksum compatibility has seen upstream fixes; the pinned tag
  must be verified rather than assumed.
- Where to persist resume state on the client (memory vs IndexedDB) needs a
  privacy/threat review before deciding.
- Part-size/concurrency defaults are benchmark questions, not guesses.

## Task breakdown (issue checklist)

1. [ ] Run and record the compatibility gate on 4.48, including the edge-proxy
   part-size/`readTimeout` measurement.
2. [ ] Add `multipart_uploads` / `multipart_parts` migrations (both backends) + parity tests.
3. [ ] Add the multipart session/part endpoints with server-side validation.
4. [ ] Presign part URLs after re-authorization; keep keys server-side.
5. [ ] Extend `transfer.ts` with parts, bounded concurrency, per-part retry/resume.
6. [ ] Commit verification + lifecycle abort/reconcile.
7. [ ] Offline + PostgreSQL tests; document results in a verification log.
8. [ ] Live benchmark (part sizes, concurrency) and threshold decision.
9. [ ] Enable behind the flag after green gates.
