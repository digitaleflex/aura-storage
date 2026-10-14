# File Transfer Contract — AURA Storage

**Status:** architecture and implementation contract. This document does not claim that the API or transfer workflow is implemented or production-validated.

## Decision

Use the **AURA Management API for identity, authorization, metadata and audit**, and **short-lived S3-compatible presigned URLs for normal binary uploads and downloads**. SeaweedFS is the object data plane. The API must not relay every large file through its own process by default.

FTPS is **not** the primary client transfer protocol. It may be added later as a narrowly scoped legacy-integration or migration adapter if a concrete partner requires it. Do not deploy an FTPS server or expose additional ports merely as a precaution.

## Responsibilities

- **Consuming platform:** authenticates its own end user, enforces its product entitlements and decides whether that user may request a file operation. AURA does not implement the platform's billing or subscription rules.
- **AURA API:** authenticates the calling application/service; checks registered permissions and tenant/application scope; validates requested metadata and quotas; creates an upload intent; generates the presigned URL; validates completion; writes catalogue and audit state; issues authorized download intents.
- **SeaweedFS S3 gateway:** receives/sends object bytes. It must remain private except for the explicitly configured HTTPS S3 endpoint required by clients using presigned URLs. Administrative interfaces stay private.
- **PostgreSQL catalogue (planned):** stores object IDs, tenant/application ownership, object key, expected and verified size/checksum, lifecycle status, timestamps and audit references. It does not store file bytes.
- **FTPS adapter (optional future scope):** if approved, runs as a separate controlled integration path with dedicated credentials, allow-listed directories, restricted network access, audit, import staging and the same catalogue validation process. It must not bypass AURA authorization or publish arbitrary filesystem paths.

## Upload sequence

1. The platform server authenticates to AURA using a dedicated machine identity. Do not embed long-lived credentials in browser JavaScript or a mobile application.
2. The platform asks for an upload intent and supplies required metadata: intended display name, declared content type, expected byte size, optional expected SHA-256, and logical folder/target scope.
3. AURA derives the storage key itself; it does not trust a client-supplied bucket/key. It checks application identity, tenant isolation, allowed operation, file-size limit, content-type policy, quota/rate limits and target folder permissions.
4. AURA records a pending intent with an opaque ID, a unique generated object key, expected constraints, expiration, actor/application scope and request ID.
5. AURA returns a short-lived presigned upload URL for a specific method, the required request headers, expiration and opaque intent ID. Large files above a tested threshold use a separately specified multipart-upload workflow. Never return S3 access keys or unrestricted credentials.
6. The platform transfers bytes directly to the configured HTTPS S3 endpoint. The client must use the exact signed method, URL and required headers. It must not log the full URL because the query string is a temporary bearer capability.
7. The platform calls the completion/commit endpoint with the intent ID. AURA verifies the object exists at the server-generated key and checks actual size, expected checksum where supplied, required storage properties where supported, and that the intent is still valid. Do not trust client-reported completion alone.
8. Only after successful verification does AURA mark the catalogue object available. Until then it remains pending and must not be downloadable through the normal application flow.
9. A background reconciliation process expires abandoned intents and detects orphaned or mismatched objects. Cleanup must use a grace period and must never delete an object merely because a transient catalogue or S3 check failed.

## Download sequence

1. The consuming platform first authorizes its own user and then requests a download intent for an opaque AURA object ID.
2. AURA authenticates the service identity and checks application/tenant ownership, object status, visibility and resource-level permission on every request.
3. AURA returns a short-lived presigned GET URL for exactly that object. The URL must not grant listing, writes, deletes or access to other keys.
4. The client downloads directly from the HTTPS S3 endpoint. The consuming platform must not persist or expose the URL longer than needed.
5. For audio/video or resumable downloads, validate HTTP Range behavior, content length/type, cache policy and expiry against the pinned SeaweedFS release and actual client libraries.

## Security requirements

- Private by default; no anonymous bucket/object access.
- Use a distinct least-privilege S3 identity per consuming application and environment. Do not use the SeaweedFS bootstrap/admin identity for routine traffic.
- The signing service must not accept arbitrary bucket/key values from clients. Keys are generated server-side and bound to the authenticated tenant/application and intent.
- Keep signed URL lifetime short and configurable. Choose a default appropriate for observed transfer conditions; document and test the chosen value. An expired URL requires a new authorization decision and a new URL.
- Signed URLs are bearer capabilities until expiry. Redact query strings and authorization headers from API, proxy, application and error logs; never include them in audit payloads, issue reports or analytics.
- Require HTTPS for public transfer endpoints. Keep SeaweedFS admin, filer UI, master, volume and metrics endpoints private.
- Enforce per-application and per-tenant size, concurrency, request-rate and storage quotas server-side. Do not rely on a UI check.
- Verify actual stored size and checksum at commit. Do not treat an ETag as SHA-256 unless the selected storage/client semantics explicitly guarantee it.
- Use explicit intent states such as pending, verifying, available, expired, failed, quarantined and deleting. Transitions must be validated and idempotent.
- Apply CSRF protection to cookie-authenticated browser mutations; use a separate, documented machine-to-machine authentication method for server-side platform clients.
- Audit authorization outcomes and lifecycle changes without logging file contents, secrets or signed URLs.
- Do not accept arbitrary callback URLs, storage endpoints, object keys or local filesystem paths from callers.

## Large files, retries and failure handling

- Do not load entire objects into API memory to calculate a checksum. Use streaming verification, storage-supported checksum mechanisms or a bounded multipart workflow.
- Define and test a maximum single-request upload size. For files above it, design multipart upload with server-controlled initiation, scoped part URLs, completion verification, abort handling and cleanup of abandoned multipart uploads.
- Use bounded timeouts and retries with exponential backoff and jitter where appropriate. Retrying an intent/commit must not create duplicate logical objects.
- If upload succeeds but commit fails, leave the object pending and let a retry or reconciliation process resolve it safely.
- If a commit references a missing object or verification fails, do not mark it available; record a sanitized failure and apply controlled cleanup/quarantine.
- Test interrupted uploads, duplicate commit requests, expired intents, wrong tenant, wrong key, mismatched size/checksum, storage unavailable, database unavailable and disk-full conditions.

## FTPS: allowed use and boundaries

FTPS is an optional integration/migration protocol, not a parallel default for every platform. Add it only when a documented external requirement cannot reasonably use the API plus S3 presigned URLs.

If introduced, require explicit scope approval and document:
- network exposure and passive-port range;
- TLS certificate lifecycle and secure protocol configuration;
- unique per-partner credentials, least-privilege directory isolation and rotation/revocation;
- IP allow-listing or private connectivity where feasible;
- upload staging, filename/path sanitization, size limits, malware/content scanning where required, and checksum verification;
- import job IDs, retry/idempotency behavior, audit trail and cleanup;
- how staged files enter the same AURA catalogue lifecycle without bypassing tenant authorization;
- operational monitoring and tests.

Do not expose plain FTP. Do not map partner-controlled paths directly to host paths. Do not allow FTPS users to browse or overwrite other applications' objects.

## Observability and data minimization

Record request ID, intent ID, application identity, tenant scope, action, outcome, timestamps, verified byte count and a safe error category. Never record passwords, access keys, authorization headers, signed URLs or private file contents. Metrics should include transfer successes/failures, duration, bytes, expired intents, verification failures, abandoned uploads and storage capacity, without high-cardinality or sensitive labels.

## Acceptance criteria

- Upload and download data flows directly between the authorized client and the S3 endpoint; the API handles control-plane operations.
- Every intent is authenticated, tenant/application scoped, object/method scoped, short-lived and auditable.
- Object keys and buckets are server-controlled.
- A file is unavailable until server-side completion verification passes.
- Size/checksum mismatches, cross-tenant attempts and expired URLs fail safely.
- Repeated completion calls are idempotent; abandoned uploads are reconciled after a grace period.
- Large-file and interrupted-transfer tests demonstrate bounded API memory use.
- Signed URLs and credentials are absent from logs, responses unrelated to the transfer and audit records.
- Tests run against the exact pinned SeaweedFS/S3-compatible release before production acceptance.
- HTTPS, encryption verification, persistence and an independent backup restore are proven before importing important or customer data.

## Bulk transfer, security and performance

For batch manifests, bounded concurrency, resumability, multipart thresholds, compression policy, malware/quarantine controls, encryption choices, quotas and a reproducible benchmark plan, see [Secure and Efficient Bulk File Transfers](SECURE-BULK-TRANSFERS.md). The detailed plan distinguishes protocol capabilities from features that still require implementation and compatibility testing against the exact pinned SeaweedFS release.

## Non-goals

This design does not add user billing/subscriptions, public anonymous sharing, a general-purpose FTP hosting service, multi-region high availability or a claim of production readiness. A single VPS remains a single point of failure.

## Related documents

- [Architecture](ARCHITECTURE.md)
- [Management API specification](API-SPECIFICATION.md)
- [Catalogue data model](DATA-MODEL.md)
- [Security baseline](SECURITY.md)
- [Backup and restore](BACKUP-RESTORE.md)
