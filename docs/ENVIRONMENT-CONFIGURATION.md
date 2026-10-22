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
- `AURA_SESSION_TTL`: human session cookie lifetime in seconds. Default `7776000` (90 days); the expiry is fixed at login and the cookie is HttpOnly, `Secure` and `SameSite=Strict`. Shorten it for higher-value deployments.
- Optional guard rails (sensible defaults in `api/config.py`; uncomment in `.env` to override): `AURA_SESSION_TTL`, `AURA_INTENT_TTL`, `AURA_INTENT_GRACE_SECONDS`, `AURA_MAX_OBJECT_BYTES`, `AURA_COMMIT_CHUNK_BYTES`, `AURA_MAX_PENDING_INTENTS`, `AURA_M2M_RATE_LIMIT`, `AURA_M2M_RATE_WINDOW`, `AURA_LOGIN_RATE_LIMIT`, `AURA_LOGIN_RATE_WINDOW`, and the multipart settings `AURA_MULTIPART_ENABLED` (default `0`), `AURA_MULTIPART_THRESHOLD_BYTES`, `AURA_MULTIPART_PART_BYTES`, `AURA_MULTIPART_MAX_OBJECT_BYTES`, `AURA_MULTIPART_SESSION_TTL` (see `docs/MULTIPART-UPLOAD-PLAN.md`), and the integrity worker settings `AURA_VERIFY_ASYNC_THRESHOLD_BYTES` (default 32 MiB), `AURA_VERIFY_PAUSE_WHILE_UPLOADING` (default `1`: the verifier waits while uploads run) / `AURA_VERIFY_PAUSE_WINDOW_S` (default 300), `AURA_VERIFY_WORKER` (`inline` or `off`), `AURA_VERIFY_LEASE_SECONDS`, `AURA_VERIFY_HEARTBEAT_BYTES`, `AURA_VERIFY_MAX_ATTEMPTS`, `AURA_VERIFY_POLL_SECONDS` (see `api/verifier.py`), `AURA_AV_SCAN_CMD` / `AURA_AV_SCAN_TIMEOUT_S` (default 120; the scan runs on the synchronous commit and in the verification worker, see `api/avscan.py`), and the capacity guard `AURA_STORAGE_CAPACITY_BYTES` (default `0` = off) / `AURA_STORAGE_HIGH_WATERMARK` (default 90 %): uploads reserve their declared size and are refused with 507 beyond the watermark, the periodic integrity scrub `AURA_SCRUB_ENABLED` (default `1`), `AURA_SCRUB_INTERVAL_DAYS` (default 30), `AURA_SCRUB_BYTES_PER_RUN` (default 10 GiB), `AURA_SCRUB_PERIOD_SECONDS` (default 3600) (see `api/scrubber.py`), and `AURA_ORPHAN_GRACE_SECONDS` (default 86400; storage orphans younger than this are ignored, see `api/storage_reconcile.py`).
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

## Transfer and integrity settings (reference)

Defaults come from `api/config.py` and `docker-compose.yml`. Override them in the
local `.env`; every value below is optional.

| Variable | Default | Effect |
|---|---|---|
| `AURA_VERIFY_ASYNC_THRESHOLD_BYTES` | `33554432` (32 MiB) | From this size, `commit` answers `202 verifying` and the verifier hashes the object outside the request |
| `AURA_VERIFY_PAUSE_WHILE_UPLOADING` | `1` | The verifier waits while an upload intent created in the last `AURA_VERIFY_PAUSE_WINDOW_S` is still pending (the re-read competes with the PUTs for the disk). `0` restores continuous verification |
| `AURA_VERIFY_PAUSE_WINDOW_S` | `300` | Age after which an abandoned pending intent stops holding the verifier back |
| `AURA_VERIFY_WORKER` | `inline` | `inline` = thread in the API process; `off` = run `python -m api.verifier` separately |
| `AURA_VERIFY_LEASE_SECONDS` / `AURA_VERIFY_HEARTBEAT_BYTES` / `AURA_VERIFY_MAX_ATTEMPTS` / `AURA_VERIFY_POLL_SECONDS` | `300` / 256 MiB / `8` / `2` | Verifier lease, heartbeat, attempts and idle poll |
| `AURA_COMMIT_DEADLINE_S` | `300` | Budget of a synchronous commit. Past it the object is **handed to the verifier (202)**, never deleted. The older name `AURA_COMMIT_DEADLINE_SECONDS` is still read as a fallback |
| `AURA_AV_SCAN_CMD` | empty | Optional antivirus command, run as `cmd <file>` (non-zero = infected). Applied on the synchronous commit **and** in the verifier |
| `AURA_AV_SCAN_TIMEOUT_S` | `120` | A hung scanner times out: commit answers 504 and the object stays pending, the verifier retries |
| `AURA_SCRUB_ENABLED` / `AURA_SCRUB_INTERVAL_DAYS` / `AURA_SCRUB_BYTES_PER_RUN` / `AURA_SCRUB_PERIOD_SECONDS` | `1` / `30` / 10 GiB / `3600` | Periodic re-hash of stored objects. A freshly verified object counts as just checked, and the scrubber yields while uploads are in flight |
| `AURA_RECONCILE_ENABLED` / `AURA_RECONCILE_INTERVAL_S` | `1` / `300` | Background reconciliation of expired intents (minimum 30 s) |
| `AURA_QUOTA_BYTES_PER_DAY` / `AURA_QUOTA_FILES_PER_DAY` | `0` (off) | Daily per-space budget. The counter is **in memory** (reset on restart) and is only debited for requests that are actually accepted |
| `AURA_STORAGE_CAPACITY_BYTES` / `AURA_STORAGE_HIGH_WATERMARK` | `0` (off) / `90` | Capacity guard: uploads are refused with 507 beyond the watermark |
| `AURA_MULTIPART_ENABLED` | `0` | Multipart uploads; keep off until validated on the pinned SeaweedFS |
| `SEAWEEDFS_S3_CACHE_MB` | `256` | `-s3.cacheCapacityMB` of the S3 gateway |
| `SEAWEEDFS_S3_READER_CACHE_MB` | `512` | `-s3.readerCacheSizeMB`: a **blocking** global memory budget for S3 reads. At the former 128 MB, concurrent re-reads (commit, verifier, scrubber, downloads) queued behind each other. Effect on the pilot not measured yet |

How to check the effect of these settings on real uploads: [Measure transfer speed](MEASURE-TRANSFER.md).
