# Environment Configuration

## Principle

Environment-specific values belong in the local `.env`. Keep service topology and security rules versioned in `docker-compose.yml`; do not make security-sensitive ports or network isolation casually configurable.

## Values controlled by `.env`

- `AURA_INSTANCE_ID`: local container name prefix, e.g. `aura-001`.
- `TZ`: container timezone.
- `TRAEFIK_IMAGE`, `SEAWEEDFS_IMAGE`: reviewed image references.
- `S3_DOMAIN`: public hostname routed to the S3 gateway.
- `ACME_EMAIL`: certificate notifications.
- `AURA_DATA_DIR`: persistent data root. Prefer an absolute path on the intended filesystem.
- `SEAWEED_VOLUME_SIZE_LIMIT_MB`, `SEAWEED_VOLUME_MAX`: SeaweedFS capacity controls.
- `S3_ACCESS_KEY`, `S3_SECRET_KEY`: initial S3 credentials injected into generated local config.

## First setup

```bash
cp .env.example .env
chmod 600 .env
# Edit .env locally; use strong random S3 credentials and real domain/email.
bash ./scripts/generate-config.sh
chmod 600 config/seaweedfs/s3.json
docker compose config --quiet
```

The generator creates `config/seaweedfs/s3.json` from the tracked example and local environment values. The generated file is ignored by Git. It does not change or erase storage data.

The generator currently injects the configured credentials into the placeholder credential fields in the example identity. Review the example's permissions and confirm policy/action syntax for the exact SeaweedFS release. Do not use a broad Admin identity for routine application access; create least-privilege identities as the service evolves.

## Management API configuration

The API container reads its own settings from Compose/environment (see `docker-compose.yml` and `api/config.py`). Secrets (`AURA_API_ADMIN_PASSWORD`, `S3_ACCESS_KEY`/`S3_SECRET_KEY`, `POSTGRES_PASSWORD`, the SSE-S3 key) live only in the local `.env`.

- `AURA_API_ADMIN_USER` / `AURA_API_ADMIN_PASSWORD`: bootstrap administrator, created on first boot with an argon2-hashed password.
- `AURA_API_BACKEND` / `AURA_API_DSN`: catalogue backend; the Compose stack uses PostgreSQL.
- `AURA_SESSION_TTL`: human session cookie lifetime in seconds. Default `2592000` (30 days); the expiry is fixed at login and the cookie is HttpOnly, `Secure` and `SameSite=Strict`. Shorten it for higher-value deployments.
- `AURA_AUDIT_LOG`: absolute path of the JSON-lines audit trail. The Compose stack pins `/var/log/aura/audit.jsonl` on a dedicated bind mount (`${AURA_DATA_DIR}/audit`), so events survive container recreations; `api/config.py` defaults to the same path. The `/admin/health` disk probe measures the containing directory, not the file, so a not-yet-written log never reports the disk as unreadable.
- Optional guard rails (sensible defaults in `api/config.py`; uncomment in `.env` to override): `AURA_SESSION_TTL`, `AURA_INTENT_TTL`, `AURA_INTENT_GRACE_SECONDS`, `AURA_MAX_OBJECT_BYTES`, `AURA_COMMIT_CHUNK_BYTES`, `AURA_MAX_PENDING_INTENTS`, `AURA_M2M_RATE_LIMIT`, `AURA_M2M_RATE_WINDOW`, `AURA_LOGIN_RATE_LIMIT`, `AURA_LOGIN_RATE_WINDOW`.
- `AURA_TRUSTED_PROXIES`: comma-separated IPs/CIDRs whose `X-Forwarded-For` is trusted when resolving the client IP for the rate limiters. Defaults to loopback + RFC1918 (the internal Docker network). The API is only reachable through Traefik and nginx; a client-supplied `X-Forwarded-For` is ignored unless the immediate peer is trusted. The API container runs uvicorn with `--no-proxy-headers` so this in-app resolution owns the client IP; do not enable `--forwarded-allow-ips=*`.

These are technical safety limits, not billing or subscription policy. API authorization, provisioning, rotation and revocation are documented in `docs/AUTHORIZATION-MATRIX.md`.

## Domain migration

To move from an initial endpoint to a dedicated domain:

1. Create DNS records for the new S3 hostname pointing to the VPS.
2. Set `S3_DOMAIN` in `.env` to the new hostname.
3. Confirm ports 80/443 are reachable and the old endpoint can remain available during migration if desired.
4. Run `docker compose config --quiet` and inspect the rendered configuration locally.
5. Deploy with the reviewed procedure and verify the new HTTPS certificate and authenticated S3 upload/download.
6. Update client endpoint configuration separately where clients currently hard-code the old endpoint.
7. Retire the old DNS name only after client migration and validation.

Changing `S3_DOMAIN` does not automatically update DNS, clients, external firewall rules, or application configuration outside this repository.

## Change classes

Usually environment-only: hostname, ACME email, image reference, data root, instance name, supported capacity settings and credentials.

May require code/config changes: service topology, adding a database/API, changing network boundaries, changing exposed ports, changing SeaweedFS command semantics, adding new application behavior, or altering policy schema.

## Safety

- Never commit `.env` or generated `config/seaweedfs/s3.json`.
- Do not print secrets or the fully rendered Compose configuration into public issues/logs.
- Back up persistent data before upgrades or changing storage paths.
- Changing `AURA_DATA_DIR` points services at a different directory; it does not move existing files. Copy/verify data separately before changing it.
- Rotating S3 credentials requires updating the generated config and any clients using those credentials.


## SSE-S3 at-rest encryption

The pilot config pins SeaweedFS 4.48 because the older 3.80 sample predates the documented SSE-S3 configuration path. Before deploying, review the official SeaweedFS release notes and verify the exact image supports WEED_S3_SSE_KEK. A configured variable is not proof that objects are encrypted.

Generate a key locally using openssl rand -hex 32, store it in WEED_S3_SSE_KEK in .env, and keep a separate protected offline copy. Loss of this key can make SSE-S3 objects unrecoverable. Do not rotate it on an existing data set without a tested migration and restore plan.

After deployment, run bash tests/sse-s3-smoke-test.sh with AWS CLI v2 installed. The test creates a temporary bucket, uploads an AES256 object, checks the returned encryption field, downloads it, verifies SHA-256, then attempts cleanup. Do not import important files unless this test passes.
