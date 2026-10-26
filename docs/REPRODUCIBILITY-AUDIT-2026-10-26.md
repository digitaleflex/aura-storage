# Reproducibility audit — what a rebuild from `origin/main` gets wrong

**Date:** 2026-10-26 · **Host:** pilot VPS, project `aura-storage` · **Method:** read-only. `git diff`, `git show`, `docker inspect`, `docker network inspect`, `docker exec … grep`. No container, network or volume was created, removed or restarted. `.env` was not read.

**References used**

| Ref | Commit | Note |
|---|---|---|
| Remote `origin/main` | `fdaaac7` | what `git clone origin/main` checks out |
| Local `main` (= `HEAD`) | `867e28d` | 17 commits ahead of `origin/main` |
| Working tree | `867e28d` + 55 modified + 11 untracked files | what is actually deployed |

The API image on this host (`aura-api:local`, built 2026-10-25T22:31Z) contains working-tree code, not `HEAD` (`/admin/objects/{oid}/reverify` is present in `/srv/api/api/main.py`, and is absent from both `HEAD` and `origin/main`). So the deployed state matches **no pushed commit at all**.

---

## 1. Verdict

**No — a rebuild from `origin/main` is not faithful, and not only for the reasons in the prior audit.** Two gaps stack. First, `origin/main` is 17 commits behind local `main` at the time of this audit (the gap grows with every local commit), so a clone silently omits the multipart gate, the edge-proxy upload retry, the diag page, the folder-purge fixes and the removal of two dev-only scripts. Second, `docker-compose.yml` is identical in `HEAD` and `origin/main`, and that file hardcodes a 90-day session TTL (ignoring `.env`), trusts all of RFC1918 as proxies, wires the API to the bootstrap SeaweedFS **Admin** key, and ships no `read_only` / `cap_drop` / `mem_limit` / `cpus` for the API. On top of the compose file, 66 files of behaviourally significant API, web, nginx and S3-identity changes exist only in the working tree. A clone today produces a stack that is *less* secure and *less* correct than the host, and two of the differences are silent.

---

## 2. Drift table

`wt:` = working-tree `docker-compose.yml` line. `HEAD:` = `git show HEAD:docker-compose.yml` line (`origin/main` is byte-identical for this file). "Deployed" = observed on the running containers, 2026-10-26.

| # | Setting | Deployed now | `HEAD` (`origin/main`) | Consequence if rebuilt from `HEAD` |
|---|---|---|---|---|
| 1 | `AURA_SESSION_TTL` | `28800` (8 h), read from container env | literal `"7776000"` (90 days), `HEAD:263` — **no** `${…}` interpolation | Every new login gets a 90-day cookie. `.env` cannot override it: the literal wins. Silent. |
| 2 | `AURA_TRUSTED_PROXIES` | `127.0.0.1/32,::1/128,172.30.0.0/24,172.31.0.0/24,172.32.0.0/24` | `${AURA_TRUSTED_PROXIES:-127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}`, `HEAD:314` | Defaults to all RFC1918: any storage/app container can forge `X-Forwarded-For` and dodge per-IP login and M2M limiters. An explicit `AURA_TRUSTED_PROXIES` in `.env` still survives (it is interpolated). |
| 3 | API S3 credential source | `S3_API_ACCESS_KEY`/`S3_API_SECRET_KEY` → `aura-api` identity, `actions: [Read, Write, List]` (wt:220-221) | `S3_ACCESS_KEY`/`S3_SECRET_KEY`, both `${…:?}`, `HEAD:254-255` | Compose aborts if only `S3_API_*` is provisioned; otherwise the API runs as the bootstrap **Admin** key (see trap 2). |
| 4 | `api` rootfs | `ReadonlyRootfs: true`, `tmpfs /tmp:size=256m` (wt:324-326) | absent (only `no-new-privileges`, `HEAD:389-390`) | Writable rootfs; a compromised API can persist a payload in its own filesystem layer. |
| 5 | `api` capabilities | `CapDrop: ["ALL"]` (wt:327-328) | absent | Default Docker capability set is restored; `no-new-privileges` alone does not drop any capability. |
| 6 | `api` resources | `Memory: 2147483648`, `NanoCpus: 2000000000` (wt:331-332) | absent | No ceiling: a runaway verify/scrub can OOM the host and starve SeaweedFS/Postgres. |
| 7 | `PYTHONDONTWRITEBYTECODE` | `1` (wt:212) | absent | Part of the same package: keeps the API from attempting `__pycache__` writes on the read-only rootfs of #4 (Python skips the write silently, so this is hygiene, not a functional break). |
| 8 | `AURA_MAX_PENDING_BYTES_PER_OWNER` | `107374182400` in env (wt:255) and honoured by `api/config.py:191-193` | not in compose, **not in `api/config.py`** | The per-owner reservation cap disappears from both config and code: one account can hold the entire disk with declared-but-never-sent multipart intents. |
| 9 | Boot-time session sweep | `revoke_sessions_beyond()` at startup (`api/main.py`, `api/db*.py`) | absent | Rows minted under the old 90-day policy keep living after the policy changes; no shrink is retroactive. |
| 10 | Dashboard router + shared middlewares | declared on `app` (wt:419-471) | declared on the `traefik` container (`HEAD:53-103`) | Placement difference only, statically verified. If Traefik v3.7 ignores its own container's labels (asserted in the wt comment, **not reproduced here**), the dashboard router and every middleware referenced as `aura-hsts@docker` / `api-ratelimit` / `api-docs-auth` fail to load. |
| 11 | `aura-s3-landing-head` router | present (wt:516-522) | absent | `HEAD /` on the S3 domain falls through to SeaweedFS → 405 instead of the landing page. |
| 12 | `app` healthcheck + `depends_on` | healthcheck on `/`, `api: condition: service_healthy` (wt:401-410) | no healthcheck, `condition: service_started` (`HEAD:415`) | The SPA is served while the API is still booting; same-origin calls 5xx. |
| 13 | `app` resources | `Memory: 268435456`, `NanoCpus: 1000000000` (wt:407-408) | absent | No ceiling on the static frontend. |
| 14 | Network subnets | `aura-edge` 172.30.0.0/24, `aura-docs` 172.31.0.0/24, `aura-storage-internal` 172.32.0.0/24 (wt:579/588/594, confirmed by `docker network inspect`) | no `ipam` block | Docker assigns arbitrary subnets, so `HEAD`'s default trusted-proxy list cannot even name the real proxy networks; `AURA_TRUSTED_PROXIES` and reality drift apart. |
| 15 | Traefik access log | `--accesslog.fields.queryparameters.defaultmode=drop` (wt:30, in live `Cmd`) | absent | Presigned URLs (`X-Amz-Signature`, `X-Amz-Credential`) land verbatim in `docker logs`. |
| 16 | `POST /api/v1/admin/objects/{oid}/reverify` | present (6 occurrences in the container's `api/main.py`) | absent from `HEAD` and `origin/main` | An operator cannot clear a `suspect` object after a re-hash; objects stay quarantined. |
| 17 | `SERVICE_SCOPES` | `read, write, delete` — `objects:purge` removed (`api/authz.py`) | includes `objects:purge` | A leaked machine token can permanently erase objects. |
| 18 | README install instructions | `git clone --branch main …` | `git clone --branch feat/secure-storage-pilot …` (`HEAD:README.md:63`), branch absent from `origin` | Following the repo's own README fails at clone time, or lands on a dead branch. |
| 19 | `HEAD .env.example` vs `HEAD` compose | — | `.env.example:148` documents `AURA_SESSION_TTL=28800` while compose pins `7776000` | The documented value is inert; an operator provisioning per the example still gets 90 days. |

**Claims corrected**

- **Claim 3 (S3 env names):** confirmed as a name change, but "breaks API→S3 authentication" is only half true. With `S3_API_*` only, compose **aborts at interpolation** (`required variable S3_ACCESS_KEY is missing a value`, reproduced with an isolated compose file). If the bootstrap `S3_*` are present — which the same `.env` normally carries, and which a working-tree deploy already needs for `generate-config.sh`'s equality guard — authentication **succeeds as Admin**. The realistic failure is privilege escalation, not a 403.
- **Claim 5 (dashboard/docs middlewares "missing in HEAD"):** **wrong as stated.** `DASHBOARD_AUTH` (`HEAD:62`), `DOCS_AUTH` (`HEAD:103`), `api-ratelimit` (`HEAD:83-84`), `aura-hsts` (`HEAD:69-70`) and `api-secure-headers` all exist in `HEAD`. What changed is *where* they are declared: `HEAD` puts them on the Traefik container, the working tree moved them to `app`. Nothing was dropped; row 10 records the placement and flags the runtime effect as unverified.
- **Claim 1 direction:** the prior audit has the numbers right, but the trap runs the other way — a rebuild **lengthens** sessions from 8 h to 90 days and ignores `.env`, it does not shorten them.
- **No claim was dropped for lack of evidence.** One consequence (row 10) is marked static-only because proving it requires creating containers, which this audit refused to do.

---

## 3. The three traps that would bite a fresh deploy

**Trap 1 — the session that silently becomes 90 days, and cannot be fixed from `.env`.**
`HEAD:263` is a YAML string literal, not an interpolation. A fresh operator copies `.env.example`, which says `# AURA_SESSION_TTL=28800` (`HEAD:.env.example:148`), uncomments it, and believes sessions last 8 h. Compose ignores it: `settings.session_ttl` receives `7776000` from the container env and every `/api/v1/login` mints a cookie valid for three months. The expiry is fixed at login (no renewal), so nothing shortens it later, and `revoke_sessions_beyond()` — the working-tree startup sweep that deletes over-long rows — does not exist in `HEAD`. The only fix is a commit; no `.env` value helps.

**Trap 2 — the API that comes back as the storage Admin.**
The deployed API authenticates to SeaweedFS with a dedicated `aura-api` identity (`Read/Write/List`, no `Admin`; `config/seaweedfs/s3.json` holds a non-empty 24-character access key for it, and `scripts/generate-config.sh` refuses to reuse the bootstrap keys). `HEAD` reads `${S3_ACCESS_KEY:?}` / `${S3_SECRET_KEY:?}` instead. Two outcomes, both bad: if the target `.env` was provisioned from the working-tree example (`S3_API_*` only), `docker compose up` dies immediately with *"required variable S3_ACCESS_KEY is missing a value"* — a hard stop that looks like a config typo. If the bootstrap `S3_*` are present, which `generate-config.sh` implies, the API starts fine and now holds `Admin` on the object store: it can create identities, rewrite bucket policy and bypass every restriction the `aura-api` identity was introduced to enforce. `HEAD`'s `generate-config.sh` also re-stamps the bootstrap key into the `aura-api` credential, erasing the separation at the source.

**Trap 3 — the API container that loses its hardening.**
`HEAD`'s `api` service keeps only `no-new-privileges` (`HEAD:389-390`). The four controls that are actually running — `read_only: true` with a 256 MB `/tmp` tmpfs, `cap_drop: [ALL]`, `mem_limit: 2g`, `cpus: 2.0` (wt:324-332) — do not exist in git. After a rebuild the API runs as root on a writable overlay with the default capability set and no memory ceiling. Nothing fails loudly: `/health/live` stays green, so the regression is invisible until it is exploited or until a verify/scrub spike takes the host down. `PYTHONDONTWRITEBYTECODE=1` (wt:212) belongs to the same package: without it the API keeps trying to write `__pycache__` into the read-only rootfs (Python skips the write silently, so this is hygiene rather than a boot failure).

Two non-security traps in the same family: `HEAD /` on the S3 domain returns 405 after a rebuild (row 11), and the `traefik` container may come up before `app`'s routers exist because `HEAD` has no `app` healthcheck and no post-`up` Traefik restart (row 12; `scripts/deploy.sh` now restarts Traefik explicitly).

---

## 4. What a clean clone loses from the working tree

66 files at audit time: 55 modified, 11 untracked (this document, created afterwards, is not counted). Behaviourally important ones only.

**`api/` (9 files)** — the largest correctness gap.
- `api/main.py` — `/admin/objects/{oid}/reverify`; boot-time `revoke_sessions_beyond()`; downloads forced to `attachment`; preview integrity gate; bounded login-attempt table; 5 s readiness cache; reservation lock around upload intents.
- `api/authz.py` — `objects:purge` removed from `SERVICE_SCOPES`; M2M limiter table bounded at 10 000 entries.
- `api/db.py`, `api/db_pg.py` — `revoke_sessions_beyond()`, `reserved_bytes_for()`, `mark_reverified()`.
- `api/config.py` — `AURA_MAX_PENDING_BYTES_PER_OWNER` (100 GiB default).
- `api/audit.py` — prune locks a `.lock` sidecar, not the journal (`os.replace` swaps the inode).
- `api/lifecycle.py` — abort the multipart session before deleting its row; extra reconciliation grace.
- `api/verifier.py` — `superseded` outcome when the row disappears mid-hash; accepts the `suspect` state.
- `api/object_query.py` — `suspect` added to `OBJECT_STATUSES`.

**`web/` (17 files)**
- `src/lib/api.ts` — `AbortSignal`/`timeoutMs` plumbing; global `aura:unauthorized` event on 401.
- `src/lib/auth.tsx` — logout always wipes local state and `queryClient.clear()` (no cross-account flash).
- `src/lib/safeStorage.ts` *(new)* — `localStorage` throws (private mode/quota) no longer white-screen the app.
- `src/theme-boot.ts` *(new)* + `main.tsx` + `index.html` — inline theme script moved to a module; the inline version is blocked by the production CSP.
- `src/lib/download.ts` — a truncated stream is now an error instead of `integrityOk: true`.
- `src/lib/csv.ts` — formula-injection prefix for `=`, `+`, `-`, `@`.
- `src/components/PreviewModal.tsx` — `sandbox` on the cross-origin PDF iframe.
- `src/pages/ObjectsPage.tsx` — popup opened inside the user gesture (blocked after `await` otherwise).
- `package.json` / `package-lock.json` — every `latest` replaced by a pinned version.
- `public/robots.txt`, `public/sitemap.xml` *(new)*.

**`scripts/` (4 files)**
- `deploy.sh` — `compose up --wait`, rebuild/recreate `app` + `s3-landing` on nginx/landing change, explicit `traefik` restart, `chown` of root-owned build artifacts.
- `bootstrap.sh` — recovers `npm` from the invoking user's `~/.node`/nvm when run under `sudo` (otherwise the deploy dies on `npm: not found`).
- `generate-config.sh` — writes the `aura-api` credential from `S3_API_*`, refuses `S3_API_*` equal to the bootstrap keys, and no longer stamps the bootstrap key into a `REPLACE_` placeholder.
- `reconcile-cron.sh` — exit-status/noise fix.

**`config/` (1 file)**
- `seaweedfs/s3.json.example` — the least-privilege `aura-api` identity (`Read/Write/List`).

**`.github/` (3 files)** — all actions pinned by commit SHA; `appleboy/ssh-action` moved `v0.1.8` → `v1.2.5`. Supply-chain hardening only, no runtime effect.

**`app/` (1 file)** — `nginx.conf`: `server_tokens off`, gzip (the 460 kB bundle), `Permissions-Policy`, `Cross-Origin-Opener-Policy`, immutable caching for `/assets/`.

**`landing/` (2 files)** — `entrypoint.sh` now installs `nginx.conf` into `conf.d`; it was mounted but never copied, so the image's default server answered without CSP/`X-Frame-Options`/nosniff. `nginx.conf`: `server_tokens off`, gzip.

**`docs/` (21 files)** — six untracked (`SECURITY.md`, `DEPLOYMENT.md`, `BACKUP-RESTORE.md`, `AUTHORIZATION-MATRIX.md`, `AUDIT-COMPLET-2026-10-24.md`, `AUDIT-REMEDIATION-2026-10-24.md`) plus updates to the API/architecture/ops docs. No runtime effect, but `.env.example` (working tree) points readers at `docs/SECURITY.md` for the S3 key migration, which does not exist in a clone.

**Root**
- `docker-compose.yml` — all of §2.
- `.env.example` — documents `S3_API_*`, `AURA_MAX_PENDING_BYTES_PER_OWNER`, `AURA_SESSION_TTL=28800`. Its line 190 still shows the **old broad** `AURA_TRUSTED_PROXIES`; uncommenting it re-opens row 2.
- `README.md` — clone branch `feat/secure-storage-pilot` → `main`; status section updated.
- `.deploy-nginx-hash` — deploy bookkeeping (tracked); a clone carries a stale hash, so `deploy.sh` force-recreates `app`/`s3-landing` once.

**`tests/` (4 files)** — security-isolation and M0x matrices updated for the machine-purge denial and forced-attachment behaviour; they encode working-tree expectations (machine purge → 403), so they are not runnable against `HEAD` unchanged. Test signal, not a deployment input.

---

## 5. Smallest set of actions that makes a rebuild faithful

Ordered; each item marked **[commit]**, **[.env]**, or **[verify]**. Nothing here was executed.

1. **[commit]** Commit the working tree and push `main`, so `origin/main` contains the deployed compose, `api/`, `scripts/generate-config.sh`, `app/nginx.conf`, `landing/entrypoint.sh` and `web/src`. Without this step nothing below can help: `docker-compose.yml` is byte-identical between `HEAD` and `origin/main`, and the running API is not in either.
2. **[commit]** Fix `README.md:63` to clone `--branch main`; `feat/secure-storage-pilot` no longer exists on `origin`.
3. **[.env]** Provision the target `.env` (never committed) with the names the compose requires: `APP_DOMAIN`, `S3_DOMAIN`, `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, `AURA_API_ADMIN_PASSWORD`, `DASHBOARD_DOMAIN`, `DASHBOARD_AUTH` (bcrypt), `DASHBOARD_ALLOWED_IPS`, `DOCS_AUTH` (bcrypt), `SWAGGER_ADMIN_IP`, plus the bootstrap `S3_ACCESS_KEY`/`S3_SECRET_KEY`.
4. **[.env]** Add `S3_API_ACCESS_KEY`/`S3_API_SECRET_KEY` as a **distinct** pair (Read/Write/List, no Admin). `generate-config.sh` aborts if they equal the bootstrap keys.
5. **[.env]** `AURA_SESSION_TTL=28800` — optional once step 1 is committed (compose default is already 28800), and **useless** before it (row 1 literal).
6. **[.env]** `AURA_TRUSTED_PROXIES=127.0.0.1/32,::1/128,172.30.0.0/24,172.31.0.0/24,172.32.0.0/24` — belt-and-braces; do not copy `.env.example:190`.
7. **[verify]** Regenerate `config/seaweedfs/s3.json` with `scripts/generate-config.sh` (invoked by `bootstrap.sh`) and confirm the `aura-api` identity has non-empty, bootstrap-distinct credentials.
8. **[verify]** Deploy with `scripts/deploy.sh` — it builds `web/dist` (git-ignored), runs `docker compose build`, `up -d --wait`, then restarts `traefik`. A plain `git clone && docker compose up -d` builds no frontend bundle and does not rebuild `aura-api:local`.
9. **[verify]** After boot: `docker inspect aura-001-api` → `ReadonlyRootfs=true`, `CapDrop=["ALL"]`, `Memory=2147483648`, `NanoCpus=2000000000`, env `AURA_SESSION_TTL=28800`; `docker network inspect` → the three 172.30/31/32 subnets; `HEAD https://$S3_DOMAIN/` → 200 landing; `/api/v1/admin/objects/{oid}/reverify` present in OpenAPI.

---

## 6. What this audit did not check

- **No rebuild was performed.** Every "deployed" value comes from `docker inspect` on the live containers, not from a clone.
- **Traefik label placement (row 10) is static.** The claim that Traefik v3.7 ignores labels on its own container is taken from the working-tree comment and was not reproduced; doing so needs a throwaway compose project. Confirmed only: `HEAD` declares the middlewares on `traefik`, the working tree on `app`, and the running `aura-001-traefik` carries just `traefik.enable` and `traefik.docker.network`.
- **`.env` was not read**, by policy. So I cannot say whether `AURA_TRUSTED_PROXIES`, `AURA_SESSION_TTL` or `S3_ACCESS_KEY` are explicitly set there, nor which of the two branches in trap 2 applies. Row 2's consequence is therefore conditional on `.env`.
- **No network clone was made.** The clone state was modelled with `git diff origin/main` and `git rev-parse` against the local remote-tracking ref; `origin/main` may have moved since the last fetch.
- **Not verified:** actually-served HTTP headers (HSTS, dashboard 401, docs BasicAuth), `web/dist` byte-for-byte reproducibility, Postgres data/migrations, SeaweedFS volume contents, ACME/TLS state, DNS and firewall, backup/restore, image digests vs a fresh `docker compose build`.
- **Not audited:** the four modified test files' coverage, and whether the 11 untracked files are complete (e.g. `web/src/lib/csv.test.ts` exists but the runner wiring was not inspected).
