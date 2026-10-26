# S3 multipart upload for large objects (#72)

**Status (2026-10-26): implemented in code behind `AURA_MULTIPART_ENABLED`
(default off); the compatibility gate below has been RUN against the pinned 4.48 image
and is CLOSED for items 1–6, with two UNKNOWNs that the S3 API cannot answer (disk
reclaim after abort, and a real 10,000-part completion) — see the
[verification log](verification-log-2026-10-25-multipart-compat-4.48.md).** What exists:
two additive columns on `objects` (`multipart_upload_id`,
`multipart_part_bytes`), `GET /api/v1/objects/{oid}/multipart` (plan + parts
held, read from the backend with `ListParts`), `POST .../multipart/parts`
(≤100 presigned part PUTs, each with a signed exact length), completion inside
`commit` followed by the unchanged full-object SHA-256, abort/soft-delete/
reconcile aborting the session, and the browser engine in
`web/src/lib/transfer.ts` (bounded part concurrency, per-part retry, URL
renewal, resume from the parts held; the upload journal keeps the idempotency
key so a reload resumes the same session). Offline tests:
`tests/test_multipart.py`, `web/e2e/multipart-engine.spec.ts`,
`web/e2e/multipart-resume.spec.ts`. Deviation from the draft below: no
`multipart_parts` table — the backend part list is authoritative and read at
status/commit time. Enable only after items 1–6 of the gate are recorded.

Original proposal follows.

The M03 transfer engine originally shipped single presigned PUT only. See [Vault transfer engine](TRANSFER-ENGINE.md)
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
current mitigation is a bounded `readTimeout` (7200s) in `docker-compose.yml`;
that buys time but a single request per object remains the wrong shape. It also
sizes multipart parts: each part PUT is itself a request through the same proxy,
so `part_size_bytes / worst_case_bandwidth` must stay comfortably below
`readTimeout`, independently of the backend's own part limits.

The 7200s sizing arithmetic is in
[verification-log-2026-10-25-multipart-proxy-4.48.md](verification-log-2026-10-25-multipart-proxy-4.48.md):
at 64 KiB/s a 450 MiB part is the absolute ceiling and 225 MiB the comfortable one, while
the 16 MiB code default is 256.0s (3.56% of the deadline).

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

**Recorded 2026-10-25 — executed, not a clean pass.** The gate was run against
`chrislusf/seaweedfs:4.48` in an isolated throwaway stack: `failures=0` (36 passes,
`unknowns=1`), harness exit code 0, one UNKNOWN (disk-level reclaim after abort is not
provable from volume stats; only the S3 API guarantee is verified). Full evidence:
[verification-log-2026-10-25-multipart-compat-4.48.md](verification-log-2026-10-25-multipart-compat-4.48.md).
The run used the dedicated isolated harness (`tests/multipart-compat-4.48.sh`, boto3
client plus a plain-`urllib` part consumer) rather than the manual probe script
described below; both are acceptable gate paths, the harness is the reproducible one.

Coverage against items 1–6 below: item 1 is exercised (harness assertion; no
failure counted); item 2 is covered by a third run (see below); **item 3 is covered** by this
run: a signed `x-amz-checksum-sha256` on a presigned `UploadPart` is accepted (HTTP
200 and echoed), the same header unsigned is rejected (403 `SignatureDoesNotMatch`),
a signed wrong digest is rejected (400 `BadDigest`), and the value is **not
persisted** — `ListParts`, Complete and `HeadObject(ChecksumMode=ENABLED)` expose no
checksum (POINT 9 in the
[verification log](verification-log-2026-10-25-multipart-compat-4.48.md)), so the
gateway validates a supplied checksum but cannot serve as a checksum store; item 4 is
consistent with the evidence (completed ETag `…-2`, integrity verified by SHA-256,
never by ETag; no full-object MD5 comparison was printed); item 5 is covered by a third
run (see below).
**Item 6 (part PUTs through Traefik plus `readTimeout` sizing) is now covered** by a
second run on 2026-10-25: a slow 5 MiB presigned part PUT through Traefik with
`readTimeout=7200s` returned 200 in 80.008s with an ETag equal to the local MD5 of the
bytes sent, the identical upload through a default-60s Traefik was cut off at 60.0s,
and at a conservative 64 KiB/s the 7200s deadline allows a 450 MiB part (225 MiB at half
the budget) — see
[verification-log-2026-10-25-multipart-proxy-4.48.md](verification-log-2026-10-25-multipart-proxy-4.48.md).
**Items 2 and 5 are now covered** by a third run on 2026-10-26 (47 passes, 0 failures,
2 UNKNOWN, harness exit 0). Item 2: the gateway *does* enforce the signed part size — one
byte more or one byte fewer than the signed `Content-Length` is rejected with 403
`SignatureDoesNotMatch`, and the same wrong-sized body is accepted when the URL is
presigned without `ContentLength`, which proves the enforcement is SigV4 verification of
the signed header and not an S3 size rule. `presigned_upload_part` (`api/s3.py:222-233`)
always signs the length, so the guarantee holds today; **dropping `ContentLength` from
that presign would silently remove it**, because part PUTs carry no signed payload hash —
the signed length is the only integrity bound. Item 5: `CompleteMultipartUpload` rejects
a non-last part below 5 MiB with `EntityTooSmall`, part 10000 is accepted while 10001 is
rejected with `InvalidPart`, and Range GET works on a completed multipart object,
including a range spanning a part boundary.

Two deviations worth knowing, neither a blocker:

- **Error code mismatch.** `Complete` referencing an out-of-range part number answers
  **404 `NoSuchUpload`** instead of 400 `InvalidPart`. A generic S3 client that maps
  `NoSuchUpload` to "the upload is gone, start over" would restart the whole upload on a
  bad part list. AURA is not exposed: `_complete_multipart_session` builds its part list
  from `ListParts` filtered to `1..count` (`api/main.py:1234-1251`), so it never
  references an out-of-range part.
- **`plan_parts` is not the 8 MiB it looks like.** The preference is raised as the object
  grows: 100 GiB uses 11 MiB parts (9,310), 1 TiB uses 105 MiB (9,987), and the 10,000
  ceiling only binds around 50 TiB. Any concurrency or part-count assumption based on
  "8 MiB parts" is wrong for large objects.

Still **not** exercised: a real 10,000-part `Complete` (≈48.8 GiB of parts) and disk-level
reclaim after abort. Both are recorded as UNKNOWN in the verification log.

The gate is therefore **closed by measurement for items 1–6**, with those two UNKNOWNs
explicitly out of reach of the S3 API. State observed on the pilot on 2026-10-25:
`AURA_MULTIPART_ENABLED=1`, `AURA_MULTIPART_PART_BYTES=5242880`,
`AURA_MULTIPART_THRESHOLD_BYTES=33554432` (`docker exec aura-001-api printenv`), which
is **not** the code default of `0`.

The gate can be measured two ways, both against the exact pinned
`chrislusf/seaweedfs:4.48` and never against the pilot: the dedicated isolated harness
(`tests/multipart-compat-4.48.sh`, the path taken on 2026-10-25) or
`scripts/seaweedfs-compat-probe.py` against a **disposable** bucket, which is the only
one of the two that can also point at a real endpoint. The "candidate client library"
check from the original wording is obsolete: the client here is the AURA browser
transfer engine (`web/src/lib/transfer.ts`), not a third-party SDK, and it is exercised
by `web/e2e/transfer-engine.spec.ts`. Record the image tag and results. Confirm
specifically:

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
