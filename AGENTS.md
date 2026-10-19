# AGENTS.md — Working rules for AURA Storage

This repo is a **pre-deployment pilot**. The stack has not passed acceptance on the
real VPS. Do not treat a passing CI check or `docker compose config` as production proof.

## Real architecture (implemented)

- Single VPS, Docker Compose: **Traefik** (ports 80/443, Let's Encrypt HTTP-01) +
  **SeaweedFS** master / volume / filer-S3 gateway (S3 on internal port 8333).
  See `docker-compose.yml`, `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE.mmd`.
- Environment-first config: local `.env` + generated `config/seaweedfs/s3.json`
  (via `scripts/generate-config.sh`). Both are git-ignored. See
  `docs/ENVIRONMENT-CONFIGURATION.md`.
- Deployment runbook: `docs/DEPLOYMENT.md`, reproducible setup:
  `docs/REPRODUCIBLE-SETUP.md`, host checklist: `docs/HOST-BOOTSTRAP-CHECKLIST.md`,
  server facts: `docs/SERVER-PROFILE.md`.

## Implemented (code + offline tests)

- Management API (`api/`) with session auth, CSRF, presigned S3 intents, role-based
  authorization and machine-to-machine identities. See `docs/AUTHORIZATION-MATRIX.md`.
- Catalogue backends: SQLite (dev/test) and PostgreSQL (`api/db.py`, `api/db_pg.py`),
  with additive migrations in `api/migrations.py`.
- Offline test suite under `tests/` (run with `.venv/bin/python -m pytest tests/`).

Implemented in code is **not** the same as validated on the pilot: the stack is
deployed there with partial dated evidence (bootstrap OK, live PostgreSQL
migration, SSE-S3 smoke PASS — see the `docs/verification-log-2026-10-1*.md`
logs) but has **not** passed acceptance.

## Specified only (NOT implemented)

OpenBooks/Axiom integrations. Additional endpoint drafts live in
`docs/API-SPECIFICATION.md` and `docs/openapi.yaml`; treat anything not listed in
`docs/AUTHORIZATION-MATRIX.md` as unavailable.

## Local validation (non-destructive only)

```bash
git status --short --branch && git log -3 --oneline
bash -n scripts/*.sh tests/*.sh
bash tests/test-s3-smoke-validation.sh
python3 -m json.tool config/seaweedfs/s3.json.example > /dev/null
AURA_API_ADMIN_PASSWORD=ci AURA_S3_ACCESS_KEY=ci-1234567890 \
  AURA_S3_SECRET_KEY=ci-12345678901234567890 AURA_S3_ENDPOINT=https://127.0.0.1:9 \
  AURA_API_DB=:memory: AURA_COOKIE_SECURE=0 .venv/bin/python -m pytest tests/ -q
git diff --check
```

On this host the system `python3` has no `pytest`; run the suite with the project
virtualenv interpreter (`.venv/bin/python`). If `.venv` is missing, create it with
`python3 -m venv .venv` and install `api/requirements.txt` into it first.
`docker compose config --quiet` requires a local `.env`; never commit it.
`tests/sse-s3-smoke-test.sh` and `tests/s3-smoke-test.sh` require a real endpoint
and AWS CLI — do not run them against production without explicit approval.

## Hard prohibitions

- Never commit `.env`, `config/seaweedfs/s3.json`, keys, certificates, user files,
  backups, or customer data. Check with `git check-ignore` and review the full diff.
- Never print secrets, tokens, private keys, or the SSE-S3 key into logs, issues, or chat.
- No deployments, no Docker/host changes, no SSH/firewall/network/service changes,
  no `sudo`, no reboots without explicit human authorization.
- Never work directly on `main`; use a dedicated branch. Never push or merge without
  approval after green local tests and confirmed remote access.

## Change discipline

- Minimal diffs; preserve unique procedures and warnings when touching docs.
- If a docs merge needs editorial arbitration, keep both files and document the
  proposal instead of deleting content.
- Every fix needs a test or a stated reason, plus a report: files changed, tests run
  with real results, tests NOT run with reasons, pending risks/decisions.

## Critical gates (do not bypass)

- **SSE-S3 key (`WEED_S3_SSE_KEK`)**: 64 hex chars, offline backup outside VPS and repo.
  Loss may make encrypted objects **unrecoverable**; rotation is a migration, not an edit.
- **No original PDF/audio imports** until HTTPS, auth, SSE-S3 (`ServerSideEncryption=AES256`
  + matching SHA-256), persistence, and an **independent backup restore test** all pass.
  Keep local originals until then. See `docs/SECURITY.md`, `docs/BACKUP-RESTORE.md`,
  `docs/verification-log-template.md`.
