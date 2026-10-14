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
