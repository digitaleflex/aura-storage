# AURA deployment verification log — 2026-10-15 (canonical UUID v4 identifiers + logical folders)

> Instance of [verification-log-template.md](verification-log-template.md). Contains no credentials,
> private keys, SSE-S3 keys, full environment dumps, customer filenames or document contents.

## Run metadata

- Date/time (UTC or timezone stated): 2026-10-15, ~11:00–11:20 UTC
- Operator: `aura-admin` (AI-assisted session, human-authorized)
- Repository branch: `main` (deployed from `main`)
- Git commit: `8df0879` — `Merge pull request #68 from digitaleflex/feat/canonical-uuid-ids`
  - included commits: `5276fff` (canonical UUID v4 identifiers), `4c079b5` (logical folder CRUD, #61)
- VPS/provider inventory reference (private record, not secrets): InterServer VPS 3718250,
  see [SERVER-PROFILE.md](SERVER-PROFILE.md)
- Maintenance/deployment purpose: deploy the canonical UUID v4 identifier change and the logical
  folder CRUD to the pilot; rebuild the API image; run the catalogue migration on live PostgreSQL.

## Host baseline

- OS/release: Ubuntu 26.04.1 LTS
- Running kernel: 7.0.0-38-generic
- Reboot required before/after: **not verified** (DEPLOYMENT.md records a pending reboot; no reboot performed)
- SSH key login verified in second session: **not executed in this run**
- Sudo verified: partial — non-interactive sudo is delegated only for `/usr/bin/docker` (and
  `apt*`, `mkdir`, `chown`, `chmod`, `systemctl`); general `sudo bash` requires a password and was
  not used. Docker steps were run with `sudo -n docker …`.
- Recovery console tested/available: **not tested**
- Disk allocation reconciled with provider: not reconciled; observed `/` = 2.9T, 11G used (1%)
- Firewall manager and policy reviewed: **not executed in this run**
- WireGuard enabled? If yes, handshake and admin access verified: **not executed**
- Docker/Compose versions: Docker Engine `29.9.0`, Compose `v5.6.0`
- Docker active after reboot: **not verified** (no reboot performed)

## Deployment performed (sanitized)

Executed the equivalent of `scripts/deploy.sh`. `sudo bash scripts/deploy.sh` was not used because
non-interactive sudo is granted only for `/usr/bin/docker`, not `bash`:

1. `bash scripts/bootstrap.sh` — validated Compose config and regenerated the SeaweedFS S3 policy file.
2. `npm ci && npm run build` (in `web/`) — rebuilt the frontend bundle consumed by the `app` container.
3. `sudo docker compose build` — rebuilt `aura-api:local` (image `sha256:de1f584c736d…`).
4. `sudo docker compose pull --ignore-buildable` — pulled registry images.
5. `sudo docker compose up -d` — only `aura-001-api` was recreated; the other containers stayed up.

Pre-deploy safety dump (not independent of the VPS):
`~/backups/aura-postgres-20261015T110746Z.dump` (`pg_dump -Fc`, SHA-256 recorded alongside), taken
**before** the migration. Previous API image for rollback: `sha256:98483bf136c7…`.

## Catalogue migration evidence (PostgreSQL, live pilot)

| | before | after |
|---|---|---|
| application `aura` | `00000000-0000-0000-0000-000000000001` | `f6d17b2c-fb50-4c14-b954-57f24b6bd7a9` |
| space `default` (prod) | `00000000-0000-0000-0000-000000000002` | `8114dd82-843f-4730-a061-953dd07aed42` |
| bucket `aura` | `00000000-0000-0000-0000-000000000003` | `0d1aa78d-5761-410d-9d4a-8098f7665991` |
| `schema_migrations` | `0001_multiplatform` | `0001_multiplatform`, `0002_canonical_ids` |

Foreign keys repointed: `users` (admin), `objects` (2 rows: `application_id`, `space_id`,
`environment`). No `service_identities` rows existed. Migration is one-time and idempotent.

## Application validation

- Compose config validation: **pass** (`docker compose config --quiet` during bootstrap)
- Image tags/release notes reviewed: traefik `v3.7.14`, seaweedfs `4.48`, postgres `17.9`,
  nginx `1.28.3-alpine`, `aura-api:local` (built from this checkout)
- DNS A/AAAA validated: A → `153.75.248.230` for both `app.aura-storage.eurinhash.com` and
  `aura-storage.eurinhash.com`; **no AAAA record**
- HTTPS certificate validated externally: `app…` CN=`app.aura-storage.eurinhash.com`, issuer
  Let's Encrypt, valid to 2027-01-12; `aura-storage.eurinhash.com` issuer Let's Encrypt, valid to
  2027-01-12
- Public listening ports reviewed: only TCP `80` and `443` listening
- Internal SeaweedFS ports not publicly reachable: consistent with the port scan (only 80/443
  listening); not directly probed from outside
- S3 unauthenticated request denied: `GET https://aura-storage.eurinhash.com/aura/` → **403**
  (`GET /` on the S3 host is the landing page → 200)
- Authenticated test upload/download: **PASS** (`tests/sse-s3-smoke-test.sh`, temp bucket, cleaned up)
- SSE-S3 response reports AES256: **PASS**
- Downloaded bytes/hash match: **PASS** (`ServerSideEncryption=AES256`, SHA-256 identical)
- Persistence after container restart: **not executed as a dedicated test** (the API was recreated
  during this deploy and came back healthy; PostgreSQL data persisted)
- Persistence after host reboot: **not executed**
- Logs reviewed for errors/secrets: `aura-001-api` → 0 `error|traceback|exception` lines; the
  SSE-S3 KEK does not appear in `api`, `filer` or `traefik` logs (occurrence count 0)

## Backup and recovery

- Backup destination independent of VPS: **NO** — the safety dump is on the same host (`~/backups`)
- Backup method/release-specific consistency guidance: `pg_dump -Fc` of the catalogue database
- SSE-S3 key recovery verified (do not record the key): **not executed**
- Restore environment isolated: **not executed**
- Restored objects readable/decryptable: **not executed**
- Restored object hashes match: **not executed**
- Restore duration: n/a
- Outcome and corrective actions: pre-migration dump taken for rollback only. An independent backup
  and a restore test remain required before importing valuable data.

## Decision

- [x] Accepted for controlled test only
- [ ] Accepted for production import
- [ ] Rejected / blocked

Outstanding blockers:

- No **independent** backup/restore test (the safety dump is local to the VPS).
- SSE-S3 **key** recovery not verified; host **reboot** persistence not verified.
- The PostgreSQL migration path had not been exercised before this run and passed here; broader
  acceptance still rests on the tests listed in DEPLOYMENT.md §6.

Next actions and owner: (1) run a restore test into an isolated environment; (2) verify the SSE-S3
key backup; (3) schedule a host reboot with persistence checks.

Approval to migrate originals (must be explicit): **not granted** — no original PDF/audio imported.

## Network and throughput validation (not yet executed)

Not executed in this run; see [NETWORK-AND-THROUGHPUT-PLAN.md](NETWORK-AND-THROUGHPUT-PLAN.md).

## SSH access verification

Not executed in this run; see
[SSH-ACCESS-AND-KEY-MANAGEMENT.md](SSH-ACCESS-AND-KEY-MANAGEMENT.md). Sudo here is delegated
non-interactively only for `/usr/bin/docker` (and a small set of package/system tools).
