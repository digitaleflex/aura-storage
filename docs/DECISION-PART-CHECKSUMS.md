# Decision — per-part checksums and client-attested `checksum_sha256`

**Status: DEFERRED — reviewed and not approved (2026-10-25).** This document records a
proposal, the evidence behind it, and why it was not adopted. No code, schema or API
change is made by it.

## Context

Today `checksum_sha256` is always computed by the server from the object's bytes, but
*where* that happens depends on size:

- below `verify_async_threshold_bytes` (32 MiB) the commit request reads the object back
  and streams it through `stream_sha256` (`api/s3.py:161-180`) before marking the object
  `available`;
- at or above that threshold, commit completes the S3 session, marks the object
  `verifying` and returns `202` (`api/main.py:1486-1494`); the verification worker then
  performs the same full streamed read and marks it `available` (`api/verifier.py:104,132`).

So the read is **not** commit-blocking for large objects — an earlier draft of this
record claimed otherwise and was wrong. What remains true: it is still one full read of
every object against the storage tier, the scrubber re-reads periodically to compare
against the stored digest (`api/scrubber.py:50-63`), and time-to-`available` still
scales with object size. There is no partial shortcut, because nothing about the
individual parts is retained.

## Evidence (SeaweedFS 4.48, 2026-10-25)

Source: [verification log](verification-log-2026-10-25-multipart-compat-4.48.md),
points 8–10 (harness summary `failures=0 unknowns=1 passes=36`).

- **A part's ETag is exactly the MD5 of that part's bytes.** Confirmed byte-for-byte on
  four shapes: 5 MiB, 5 MiB + 4099 bytes (non-aligned), 3 bytes, and 0 bytes
  (`d41d8cd98f00b204e9800998ecf8427e`, the 0-byte part was accepted).
- **The completed ETag is `md5(concat(part MD5 bytes))-N`.** Point 10: three parts of
  5,242,880 / 5,251,071 / 4,000 bytes complete and HEAD as
  `"2eca9979f6e33744ed05ea0285420b39-3"`, which equals the locally computed composite.
  It is MD5-based; it is neither a whole-object MD5 nor a SHA-256.
- **No checksum is persisted by the gateway.** `x-amz-checksum-sha256` is accepted (and
  echoed) only when it is inside the presign signature; the value is validated (a wrong
  digest is rejected with 400 `BadDigest`) but `ListParts`, `CompleteMultipartUpload`
  and `HeadObject(ChecksumMode=ENABLED)` return no checksum field. The
  server-computed `x-amz-checksum-crc32` on each `UploadPart` response is likewise not
  persisted.
- **The part ETag is browser-readable; the checksum echo is not.** CORS
  `Access-Control-Expose-Headers` lists `ETag, Content-Length, Content-Type,
  Last-Modified, x-amz-request-id, x-amz-version-id`. `x-amz-checksum-sha256` is
  absent, so JavaScript cannot read the echoed checksum — while it can read the ETag.

## Proposed model

1. The browser computes **MD5 per part** while sending the part, then compares it to
   the part's ETag in the `UploadPart` response. ETag is CORS-exposed, so this is a
   direct read. A mismatch means the part arrived corrupted: retry it, never count it.
2. On commit the browser reports `{part_number, md5}` for every part it uploaded to the
   AURA API. The server treats that as a **claim**, not a proof.
3. The API calls `ListParts` and compares each reported MD5 to the ETag of the same
   part number (normalising the surrounding quotes), and checks the part numbers and
   sizes against the server-side plan. This is a **server-authoritative equality
   proof**: the reference value is produced by the gateway from the bytes it received.
   No object is read.
4. The browser also computes the **whole-object SHA-256 incrementally** while reading
   the file — a byte it has to read anyway to upload. That digest is sent with the
   commit and becomes the object's `checksum_sha256`. It is
   **client-attested**: its correctness follows from the part chain. If every part's
   MD5 matches the server's part MD5, the bytes the client hashed are the bytes stored
   (modulo MD5 collisions, see the risks), and the SHA-256 over their concatenation is
   the SHA-256 of the stored object. The chain must cover the complete part list, not a
   subset.

Ordering matters: the `ListParts` comparison must happen **before**
`CompleteMultipartUpload`, while the part list still exists, and `Complete` must be
given the exact ETag list that was compared. Otherwise the compared parts and the
assembled parts can differ.

## Invariant change (stated bluntly)

`checksum_sha256` **stops being independently computed by the server for multipart
objects**. The server will no longer be able to say "I read these bytes and hashed
them" for a multipart object; it can only say "the client's per-part hashes match mine,
and the whole-object hash is the client's". That is a weaker claim, and it must be
visible as such rather than hidden behind a field that looks unchanged.

- Record provenance next to the digest, e.g.
  `checksum_source = server_stream | client_attested_chain` (naming to be settled at
  implementation), and expose it wherever `checksum_sha256` is exposed (API response,
  audit event, UI/export as appropriate).
- Keep the `server_stream` path, and keep it the only path for **single-PUT** objects.
  It is also the fallback: multipart with the feature off, a client that cannot produce
  per-part MD5s, an incomplete chain, or an operator flag that forces a full
  re-verification.
- `api/scrubber.py:63` still re-reads and compares against `checksum_sha256`, so the
  independent check is not lost — but it runs later (scheduled scrub), not at commit,
  and cannot be a substitute for commit-time evidence.

## Open risks

- **WebCrypto has no MD5.** A JavaScript MD5 implementation has to be shipped, reviewed
  and tested against known vectors. It runs over every uploaded byte; on large files
  that cost must be measured, not assumed.
- **The checksum echo header is not CORS-exposed today.** The proposal does not depend
  on it — it uses the ETag — but any client that wanted the gateway's echoed
  `x-amz-checksum-sha256` would need a CORS change on the gateway/proxy, and that
  behaviour has not been tested in a real browser.
- **MD5 is a corruption check, not a security primitive.** MD5 collision resistance is
  broken. These digests detect transfer/storage corruption and prove that the client
  and the gateway saw the same bytes; they are not an authenticity proof for the
  content and must not be presented as one.
- **Objects uploaded before the change have no part manifest.** They keep a
  `server_stream` checksum and cannot be retro-attested; attesting them would require
  exactly the re-read this proposal removes. A backfill is a separate decision.
- **A re-uploaded part between `ListParts` and `Complete`** would break the chain
  unless the compared ETags are the ones handed to `Complete`. This is an
  implementation requirement, and a test case.
- **Multi-gigabyte browser hashing** is unbounded work on the client (main-thread
  starvation, memory, mobile). Whether to hash whole objects above a size threshold,
  and how to do it off the main thread, is unresolved.

## Status

**DEFERRED — reviewed 2026-10-25, not approved.** The evidence above is solid and the
mechanism works, but an adversarial review concluded the trade is bad for this
deployment. Reasons, in order of weight:

1. **Time-of-check/time-of-use race.** A part re-uploaded (another tab, a retry, a
   stale session) between the client's report and `CompleteMultipartUpload` breaks the
   chain unless the ETags compared are exactly the ones handed to `Complete`. Getting
   this wrong stores a corrupt object marked `available` — the failure mode is silent.
2. **It redefines `checksum_sha256` for every consumer.** The digest stops being
   server-verified and becomes client-attested: `api/scrubber.py:63` compares against
   it, the verifier writes it, admin reverify checks it, `docs/openapi.yaml` documents it
   as "streamed server-side", and any future dedup key would inherit the weaker
   provenance. That is a permanent semantic change, not an optimisation.
3. **Real client cost.** WebCrypto has no MD5 (new JS implementation required), per-part
   MD5s must be cached per `(intent, part)` so a retry reuses the same digest, and
   multi-gigabyte hashing has to be kept off the main thread.
4. **No measured problem.** For objects ≥ 32 MiB the read already sits off the commit
   path in the verification worker, so the latency win is theoretical on a
   single-VPS pilot that is not yet accepted for production.

`checksum_sha256` is unchanged and remains server-computed. `AURA_MULTIPART_ENABLED`
stays off until plan gate item 6 (part PUTs through Traefik plus `readTimeout` sizing)
is covered.

**Reopen only if all of the following hold:**

- multipart is re-enabled in production (not merely planned);
- the server-side hash is measured at > 30 % of p50 commit latency for multipart objects
  ≥ 10 GB, over ≥ 7 consecutive days, on the target environment;
- the implementation requirements are agreed up front: `ListParts` (current server
  state) is authoritative for all parts `1..N` before `Complete` and the client's ETag
  list is never used to build the parts array; `checksum_source`
  (`server_stream | client_attested_chain`) is stored and surfaced; scrubber, verifier
  and admin reverify understand the new provenance; per-part MD5s survive retries; and
  race tests cover overwrite, duplicate, missing and paginated parts.

## References

- [Verification log 2026-10-25 (points 8–10)](verification-log-2026-10-25-multipart-compat-4.48.md)
- [S3 multipart upload plan](MULTIPART-UPLOAD-PLAN.md), compatibility gate items 3 and 6
- Server-side hash: `api/s3.py:161-180` (`stream_sha256`), commit path in `api/main.py`
- Scrubber comparison: `api/scrubber.py:63`
