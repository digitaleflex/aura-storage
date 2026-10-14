# AURA Storage Architecture

## Purpose

AURA is an independently operated storage service. Its initial deployment is a single VPS running Docker Compose. It must serve authorized object requests without requiring Axiom or Azure to be available.

## Components

1. **Traefik Proxy** — HTTPS routing, automatic TLS certificate management, access logs and metrics. Protect its dashboard; it is not the file-management UI.
2. **SeaweedFS Filer + S3 API** — object operations for authorized clients and direct transfer of file bytes.
3. **Persistent host volumes** — files and required metadata must survive container recreation.
4. **AURA Management API** — implemented service for object inventory, virtual folders, search, metadata, access policy, upload/download intents and audit events. It is not yet validated on the pilot VPS.
5. **PostgreSQL catalogue** — implemented catalogue for object metadata, tenant/application ownership, transfer intent state and audit records; never the file bytes. It is not yet validated on the pilot VPS.
6. **Independent backup destination** — separate failure domain, with a tested restore.
7. **Future integrations** — OpenBooks for catalogue/entitlements and Axiom for limited monitoring/control via a versioned API.

## Responsibility boundaries

- Consuming platforms authenticate their own users and enforce their own product entitlements and business rules. AURA does not implement consumer-platform billing/subscriptions.
- A consuming platform authenticates to AURA using a dedicated service identity when requesting object operations.
- AURA authorizes the application/tenant/resource and issues a short-lived presigned S3 URL for a specific object and method.
- The client transfers binary bytes directly to/from the HTTPS S3 endpoint. The API handles authorization, metadata, lifecycle and audit, not the default large-file data path.
- Each consuming application and environment uses a dedicated, least-privilege S3 identity or equivalent server-side signing boundary. The bootstrap/admin identity is not for routine application traffic.
- The management API must not expose raw filesystem paths, unrestricted storage credentials or arbitrary bucket/key access.
- FTPS is not part of the default architecture. It may be introduced as an isolated, controlled legacy-import adapter only after a concrete need is documented; it must feed the same authorization, verification and catalogue lifecycle.
- Axiom may later monitor health/capacity and request scoped operations, but routine object access must not depend on Axiom.
- Traefik's dashboard is operational visibility, not an object browser.

## Initial topology

One VPS, Docker Engine, Docker Compose, Traefik and SeaweedFS. Public ingress is HTTPS through Traefik. SeaweedFS internal/admin ports stay on a private Docker network and are not published publicly. The S3 hostname is exposed only as needed for clients to use HTTPS presigned URLs. The management API is a separate component; it is not publicly routed and is reachable only through the app proxy, with authentication, authorization, audit logs and a defined data model.

A single VPS is not high availability. Independent backup and a tested restore are mandatory before importing important production data.

## Transfer flow

1. A consuming platform authorizes its user under its own rules and authenticates its service identity to AURA.
2. The platform requests an upload intent. AURA checks tenant/application scope, policy, size limits and quota, generates an object key and records a pending intent.
3. AURA returns a short-lived presigned upload URL scoped to that key and method.
4. The client sends bytes directly to SeaweedFS/S3 over HTTPS.
5. The client asks AURA to commit the intent. AURA verifies the stored object, actual size and checksum/required storage properties before marking the catalogue object available.
6. For downloads, AURA authorizes the object request and issues a short-lived GET URL scoped to one object.
7. A reconciliation process handles expired intents and orphaned objects conservatively, with a grace period.

See [File Transfer Contract](FILE-TRANSFER.md) for security controls, large-file handling, failure modes and acceptance criteria.

## Object catalogue

SeaweedFS/S3 stores bytes. AURA's management/catalogue layer should maintain stable object IDs, bucket/key, display name, content type, size, checksum, timestamps, logical folder, tenant/application ownership, visibility and lifecycle state. The catalogue must not expose internal storage locations to ordinary callers. Avoid embedding host filesystem paths in application records.

Upload intent creation, S3 transfer and PostgreSQL commit are not one atomic transaction. Use explicit lifecycle states, idempotent completion and reconciliation rather than assuming a distributed transaction.

## Media and large-file behavior

Test multipart upload/download, large objects, interrupted transfers, Range requests for audio/video, cache headers, checksum behavior and signed URL expiry with the exact pinned SeaweedFS release and client libraries. The API must not load an entire object into memory for checksum calculation. Define and test a single-request size threshold before implementing multipart upload.

## Acceptance gates

- Presigned URLs cannot access objects outside their intended method/key scope.
- Cross-tenant and cross-application requests are denied.
- No object is marked available before server-side verification.
- Signed URLs and credentials are redacted from logs.
- Upload interruption, duplicate commit, expiry, checksum mismatch and storage/database outage have tested behavior.
- HTTPS, encryption verification, persistence and an independent backup restore are proven before importing important or customer data.
