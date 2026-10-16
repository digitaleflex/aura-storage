# AURA deployment verification log — 2026-10-16 (S16 Vault explorer polish + API rebuild)

> Instance of verification-log-template.md. Contains no credentials,
> private keys, SSE-S3 keys, full environment dumps, customer filenames or document contents.

## Run metadata

- Date/time: 2026-10-16, ~09:45–10:15 UTC
- Operator: `aura-admin` (AI-assisted session, human-authorized "Go déploiement VPS")
- Repository branch: `main` (merged + pushed this run)
- Git commit: `4c97b72` — merges `def9fa9` (maquette PNG) + `feat/vault-ui-s16`
  (`54f589a` web polish/tokens/specs, `5595d7b` docs UI-AUDIT, `03578d9` gitignore dist backups)
  on top of `dcd63d8` (catalogue soft-delete filter), `3168ff5` (orphans),
  `382b45d` (toasts/skeletons), `02afba0` (P0 drop/selection)
- VPS/provider inventory reference: InterServer VPS 3718250, see SERVER-PROFILE.md
- Maintenance/deployment purpose: deploy the S16 Vault explorer work
  (drop backlog fix, 409 folder-delete handling, real admin usage, conditional
  SHA-256 chip, Vault token layer, mocked e2e spec) plus the pending API fixes.

## Drift found before this deploy

- `up -d` after `compose build` did NOT recreate `aura-001-api`: the container
  kept running the previous image while the fresh build changed the tag.
  Fixed with an explicit `docker compose up -d --force-recreate --no-deps api`.
  Open question (not blocking): why the plain `up -d` missed the image change.
- The previous API image was superseded by the rebuild. Rollback: retag
  `aura-api:local-pre-f603ec3` (present locally) or rebuild from the
  pre-merge commit, then `up -d --force-recreate --no-deps api`.
- No schema change in this deploy (`api/migrations.py` untouched; diff scan for
  DDL came back empty), so no pre-deploy catalogue dump was taken (residual risk,
  same rationale as the 2026-10-15 vault-console-ui run).

## Host baseline

- OS/release: Ubuntu 26.04 LTS (per SERVER-PROFILE.md; not re-verified this run)
- Reboot required before/after: not verified (no reboot performed)
- Docker access this run: via `sg docker` (group membership); direct `sudo`/`ssh`
  remain unavailable from the AI session sandbox
- Docker/Compose versions: not re-recorded (stack already running; see prior log
  for Engine 29.9.0 / Compose v5.6.0)

## Deployment performed (sanitized)

1. `bash scripts/bootstrap.sh` — pass (compose syntax validated, s3.json regenerated 0600).
2. `npm run build` in `web/` — pass (180 modules, Vault tokens present in bundle).
   `web/dist` is bind-mounted into the `app` container, so the new UI went live.
3. `docker compose build` — pass (new `aura-api:local` built from `./api`).
4. `docker compose pull --ignore-buildable` — pass (traefik v3.7.14, seaweedfs 4.48,
   postgres 17.9, nginx 1.28.3-alpine; no digest surprise recorded).
5. `docker compose up -d` + `up -d --force-recreate --no-deps api` — only
   `aura-001-api` and `aura-001-traefik` recreated; all 8 containers healthy after.

## Application validation

- Compose config validation: pass (during bootstrap).
- API `/health/live`: 200, container healthy.
- S3 root (`S3_DOMAIN`, Host-header check from VPS): 200.
- App (`APP_DOMAIN`, Host-header check from VPS): 200.
- SSE-S3 smoke (`tests/sse-s3-smoke-test.sh`): **PASS** —
  `ServerSideEncryption=AES256` reported and downloaded bytes match.
  (Proves the S3 API path only, not backup/restore or disk-level encryption.)
- HTTPS certificate validated externally: not executed in this run.
- Internal SeaweedFS ports not publicly reachable: not re-verified in this run.
- Persistence after container restart: not re-verified in this run.
- Independent backup + restore test: **still open** (deployment gate).

## Gates and prohibitions restated

- Do NOT import original PDF/audio files until HTTPS, auth, SSE-S3, persistence,
  and an independent backup restore test all pass. Keep local originals.
- `WEED_S3_SSE_KEK` stays in server-side `.env` (0600) + offline copy only.
