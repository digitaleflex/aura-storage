# Secure and Efficient Bulk File Transfers

**Status:** engineering design and benchmark plan. This is not evidence that the controls are implemented or that performance has been measured on the production VPS.

## Objective

Make AURA safe and efficient for many files, large files, slow or unstable connections, and repeated uploads from multiple consuming platforms. Optimize for measured end-to-end throughput and reliability, not for a single theoretical algorithm.

AURA stores private files for consuming platforms. Each platform remains responsible for its end users and product entitlements. AURA enforces application/tenant isolation, storage permissions, quotas, integrity and lifecycle controls. It does not implement billing.

## Research-backed decisions

1. **Direct S3 transfer with short-lived presigned URLs:** keep binary data off the FastAPI request path. The API is the control plane; SeaweedFS/S3 is the data plane.
2. **Multipart upload for large objects:** independently transfer bounded parts, retry only failed parts, then complete the upload. Amazon recommends considering multipart around 100 MB; treat that as a starting reference, not a universal threshold. Benchmark the pinned SeaweedFS release and actual network before choosing AURA's threshold. The SeaweedFS S3 API documents multipart operations, but exact behavior must be tested against the deployed version. Sources: [AWS multipart upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html), [SeaweedFS S3 API](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API).
3. **Resumability:** for S3 multipart, persist the upload ID and completed part numbers/ETags/checksums so an interrupted transfer can resume without retransmitting completed parts. Use the tus protocol only if AURA deliberately adds a tus-compatible upload gateway; tus is not automatically required on top of presigned S3 multipart. Source: [tus protocol](https://tus.io/protocols/resumable-upload).
4. **Integrity:** verify per-part checksums where the exact S3-compatible implementation supports them, and calculate a full-object SHA-256 for catalogue integrity when feasible. CRC32C/CRC checks are useful for fast accidental-corruption detection; SHA-256 is the durable content fingerprint. Never assume a multipart ETag equals the full file's MD5 or SHA-256. AWS's checksum semantics are documented here: [S3 upload integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html).
5. **Compression only when beneficial:** use streaming Zstandard (zstd) as an optional preprocessing choice for compressible text-like payloads, logs, JSON, CSV and similar data. Do not automatically recompress PDF, JPEG/PNG, MP4, ZIP, gzip or other formats that are already compressed; this often wastes CPU and can increase latency with little size reduction. Preserve original bytes by default. Compression must be an explicit, versioned representation decision, not a transparent mutation of user documents. Source: [Zstandard format](https://github.com/facebook/zstd/blob/dev/doc/zstd_compression_format.md).
6. **Defense in depth for untrusted files:** allowlist required types where the business case permits; do not trust filename extension or client Content-Type alone; use generated storage keys; cap file size, archive expansion and processing resources; scan or quarantine where appropriate. Source: [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

These sources describe protocol/tool capabilities and general security practices. They do not prove equivalent checksum, encryption or multipart behavior for the exact AURA deployment. Compatibility tests are mandatory.

## Recommended transfer pipeline

### A. Batch preparation

- Accept a manifest of files with a stable client-side item ID, original filename for display only, byte size, declared media type, optional SHA-256, and logical destination.
- Validate manifest schema, number of entries, total declared bytes, per-file limits and destination permissions before creating a large batch.
- Create an import/batch job with states such as queued, running, partially_failed, completed, failed and cancelled.
- Generate opaque object IDs and storage keys server-side. Never derive storage paths from user filenames.
- Reject duplicate manifest IDs and make job creation idempotent with an idempotency key.

### B. Scheduling and concurrency

- Use a bounded client queue rather than starting every file and every part simultaneously.
- Start with a conservative configurable concurrency, for example 3-4 active files and 2-4 active parts per large file; these are initial test values, not promised optimal settings.
- Apply a global per-application and per-tenant concurrency cap at the service level, plus disk-capacity safeguards. Client-side limits alone do not protect the server.
- Adapt concurrency based on measured throughput, retry rate, latency and server saturation. Reduce concurrency after repeated timeouts/429/5xx responses; increase cautiously when stable.
- Avoid parallelizing tiny files into multipart requests. Batch their authorization/manifest operations, but keep each object as a separate authorized object unless a real archive is explicitly desired.
- Use bounded exponential backoff with jitter for retryable network/server errors. Do not retry authorization failures, checksum mismatches or invalid requests blindly.

### C. Single PUT versus multipart

- Single PUT for small/medium objects when reliable and supported by the tested stack.
- Multipart for large objects or where resumability provides clear value. Benchmark thresholds such as 32, 64 and 100 MiB rather than treating one value as universally correct.
- Pick a part size using tests, with a reasonable starting matrix such as 8, 16 and 32 MiB; respect the actual S3-compatible service's part-count and part-size limits. Do not assume AWS limits automatically equal SeaweedFS limits.
- Presign each permitted part or a tightly scoped multipart action server-side. Never expose long-lived S3 credentials to browsers or mobile clients.
- Store multipart upload ID, expected object key, intent expiry, part numbers, sizes and integrity values in server-side state. Do not trust client-supplied bucket/key or arbitrary upload IDs.
- Complete only after validating the expected part list and authorization. Abort abandoned multipart uploads after a documented grace period; do not immediately delete after a transient error.
- For tiny files, use a bounded queue and avoid multipart overhead.

### D. Retry and resume

- Persist batch ID, item ID, upload intent ID, multipart upload ID and completed part metadata in a durable client/server-safe way. Persist no presigned URL longer than needed; a new URL can be issued after reauthorization.
- Retry only failed parts where possible; do not restart the whole file if the underlying multipart upload is still valid.
- Refresh expired presigned URLs by requesting new URLs after AURA rechecks authorization. Never extend an old URL by altering its query string.
- Make commit and batch retries idempotent. A repeated request must not create duplicate catalogue records or replace an unrelated object.
- If storage upload succeeded but catalogue commit failed, keep the item pending and reconcile it. Never mark it available based only on client progress.
- Surface actionable per-file failures and allow retrying failed items without re-uploading successful items.

## Security and confidentiality

### Access isolation
- Every application has a distinct machine identity per environment and a least-privilege policy. Every object and upload intent is bound to a tenant/application scope.
- Authorize every metadata read, upload intent, multipart operation, commit, download intent, delete and restore. Test cross-tenant and cross-application negative cases.
- Use opaque server-generated keys; do not leak bucket names, internal endpoints, local paths or secrets.
- Presigned URLs are bearer capabilities. Use short expiry, exact object/method scope, HTTPS, redaction from logs, and no analytics/telemetry collection of query strings.

### Encryption
- Require HTTPS/TLS in transit.
- Require and verify SeaweedFS server-side encryption (SSE-S3) on the pinned deployment; confirm actual response metadata and round-trip bytes in an acceptance test. Store the encryption key backup separately and offline as the repository's security policy requires.
- Consider **optional client-side envelope encryption** only for data classes that require protection from storage operators or server-side compromise. It requires a real key-management and recovery design, per-object data keys, authenticated encryption, versioned encryption metadata and tested key rotation/recovery. It also limits server-side preview, content scanning and indexing. Do not invent a custom cryptographic format or make client-side encryption mandatory before key recovery is designed.
- Do not treat compression as encryption or checksum as authenticity.

### Malicious or malformed files
- Do not trust extension, MIME type or magic bytes individually; combine checks according to supported file types and risk.
- Keep objects private and unavailable until integrity/required policy checks complete. Use a quarantine state for suspicious or not-yet-scanned objects where the platform's use case requires scanning.
- If antivirus is introduced, run it asynchronously in a resource-limited isolated worker, not in the upload request. Do not send private documents to public scanning services without explicit data-governance approval.
- Do not automatically extract archives. If archive extraction is required, prevent path traversal and symlink escapes, cap entry count, nested depth, total expanded bytes and compression ratio, and run in a sandbox. ZIP bombs can exhaust disk, memory and CPU.
- Treat PDF parsers, document converters, OCR and media processors as untrusted-input attack surfaces; use patched dependencies, timeouts and memory/CPU limits.

### Quotas and exhaustion protection
- Enforce per-file, per-batch, per-tenant and global storage limits server-side.
- Limit concurrent files/parts, intent creation rate, multipart sessions, incomplete-upload lifetime, archive expansion and processing jobs.
- Monitor disk free space and reserve a safety margin. Stop or reject new work before the host reaches disk-full conditions; alert operators.
- Add fair scheduling so one tenant cannot monopolize all workers or bandwidth.
- Rate-limit metadata/control-plane requests independently from byte transfers.

## Compression and deduplication decisions

### Compression policy
- Preserve original bytes as the default storage behavior.
- Optionally compress only eligible content types or when a bounded sampling pass shows a meaningful saving that exceeds a configurable threshold.
- Prefer zstd for application-controlled compressible payloads where interoperability is managed. Store the original media type, compression codec/version and original/stored sizes in metadata.
- Stream compression/decompression with CPU, memory and time limits. Do not load an entire file into RAM.
- Never recompress content that is already compressed by default. If compression is applied, downloads must return the original representation unless the client explicitly requests the encoded representation and understands its metadata.
- Benchmark the complete trade-off: bytes saved, CPU time, end-to-end latency, client compatibility and cost. A smaller file is not automatically a faster transfer if compression saturates a CPU.

### Deduplication
- Do not implement cross-tenant global deduplication in the first release. It can create privacy side channels, complicate deletion/retention and make ownership semantics difficult.
- If storage-saving deduplication is later justified, start with tenant-scoped deduplication and a threat model. Keep reference counts, immutable object identity, deletion safety and audit semantics explicit.
- A SHA-256 fingerprint may identify accidental duplicates within an authorized scope, but must not reveal whether another tenant owns the same content.

## Metadata and lifecycle model

Each item should track at minimum:
- opaque object ID, tenant ID, application ID, batch/job ID;
- server-generated bucket/key;
- display filename, declared and detected content type;
- expected size and verified stored size;
- expected checksum and independently verified checksum, with algorithm and semantics;
- compression codec/version if transformed;
- encryption state/metadata version without exposing keys;
- status: pending, uploading, verifying, quarantined, available, failed, expired, deleting, deleted;
- created/updated/completed timestamps, expiry, attempt count and sanitized failure category;
- request/correlation ID and audit actor.

File bytes stay in SeaweedFS/S3; metadata and intent/job state stay in PostgreSQL when that planned catalogue is implemented.

## Performance measurement plan

Do not claim an algorithm is fastest without tests on AURA's real bottlenecks. Benchmark on a non-production test dataset and a controlled endpoint before production rollout.

### Test matrix
- File sizes: 100 KiB, 1 MiB, 10 MiB, 64 MiB, 100 MiB, 512 MiB and 1 GiB, subject to safe test capacity.
- File types: text/JSON/CSV, PDF, JPEG/PNG, MP4, ZIP and opaque binary.
- Network profiles: stable LAN, normal client connection, high latency, constrained bandwidth, packet loss/interrupted connection.
- Modes: single PUT; multipart at multiple part sizes; concurrency levels 1, 2, 4, 8 within safe limits; retries/resume; compression off versus zstd on only for eligible content.
- Failure cases: interruption mid-file, expired URL, one part failure, duplicate commit, checksum mismatch, database unavailable, storage unavailable, low disk capacity and abandoned multipart session.
- Security cases: wrong tenant/application, reused intent, wrong object key, expired URL, oversized manifest/file, suspicious archive and path-traversal filename.

### Metrics
- successful bytes/second and files/second;
- end-to-end p50/p95/p99 duration by size band;
- retries, resume success rate, failed bytes retransmitted and time to recover;
- API CPU/RAM (must remain bounded as file size grows), storage CPU/disk throughput, disk free space and network throughput;
- compression ratio and CPU time, where tested;
- checksum failures, quarantines, unauthorized attempts and rate-limit responses;
- orphaned objects, pending-intent age and incomplete multipart count.

Record test environment, pinned SeaweedFS/container versions, client SDK versions and repeat count. Use a representative dataset without personal or production files. Do not publish exact throughput targets until the VPS/network baseline is measured.

## Implementation sequence

1. **P0 — security baseline:** application identity, tenant isolation, object-private default, quota enforcement, signed URL redaction, encryption verification and no production data before independent restore.
2. **P0 — reliable transfer state machine:** upload intents, server-generated keys, pending/verify/available states, idempotent commit, checksum and size verification, orphan reconciliation.
3. **P0 — batch jobs:** manifest validation, per-file outcomes, idempotency, bounded queue, cancellation and retry of failed items.
4. **P1 — multipart:** add only after a compatibility test against the exact pinned SeaweedFS release; presign part operations and safely abort expired sessions.
5. **P1 — resilience and tuning:** adaptive concurrency, retry/backoff, resume, load/failure tests and capacity alerts.
6. **P1 — content safety:** quarantine and isolated malware/content scanning based on supported file types and privacy requirements.
7. **P2 — optional transformations:** zstd for eligible formats, client-side envelope encryption for selected data classes, tenant-scoped deduplication only after measured need and threat review.

## Definition of done

- Bulk manifests cannot cross tenant/application boundaries or bypass quotas.
- File bytes do not pass through FastAPI for normal direct-to-S3 transfers.
- Large uploads can resume at part granularity and failed files can retry independently.
- Every completed object is checked for expected size and supported integrity checks before availability.
- Presigned URLs and credentials never appear in logs.
- Malformed/malicious files, archives, retries and exhausted disk conditions fail safely.
- Multipart and checksum compatibility is demonstrated against the pinned SeaweedFS release, not assumed from AWS documentation.
- Benchmark results show measured performance and resource use; no unverified speed claims.
- Independent backup/restore, TLS and SSE-S3 verification remain required gates before importing important or customer files.

## References

- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [AWS S3 multipart uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)
- [AWS S3 upload integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html)
- [SeaweedFS S3 API compatibility](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)
- [tus resumable upload protocol](https://tus.io/protocols/resumable-upload)
- [Zstandard format](https://github.com/facebook/zstd/blob/dev/doc/zstd_compression_format.md)
