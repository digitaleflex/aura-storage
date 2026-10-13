# AURA Storage Architecture

AURA is the storage data plane, not an application catalogue, subscription service, or central orchestrator.

## Components

1. S3 endpoint for authorised object operations.
2. SeaweedFS storage engine and metadata services.
3. Persistent host-mounted data directory.
4. HTTPS edge configured for the real storage domain.
5. Independent backup target in a separate failure domain.
6. Future limited health/capacity/backup-status integration with Axiom.

## Responsibility boundaries

- OpenBooks authorises the user/subscription before issuing a short-lived signed URL or proxying a protected download.
- Each application gets a separate least-privilege S3 identity.
- Axiom can later observe health and capacity, but routine file access must not depend on Axiom being online.
- Do not give a general-purpose agent unrestricted access to every object's read/delete operations by default.

## Initial topology

Start with one VPS and Docker Compose. The Compose baseline binds S3 to loopback; SeaweedFS internal ports are not published to the host. Public requests must pass through an explicitly configured HTTPS proxy. This is not high availability: VPS, disk, provider, or configuration failure can make data unavailable. Independent backups and tested restore are required before production.

Applications should store logical object identifiers and metadata, not host filesystem paths. Test multipart operations, large files, interrupted transfers, audio/video Range requests, cache headers and signed-URL expiration with the selected engine and clients.