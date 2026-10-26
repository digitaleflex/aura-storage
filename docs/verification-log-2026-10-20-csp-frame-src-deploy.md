# Verification log — CSP `frame-src` redeploy on the pilot VPS (2026-10-20)

> **Note (2026-10-24)** : deux constats de ce log sont périmés. `scripts/deploy.sh`
> sait désormais recréer `app` quand `app/nginx.conf` change, et la taille
> annoncée d'`openapi.yaml` n'est plus celle du fichier courant. Voir
> [`AUDIT-COMPLET-2026-10-24.md`](AUDIT-COMPLET-2026-10-24.md), section 8.

Partial redeploy of the running pilot stack to serve the CSP fix that unblocks
PDF framing from the S3 host. **Not** a full acceptance run: this log records only
what was executed and observed, and marks the rest as not covered.

## Metadata

| Field | Value |
|---|---|
| Date/time | 2026-10-20, ~10:45–11:00 UTC |
| Operator | `aura-admin` (automated session on the VPS) |
| Host | `vps3718250.trouble-free.net`, Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic` |
| Docker / Compose | 29.9.0 (overlayfs) / Compose v5.6.0 |
| Branch | `fix/restore-m2m-tests`, merged as PR #103 |
| Git commit deployed | pre-merge SHAs `87a4a5e` (CSP fix) + `7fc787d` (test restore) + `8e6c504` (this log), deployed from the working tree before the PR existed |
| SHA note | PR #103 was merged with `--rebase`, so the same content now exists upstream as `319fea9` (CSP), `3cd8d2f` (tests), `ed1d4b6` (this log). The pre-merge SHAs are reachable only in the local branch/reflog; the tree is unchanged (`git diff --stat 8e6c504 ed1d4b6` is empty). |
| Purpose | serve `frame-src`/`object-src` = S3 host so inline PDF framing works |

## Pre-deploy state

- `git fetch --all --prune`: no new remote changes; at deploy time `main` was ahead of `origin/main` by 1 (`87a4a5e`).
- Offline suite: `1 failed, 247 passed, 2 skipped` — `tests/test_security_isolation.py` raised
  `NameError: name 'c' is not defined` because two #38 tests had lost their `def` headers
  (`test_identity_revocation_and_rotation`, `test_expired_identity_is_rejected`).
- `.env` was missing `SWAGGER_DOMAIN` (present in `.env.example`, consumed by the `swagger-ui` service).
- Running `aura-001-app` served the old policy: `frame-src 'none'; object-src 'none'`.

## Steps executed

| Step | Result |
|---|---|
| `tests/test_security_isolation.py` restored from `af0d299` (verbatim) | `250 passed, 2 skipped` |
| `SWAGGER_DOMAIN=docs.aura-storage.eurinhash.com` appended to `.env` | added, file mode `0600` preserved |
| `bash scripts/bootstrap.sh` (via `deploy.sh`) | `config/seaweedfs/s3.json` regenerated (0600), compose config validated, preflight checks (placeholders, 64-hex KEK, key lengths) passed |
| `npm ci && npm run build` (`web/dist`, git-ignored) | rebuilt, `dist/index.html` + `index-BzoBW_DF.js` |
| `docker compose build` | `aura-api:local` rebuilt |
| `docker compose pull --ignore-buildable` | all registry images re-pulled; tags identical to `.env` and to the running containers (no version drift; SeaweedFS stays 4.48, `WEED_S3_SSE_KEK` untouched) |
| `docker compose up -d` | `aura-001-api` recreated and healthy |
| `docker compose up -d --force-recreate app` | **required separately** — see gap below |

**Deployment gap found:** `deploy.sh` recreated only `api`. The `app` service bind-mounts
`app/nginx.conf` as `/etc/nginx/templates/default.conf.template`, so a config-file change does
not change the Compose config hash; `docker compose up -d` left `aura-001-app` untouched and the
old `frame-src 'none'` policy stayed live while the script exited 0. The fix only became live
after `docker compose up -d --force-recreate app`.

## Post-deploy observations

| Check | Result |
|---|---|
| `GET https://app.aura-storage.eurinhash.com/` | 200, TLS verified, bundle `index-BzoBW_DF.js` |
| Live `Content-Security-Policy` | `frame-src https://aura-storage.eurinhash.com; object-src https://aura-storage.eurinhash.com;` |
| `POST /api/v1/login` with bogus credentials | 401 (Traefik → api → auth path works) |
| `GET /login` | 200 |
| `docker compose ps` | all 9 services up; `aura-001-api` healthy, `aura-001-postgres` healthy, `aura-001-traefik` healthy |
| Public listeners | only Traefik 80/443 (`ss -ltn`); no SeaweedFS host port published |
| `GET https://aura-storage.eurinhash.com/` | 200 (S3 root landing) |
| Unsigned `GET /app` on the S3 host | 403 XML `AccessDenied` (unchanged) |
| `https://docs.aura-storage.eurinhash.com/` | 403 `Forbidden` (9 bytes) emitted by Traefik itself, not by the container: router `aura-swagger@docker` + `api-docs-allowlist` ipAllowList (`127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.2/32`; `SWAGGER_ADMIN_IP` unset in `.env`). No upstream call (backend `-`, 0–1 ms). Expected until `forwardAuth` is wired. |
| `https://traefik.aura-storage.eurinhash.com/` | 403 from `dash-ipallow` (`DASHBOARD_ALLOWED_IPS` unset → `127.0.0.1/32`) evaluated before `dash-auth`, hence 403 rather than 401. Expected. |
| `https://docs.app.aura-storage.eurinhash.com/` | does not resolve and is routed by nothing: only `SWAGGER_DOMAIN` = `docs.aura-storage.eurinhash.com` exists. A double-label name is not served. |
| Real logged-in admin session in the Traefik access log after the recreate | 200 on `/api/v1/me`, `/api/v1/objects`, `/api/v1/folders`, `/api/v1/admin/*` — the recreated `app` container serves a working session |
| Container logs reviewed | no secrets, no unexpected errors in `api`/`app` tails |

## Not covered

- Authenticated login, upload/download through the API and `ServerSideEncryption=AES256`
  verification were **not** re-run after this deploy.
- Persistence after container restart or host reboot was not exercised.
- Backup/restore, off-site replication and the independent restore test are unchanged and
  still outstanding.
- No acceptance decision is made here; the SSE-S3 key gate and the "no original PDF/audio
  imports" gate remain in force.

## Decision

- [x] Accepted for controlled test only
- [ ] Accepted for production import
- [ ] Rejected / blocked

Outstanding blockers: `deploy.sh` does not recreate `app` on a config-only change; the
authenticated upload/download + SSE-S3 smoke was not re-run; PR #103 merged without an
independent reviewer because the code was already serving the pilot.

Next actions and owner: patch `deploy.sh` to force-recreate `app` (or document the manual
step); re-run the authenticated S3 smoke test before importing any valuable data; record the
review requirement on the next change that reaches `main`.
