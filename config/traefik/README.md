# Traefik configuration notes

The Compose file defines Traefik via static CLI arguments and discovers the SeaweedFS S3 service using Docker labels.

## Important behavior

- Only ports 80 and 443 are published on the host.
- Docker provider uses `exposedByDefault=false`; a service must explicitly opt in with labels.
- ACME uses the HTTP-01 challenge. The DNS A/AAAA record for `S3_DOMAIN` must resolve to this VPS, port 80 must be reachable, and no conflicting proxy should intercept the challenge unexpectedly.
- The dashboard API is enabled internally but no public router is defined. Do not add a public dashboard route without authentication and network restrictions.
- The `aura-s3-landing` router answers only an unsigned `GET /` on `S3_DOMAIN` with a static page; signed requests and every other path stay on the `aura-s3` router (`docs/S3-ROOT-LANDING.md`).
- The Docker socket is mounted read-only. Read-only does not remove the security sensitivity of Docker API access; keep the host and Docker access tightly controlled.
- ACME state is stored in the named volume `traefik-acme`. Back up its state securely and do not publish it.
- The Compose labels and network names must be reviewed with the exact Traefik version before production.

## Before public exposure

1. Replace sample domain/email values in the local `.env`.
2. Configure DNS and verify it from outside the server.
3. Open only TCP 80 and 443 plus restricted SSH in the host firewall.
4. Confirm the S3 identity configuration is non-placeholder and tested.
5. Confirm SeaweedFS internal ports have no host bindings.
6. Review access logs for credential-bearing query strings; configure redaction/retention as needed.
