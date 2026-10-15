# AURA deployment verification log — 2026-10-15 (Vault console UI: flat folder tree, object moves, paged listing)

> Instance of [verification-log-template.md](verification-log-template.md). Contains no credentials,
> private keys, SSE-S3 keys, full environment dumps, customer filenames or document contents.

## Run metadata

- Date/time (UTC or timezone stated): 2026-10-15, ~12:45–13:05 UTC
- Operator: `aura-admin` (AI-assisted session, human-authorized)
- Repository branch: `feat/vault-console-ui` (deployed from the working tree of that branch)
- Git commit: `e7d5eee` — branch head, 8 commits ahead of `main` (`24c92f9`)
  - deployed commits: `bbe4422` (flat folder listing + object move), `d10c096` (paged listing,
    move dialog, one-request tree), `e1abc3d` (tests), `e7d5eee` (docs)
  - earlier commits on the same branch, already present before this run: `11dc92b`, `edc454e`,
    `19ee9b1`, `c803c62`
- VPS/provider inventory reference (private record, not secrets): InterServer VPS 3718250,
  see [SERVER-PROFILE.md](SERVER-PROFILE.md)
- Maintenance/deployment purpose: deploy the Vault console UI follow-up work and **correct a live
  frontend/API drift** (see below).

## Drift found before this deploy

The `app` container bind-mounts `./web/dist` read-only, so the frontend is served straight from the
host directory, while the API comes from a built image. Before this run the two had diverged:

| | state before the deploy |
|---|---|
| `web/dist` (served live) | **already contained** the new UI (infinite query, move action, `?all=true`) |
| `aura-api:local` image | built `2026-10-15 11:08:51 UTC`, i.e. **older** than the source edits (`12:30 UTC`) |

Evidence: inspecting the running container's route table showed `GET`/`DELETE` on
`/api/v1/objects/{oid}` with **no `PATCH`**, and no `all` parameter was accepted. Effect while it
lasted: the folder tree was incomplete and the move action could not work. The deploy below removed
the drift.

## Host baseline

- OS/release: Ubuntu 26.04.1 LTS
- Running kernel: 7.0.0-38-generic
- Reboot required before/after: **not verified** (no reboot performed)
- SSH key login verified in second session: **not executed in this run**
- Sudo verified: partial — non-interactive sudo is delegated only for `/usr/bin/docker` (and a small
  set of package/system tools). `sudo -n true` requires a password, so general `sudo bash` was not
  used; docker steps ran as `sudo -n docker …`.
- Recovery console tested/available: **not tested**
- Disk allocation reconciled with provider: not reconciled; observed `/` = 2.9T, 11G used (1%)
- Firewall manager and policy reviewed: **not executed in this run**
- WireGuard enabled? If yes, handshake and admin access verified: **not executed**
- Docker/Compose versions: Docker Engine `29.9.0`, Compose `v5.6.0`
- Docker active after reboot: **not verified** (no reboot performed)

## Deployment performed (sanitized)

Executed the equivalent of `scripts/deploy.sh`. `sudo bash scripts/deploy.sh` was not used because
non-interactive sudo is granted only for `/usr/bin/docker`, not `bash`:

1. `bash scripts/bootstrap.sh` — validated the Compose config and regenerated the SeaweedFS S3
   policy file (mode 0600).
2. `npm run build` (in `web/`) — rebuilt the bundle consumed by the `app` container.
   `npm ci` was **skipped on purpose**: `node_modules` was already consistent and the previous
   `tsc --noEmit` had passed on the same tree.
3. `sudo docker compose build` — rebuilt `aura-api:local` from `./api`.
4. `sudo docker compose pull --ignore-buildable` — pulled the registry images. **No image digest
   changed** (traefik `575fa15b1350…`, postgres `2a0d0fe14825…`, seaweedfs `4e61d15fd359…`,
   nginx `a8b39bd9cf0f…` were all identical before and after), so no other container was recreated.
5. `sudo docker compose up -d` — **only `aura-001-api` was recreated**; the other seven containers
   stayed untouched.

Pre-deploy safety dump: **NOT taken**. Rationale: no schema change is involved — `api/migrations.py`
is untouched and the new queries reuse the existing `folder_id` column. This is a deliberate
deviation from the previous run and is listed as a residual risk below.

Rollback: the previous API image `sha256:de1f584c736d…` was **removed by the rebuild**. The reliable
rollback is therefore `git checkout c803c62 && sudo docker compose build && sudo docker compose up -d`.
A tagged image `aura-api:local-pre-f603ec3` (19 h old) is still present locally.

## Application validation

- Compose config validation: **pass** (`docker compose config --quiet` during bootstrap)
- Image tags/release notes reviewed: traefik `v3.7.14`, seaweedfs `4.48`, postgres `17.9`,
  nginx `1.28.3-alpine`, `aura-api:local` (built from this checkout)
- Deployed code equals the local checkout: **md5 identical** for `api/main.py` (`ad7d0bc7…`),
  `api/db.py` (`1be0ac29…`), `api/db_pg.py` (`235d54be…`)
- Deployed API contract: `GET /api/v1/folders` exposes `[parent_id, all, x-csrf-token]`;
  `PATCH` is present on `/api/v1/objects/{oid}` with a request body
- Public service: `app.aura-storage.eurinhash.com` → **200**; `aura-storage.eurinhash.com` → **200**;
  port 80 → **301** to HTTPS
- Served bundle: `assets/index-Brke8ge1.js` + `assets/index-cqsTtfBP.css` (the freshly built ones)
- Authenticated read-only smoke test against the pilot (no catalogue content recorded; the session
  it created was revoked by the closing logout):

  | Request | Result |
  |---|---|
  | `POST /api/v1/login` | 200 |
  | `GET /api/v1/folders?all=true` | 200 (0 folder) |
  | `GET /api/v1/folders` (root) | 200 (0 folder) |
  | `GET /api/v1/folders?all=true&parent_id=root` | **422** (the new rule is live) |
  | `GET /api/v1/objects?folder_id=root&limit=5&offset=0` | 200 (2 objects) |
  | `GET /api/v1/objects?limit=1&offset=0` | 200 (1 object — pagination honoured) |
  | `GET /api/v1/me` | 200 |
  | `POST /api/v1/logout` | 200 |

  One `login success` audit entry was written as a result; no object, folder or user was modified.
- Persistence after container restart: the API was recreated during this deploy and came back
  healthy; PostgreSQL data persisted (its container was never touched)
- Persistence after host reboot: **not executed**
- Logs reviewed for errors/secrets: `aura-001-api` (tail 34), `aura-001-filer` (tail 4000),
  `aura-001-traefik` (tail 1524) → **0** occurrences of the SSE-S3 KEK and **0**
  `error`/`traceback`/`exception` lines

## Local test evidence for this change

Run on the deployed tree before the push (`feat/vault-console-ui` @ `e7d5eee`):

| Check | Result |
|---|---|
| `pytest tests/` (SQLite, offline) | **125 passed, 2 skipped** |
| `tests/test_pg_parity.py` against a **disposable** PostgreSQL 17.9 container | **1 passed** |
| Playwright e2e against an isolated stack (API 8082 / Vite 5174) | **7 passed** |
| `npm run build` (`tsc --noEmit && vite build`) | pass, 175 modules |
| `git diff --check` | clean |

The e2e stack ran on separate ports precisely so the long-running dev servers (8081/5173) and the
production stack were never touched. The parity test ran against a throwaway container on a
loopback-only port, never against the pilot database.

## Backup and recovery

- Backup destination independent of VPS: **NO** — and there is currently **no backup automation at
  all**: no `scripts/*backup*`, no user crontab, no systemd timer. `docs/BACKUP-RESTORE.md`
  describes a purely manual procedure. `/srv/aura-storage` holds 3.9 MB.
- Backup method/release-specific consistency guidance: n/a (nothing automated)
- SSE-S3 key recovery verified (do not record the key): **not executed**
- Restore environment isolated: **not executed**
- Restored objects readable/decryptable: **not executed**
- Restored object hashes match: **not executed**
- Restore duration: n/a
- Outcome and corrective actions: unchanged — the blockers below remain open.

## Not executed in this run (with reasons)

- `tests/sse-s3-smoke-test.sh`, `tests/s3-smoke-test.sh`: require a real endpoint plus AWS CLI; not
  run here. (The SSE-S3 smoke test did pass on 2026-10-15 in the earlier run — see
  [verification-log-2026-10-15-canonical-ids.md](verification-log-2026-10-15-canonical-ids.md).)
- Independent backup/restore test, SSE-S3 key recovery, host-reboot persistence: not executed.
- Original PDF/audio import: not executed and still not permitted.

## Decision

- [x] Accepted for controlled test only
- [ ] Accepted for production import
- [ ] Rejected / blocked

Outstanding blockers (unchanged):

- No **independent** backup/restore test; no backup automation exists at all.
- SSE-S3 **key** recovery not verified.
- Host **reboot** persistence not verified.
- The PostgreSQL migration path passed in the earlier run; broader acceptance still rests on the
  tests listed in [DEPLOYMENT.md](DEPLOYMENT.md) §6.
- This run took **no pre-deploy dump** (no schema change was expected); a rollback would rebuild
  from `c803c62`.

## Recorded decision — deferral of the outstanding gates (operator, 2026-10-15)

On 2026-10-15 the operator decided to **defer the four outstanding gates by roughly three months**
(review target: **mid-January 2027**) in order to prioritise revenue-generating work.

- Deferred: (1) the independent backup/restore test, (2) the offline `WEED_S3_SSE_KEK` backup,
  (3) the host-reboot persistence test, and (4) consequently the import of original PDF/audio files.
- **The gates themselves are not modified, relaxed or removed.** They keep their blocking character
  and apply again at the first valuable import.
- Residual risk while the deferral lasts: `/srv/aura-storage` is 3.9 MB with essentially no
  production objects, so the immediate exposure is low and no valuable data is at risk **as long as
  nothing valuable is imported**. The deferral stops being low-risk at the first real import.
- Cheapest mitigation, available immediately and without touching the VPS: copy the 64-hex
  `WEED_S3_SSE_KEK` into an offline store outside the VPS. Key recovery is the only gate whose
  deferral carries no economic benefit: losing it makes SSE-encrypted objects unrecoverable.
- There is **no automation** that would remind anyone of the review date; it must be honoured
  manually by the operator.
- Approval to migrate originals (must be explicit): **not granted**.

## Network and throughput validation (not yet executed)

Not executed in this run; see [NETWORK-AND-THROUGHPUT-PLAN.md](NETWORK-AND-THROUGHPUT-PLAN.md).

## SSH access verification

Not executed in this run; see
[SSH-ACCESS-AND-KEY-MANAGEMENT.md](SSH-ACCESS-AND-KEY-MANAGEMENT.md). Sudo here is delegated
non-interactively only for `/usr/bin/docker`.
