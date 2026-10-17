# Security Baseline

## Network and host
- Use SSH keys and confirm key access before disabling password login.
- Restrict SSH source addresses when practical.
- Apply OS security updates and configure unattended security updates.
- Use default-deny inbound firewall rules and allow only required ports.
- Keep SeaweedFS master, volume, filer UI/admin, metrics and other internal interfaces private.
- Expose S3 only through HTTPS.
- Never publish the Traefik dashboard without explicit authentication and network restrictions.
- Restrict Docker socket access; Docker group membership is effectively root-equivalent.

## S3 access and object encryption
- Generate unique credentials outside Git and store local config with restrictive permissions.
- Use different least-privilege identities per app/environment; the bootstrap identity is administrative and must not be used for routine app traffic.
- Keep objects private by default. Do not grant anonymous access unless a specific public-content design has been reviewed.
- The Compose baseline passes WEED_S3_SSE_KEK to the SeaweedFS Filer/S3 gateway. Generate a 256-bit hex key with: openssl rand -hex 32.
- Protect an offline copy of the SSE key separately from the VPS and repository. Never commit it, print it to logs, or store it beside the only copy of encrypted data.
- Losing the SSE key may make SSE-S3 objects unrecoverable. Rotating the key is a data-migration procedure, not a simple environment edit.
- Run tests/sse-s3-smoke-test.sh after deployment. It uploads an object with AES256, checks the S3 response and verifies downloaded bytes. Do not import valuable data unless the test passes.
- This test validates S3 object encryption reporting; it does not prove whole-disk encryption or protect against a compromised running server.
- Confirm the selected SeaweedFS image release supports WEED_S3_SSE_KEK. If it does not, do not assume encryption is active; select a supported release and re-run the acceptance test.
- Validate S3 policy syntax/actions against the exact selected SeaweedFS release.

## Secrets, releases and recovery
- Pin reviewed container image versions; inspect release notes before upgrades.
- Never commit .env, keys, certificates, production config, customer data or backups.
- Document credential revocation, secret rotation, disk-full response, backup restore and rollback.
- The VPS is not a backup. Keep originals locally until an independent backup has been restored successfully.

## API authorization and multi-platform isolation (#35, #36)
- Every sensitive API route declares the capability it needs server-side; a route that
  is not classified stays closed. The full route × capability matrix is in
  `docs/AUTHORIZATION-MATRIX.md`.
- A valid session or CSRF token is authentication, not authorization: administrative
  and destructive actions (purge, reconcile, provisioning) require the matching role
  or scope and are refused with 403 otherwise.
- Human sessions are relatively short-lived by default (`AURA_SESSION_TTL` = 8 hours)
  in the Docker Compose stack (and `api/config.py` defaults to 8 hours). The narrower
  theft window reduces exposure; the team can override the value explicitly in
  `.env` when a longer session is an operational requirement. The cookie is
  `HttpOnly`, `Secure`, `SameSite=Strict` and set with `max_age` corresponding to
  the effective TTL (no sliding refresh). A new login always issues a new session
  identifier and a new CSRF token.
- Objects carry an application/space/environment boundary. Catalogue queries are
  always filtered by the caller's space, and human users are further limited to their
  own objects.
- Client-supplied tenant, owner, bucket or object-key values never grant access:
  object keys are generated server-side and buckets must be registered to the caller's
  space.
- Presigned URLs are short-lived and scoped to a single object and operation; they are
  never logged and never embedded in the frontend bundle.

## Machine-to-machine identities (#38)
- Platforms call AURA with a service identity (`Authorization: Bearer aura_<id>_<secret>`),
  not with a human session and not with the bootstrap SeaweedFS S3 key.
- AURA stores only the SHA-256 fingerprint of the secret; the token is shown once at
  creation or rotation. Unknown, revoked and expired tokens all return 401.
- Grant the minimum scopes per identity and one identity per application/environment.
  Machine identities are data-plane only: they may hold object capabilities
  (`objects:*`), never `admin:*`, which stays with human operator/admin sessions.
- Provision, rotate and revoke through the admin API (see
  `docs/AUTHORIZATION-MATRIX.md`). Revocation is immediate and isolated to one identity.
- Failed machine authentication is rate-limited per client IP; secrets never appear in
  logs, errors, subsequent responses or the frontend bundle. The client IP comes from
  `X-Forwarded-For` only behind a trusted proxy, and the right-most untrusted entry is
  used, so a spoofed header cannot bypass the limiter (`api/netinfo.py`).

## Transfer integrity and resource limits (#37, #40)
- Commit streams the object to compute SHA-256 without loading it fully into memory,
  enforces a maximum size, and verifies the streamed size against storage metadata.
  Truncated, oversized or mismatched uploads are never marked available.
- Upload intents expire; commits after the intent TTL (plus a grace period) are
  refused. Repeated commits are idempotent.
- Technical guard rails (max object size, pending-intent cap, rate limits) protect the
  service from abuse. These are safety limits, not billing or subscription policy.
- An upload intent declares the object's `size_bytes`; that value is bound into the
  presigned URL as a **signed `Content-Length`**, so an uploader cannot push more than
  the API authorised and fill the volume before commit. Declared sizes above the
  configured maximum are refused up front (422), and the commit-time size check remains
  as defence in depth (#40). Enforcement of the signed header is validated on the pilot.
- The presigned PUT also signs the SSE-S3 request header
  **`x-amz-server-side-encryption: AES256`** (`api/s3.py`), so the client must send it
  for the gateway to encrypt the object at rest; the commit step can then require
  AES256 at the object level. Like `Content-Length`, the signed-header enforcement is
  validated on the pilot, not in the offline suite.
- Default bucket names (derived from the space name/environment, or supplied) are
  validated against the S3 naming rules before the bucket is registered, so a space can
  never point at a bucket name S3 would reject (`api/s3.py:is_valid_bucket_name`, #41).
