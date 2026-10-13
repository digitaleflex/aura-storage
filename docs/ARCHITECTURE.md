# AURA Storage Architecture

## Purpose

AURA is an independently operated storage service. Its initial deployment is a single VPS running Docker Compose. It must serve authorised object requests without requiring Axiom or Azure to be available.

## Components

1. **Traefik Proxy** — HTTPS routing, automatic TLS certificate management, access logs and metrics. Protect its dashboard; it is not the file-management UI.
2. **SeaweedFS Filer + S3 API** — object operations for authorised clients.
3. **Persistent host volumes** — files and required metadata must survive container recreation.
4. **AURA Management API** — planned service for object inventory, virtual folders, search, metadata, access policy and audit events.
5. **Independent backup destination** — separate failure domain, with a tested restore.
6. **Future integrations** — OpenBooks for catalogue/entitlements and Axiom for limited monitoring/control via a versioned API.

## Responsibility boundaries

- Applications authenticate/authorise the user before issuing a short-lived signed URL or proxying a protected download.
- Each consuming application uses a dedicated, least-privilege S3 identity.
- The management API handles cataloguing and administrative workflows; it must not expose raw filesystem paths or unrestricted storage credentials.
- Axiom may later monitor health/capacity and request scoped operations, but routine object access must not depend on Axiom.
- Traefik's dashboard is operational visibility, not an object browser.

## Initial topology

One VPS, Docker Engine, Docker Compose, Traefik and SeaweedFS. Public ingress is HTTPS through Traefik. SeaweedFS internal/admin ports stay on a private Docker network and are not published publicly. The management API is a separate component and should be added only with authentication, authorisation, audit logs and a defined data model.

A single VPS is not high availability. Independent backup and a tested restore are mandatory before importing important production data.

## Object catalogue

SeaweedFS/S3 stores bytes. AURA's management/catalogue layer should maintain stable object IDs, bucket/key, display name, content type, size, checksum, timestamps, logical folder, ownership, visibility and lifecycle state. The actual fields and database will be defined in a dedicated API/data specification. Avoid embedding host filesystem paths in application records.

## Media behavior

Test multipart upload/download, large objects, interrupted transfers, Range requests for audio/video, cache headers and signed URL expiry with the exact engine release and client libraries.
