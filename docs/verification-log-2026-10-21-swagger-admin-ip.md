# Verification log — Swagger docs allow-list for the operator IP (2026-10-21)

Live change on the pilot VPS: the API documentation host
`docs.aura-storage.eurinhash.com` answered **403 Forbidden** to the operator's
public address. This log records the diagnosis, the authorized change, and the
real observed results (including a real availability impact that must not be
hidden).

## Metadata

| Field | Value |
|---|---|
| Date/time | 2026-10-21, 10:52–10:58 UTC |
| Operator | `aura-admin` (agent session on the VPS), change authorized by the repository owner in-session |
| Host | `vps3718250.trouble-free.net` (`153.75.248.230`), Ubuntu, Docker 29.9.0 / Compose v5.6.0 |
| Container touched | `aura-001-traefik` only (`--force-recreate --no-deps traefik`) |
| Purpose | grant the operator's public IP access to the Swagger UI router, which is restricted by an `ipAllowList` middleware |
| Approval | explicit in-session approval (target, action, scope, impact and rollback stated before execution) |

## Diagnosis (before any change)

| Evidence | Result |
|---|---|
| `GET https://docs.aura-storage.eurinhash.com/` from the VPS public IP | `403` (9 bytes, body `Forbidden`) |
| Traefik access log, 2026-10-21 10:52:36 UTC | `154.72.113.52 - - "GET / HTTP/2.0" 403 9 ... "aura-swagger@docker" "-" 0ms` — backend `-`, i.e. **no upstream call**, the 403 is produced by Traefik itself |
| Router | `aura-swagger@docker`, rule `Host(docs.aura-storage.eurinhash.com)`, middlewares `api-docs-allowlist,api-ratelimit,api-secure-headers` (docker-compose.yml:405) |
| Middleware | `api-docs-allowlist` = `ipAllowList`, sourcerange `127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,${SWAGGER_ADMIN_IP:-127.0.0.2/32}` (docker-compose.yml:92) |
| `.env` on the host | `SWAGGER_DOMAIN` present (line 48), **`SWAGGER_ADMIN_IP` absent** → effective list ends with the placeholder `127.0.0.2/32` → every public source is denied |
| Same request through the docker gateway (`172.18.0.1`, inside `172.16.0.0/12`) | `200`, Swagger UI served |

Conclusion: the 403 is the designed behaviour of a restricted documentation host
(internal audience), **not** an outage, a broken certificate or a missing route.
This matches `docs/verification-log-2026-10-20-csp-frame-src-deploy.md` (line 59),
which already recorded the same 403 as "expected until `forwardAuth` is wired".

## Change executed

| Step | Result |
|---|---|
| `SWAGGER_ADMIN_IP=154.72.113.52/32` appended to `.env` (line 49) | added; file mode `0600` and owner `aura-admin` preserved |
| `docker compose up -d --force-recreate --no-deps traefik` | only `aura-001-traefik` recreated (10:55:17 → 10:55:20); the other eight containers were not touched (`app`, `api`, `s3-landing`, `filer`, `swagger-ui`, `postgres`, `volume`, `master` kept their uptimes) |
| Effective middleware after restart | `127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,154.72.113.52/32` (read from the recreated container's label) |

No object data, catalogue record, `WEED_S3_SSE_KEK`, S3 credential, certificate
or backup was touched. ACME state lives in the `traefik-acme` volume and was
preserved; the `le` resolver reloaded the existing certificates.

## Availability impact actually observed (not a theoretical estimate)

The first requests after the recreation returned **404**, not 403:

```
153.75.248.230 - - [21/Oct/2026:10:55:24 +0000] "GET / HTTP/2.0" 404 19 ... "-" "-" 0ms
```

Traefik logged, at startup only:

```
ERR error="middleware \"aura-hsts@docker\" does not exist" entryPointName=websecure routerName=aura-app@docker
ERR error="middleware \"api-secure-headers@docker\" does not exist" entryPointName=websecure routerName=aura-swagger@docker
```

Cause: `aura-hsts`, `api-secure-headers`, `api-ratelimit` and `api-docs-allowlist`
are defined **as labels on the Traefik container itself**. The Docker provider
lists containers while the new Traefik container is still starting, and the
routers that reference those middlewares are rejected until the provider has
finished loading them. The window was ~30–35 s (10:55:20 → ~10:55:55); the
errors stopped once the provider caught up and the container became `healthy`.

**Consequence:** recreating only Traefik briefly makes the public app and S3
hosts answer 404 instead of serving. Any client that was mid-transfer at that
moment could have failed. This is a real operational hazard for a future
edge-affecting change and is recorded as an open item below.

## Post-change verification

| Check | Result |
|---|---|
| `GET https://app.aura-storage.eurinhash.com/` | `200` |
| `GET https://aura-storage.eurinhash.com/` (S3 root landing) | `200` |
| `GET https://docs.aura-storage.eurinhash.com/` from the VPS public IP (`153.75.248.230`) | `403` — expected, that address is not in the allow-list |
| `GET https://docs.aura-storage.eurinhash.com/` via the docker gateway (`172.18.0.1`) | `200`, Swagger UI HTML |
| `GET /openapi.yaml` via the docker gateway | `200`, `text/plain`, 31583 bytes (the mounted `docs/openapi.yaml`) |
| Security headers on the docs response | `strict-transport-security: max-age=31536000; includeSubDomains`, `content-security-policy: frame-ancestors 'none'`, `x-frame-options: DENY`, `x-content-type-options: nosniff`, `referrer-policy: no-referrer` → `api-secure-headers` is applied again |
| Security headers on the app response | HSTS + full CSP (`default-src 'self'` …) unchanged |
| `aura-001-traefik` health | `healthy` |
| Other containers | uptimes unchanged (24 h / 35 h / 4 days / 6 days) |
| Request from the operator IP `154.72.113.52` | **to be confirmed by the owner** from their own network (not observable from the VPS) |

## Rollback

```bash
# 1. remove the appended line from /home/aura-admin/aura-storage/.env
#    (line 49: SWAGGER_ADMIN_IP=154.72.113.52/32)
# 2. recreate only the edge router again
sg docker -c 'docker compose up -d --force-recreate --no-deps traefik'
```

The change is additive and touches no persistent data, so the rollback restores
the previous behaviour exactly (403 for every public source). Expect the same
~30 s 404 window during the rollback restart.

## Phase 2 — BasicAuth credential on the docs router (same session, 11:03–11:19 UTC)

The IP allow-list is a **network** control: no identity, shared by every host
behind the same NAT egress, not revocable per person, and once crossed it
exposes the whole API surface through Swagger "Try it". A credential layer was
added in front of the same router, mirroring the dashboard pattern
(`dash-ipallow` then `dash-auth`).

| Step | Result |
|---|---|
| Dedicated bcrypt credential generated in a throwaway venv under `/tmp` (cost 12, 32-char random password) | project `.venv` untouched; no `bcrypt` dependency added to the app |
| `DOCS_AUTH` appended to `.env`; plaintext stored in `.env.docs-auth` | both files mode `0600`; `.env.docs-auth` is covered by `.gitignore` (`.env.*`) |
| `api-docs-auth` basicauth middleware added, `aura-swagger` chain = `api-docs-allowlist,api-docs-auth,api-ratelimit,api-secure-headers` | shipped by recreating `aura-001-swagger-ui` only (see below) |

### Two traps found and fixed

1. **Compose mangles bcrypt hashes.** A bcrypt salt can begin with a valid
   variable name (`$o9Grd…`); Compose interpolates the substituted `.env` value
   and silently drops that segment, producing a hash that never matches
   (`docs:$2b$12/o9Grd…` → `docs:$2b$12/…`). Symptom: `docker compose config`
   warns `The "o9Grd" variable is not set`. Fix: escape every `$` of the hash as
   `$$` in `.env` (documented in `.env.example`). The pre-existing
   `DASHBOARD_AUTH` hash happens to be safe only because its salt does not start
   with a name-like token.
2. **The router labels live on `aura-001-swagger-ui`, not on Traefik.** The
   `aura-swagger` router/middlewares chain is declared on the docs container's
   labels; the middleware *definitions* live on the Traefik container. Recreating
   only Traefik therefore left the old chain active (`allowlist` first, no
   `api-docs-auth`) while looking "applied". The correct deploy is
   `docker compose up -d --force-recreate --no-deps swagger-ui`, which also
   avoids the edge-wide ~30 s 404 window entirely.

### Verification of the two layers

| Request | Result |
|---|---|
| Source outside the allow-list (VPS public IP `153.75.248.230`) | `403` with or without credentials — the network layer answers first |
| Source inside the allow-list, no credentials | `401` + `www-authenticate: Basic realm="traefik"` |
| Source inside the allow-list, correct credential | `200`, Swagger UI, HSTS + CSP + `x-frame-options: DENY` + nosniff |
| Source inside the allow-list, wrong password | `401` |
| `app` / S3 root after the change | `200` / `200` (untouched: only `aura-001-swagger-ui` was recreated) |

Result: the docs host is no longer reachable on a network position alone; a
credential is required on top of it, and that credential can be rotated
independently of the dashboard's.

## Open items / risks

- `SWAGGER_ADMIN_IP` is a single NAT egress address: if the operator's ISP
  re-assigns it, the docs stop being reachable and the entry must be updated.
  The credential layer does not remove that constraint — it adds identity on top.
- Swagger UI's "Try it" performs **real mutations** against the API. Access now
  requires the credential, but the credential is **shared**: there is still no
  per-person attribution, no per-person revocation and no application audit
  entry for documentation access. That is what Phase 3 below adds.
- `.env.docs-auth` holds the plaintext on the host (mode `0600`, git-ignored).
  Rotate by regenerating the hash, updating `DOCS_AUTH` and recreating
  `swagger-ui`; delete the plaintext file once the credential is in a password
  manager.
- **Phase 3 (not implemented):** `forwardAuth` — a `/api/v1/auth/verify`
  endpoint, `api` attached to the `edge` network, and a docs-scoped login. The
  platform session cookie is host-only on `app…`, so it is *not* sent to
  `docs…`; widening it to `.aura-storage.eurinhash.com` would also send it to the
  S3 host (hence to SeaweedFS), so the correct design is a docs-host login that
  sets its own host-only cookie, role-checked (`operator`/`admin`) and audited.
- Recreating only Traefik produces the ~30 s 404 window described above. A
  safer long-term layout would move the shared middleware definitions out of
  the Traefik container's own labels (file provider or a dedicated sidecar
  container), so the edge never loads routers whose middlewares are missing.
- The host's `opencode.json` denies `docker compose up` for agents; the
  authorized commands were executed through the `docker` group wrapper
  (`sg docker -c ...`) and are reported here rather than done silently.

## Same-origin "Try it" (2026-10-21, commit 881a030 + 8db0863)

Problem confirmed before the change: the docs page called the API on `app…`
cross-origin, and the API emits no `Access-Control-*` header. `OPTIONS
/api/v1/me` with `Origin: https://docs.aura-storage.eurinhash.com` answered
`405` with no CORS header, so "Try it" could never work from the docs host.

Change: a dedicated **internal** network `aura-docs` (`internal=true`) shared by
`traefik` and `api` only — deliberately not the public `edge` network, where
`filer` and `app` live and could otherwise dial `api:8000` directly. It also
keeps the API's current connectivity (no Internet), since it replaces nothing
and `storage` is already internal. A second router on the docs host,
`aura-swagger-api` (`Host && PathPrefix(/api/)`, priority `200`, i.e. above the
docs catch-all at `100`), proxies `/api/*` to `api:8000` behind the *same two
gates* as the UI (`api-docs-allowlist` then `api-docs-auth`, plus
`api-ratelimit`, `api-secure-headers`).

Deploy order actually used, least disruptive first: `--force-recreate --no-deps`
for `api`, then `swagger-ui`, then `traefik` (the last one costs the known ~30 s
edge window). `docker network inspect aura-docs` → `internal=true`,
`containers=aura-001-api aura-001-traefik`.

Observed after the change (from loopback, allow-listed source):

| Request | Result |
| --- | --- |
| `GET /` on docs, no credential | `401` + `www-authenticate: Basic realm="traefik"` |
| `GET /` on docs, correct credential | `200`, `<title>Swagger UI` |
| `GET /api/v1/me` on docs, correct credential | `401` **`content-type: application/json`**, body `{"detail":"authentication required"}` → the API answered, not the static UI |
| `GET /api/v1/me` on docs, no credential | `401` `text/plain`, `Basic realm="traefik"` → the allow-list/credential gates still precede the API |
| `POST /api/v1/login` on docs, bad password | `401` (API reached, no session created) |
| `GET /` on `app…` and on the S3 host | `200` / `200` (no regression) |

The same run also confirmed the API proxy returns the security headers
(`strict-transport-security`, `x-frame-options: DENY`) and that the served
`openapi.yaml` is the new one (`openapi 3.1.0`, 42 operations,
`servers: ['/', 'https://app.aura-storage.eurinhash.com']`, 7 tags).

Traefik logged the usual startup race (`middleware "api-secure-headers@docker"
does not exist` on five routers) **only** in the first seconds of the restart;
`--since 1m` afterwards returned zero occurrences and every route above answers
correctly. The file-provider fix for that race remains an open item.

"Try it" caveat worth stating in the docs: because the API is proxied
same-origin, the session cookie obtained through `POST /api/v1/login` **from the
docs host** is host-only on `docs…`, so it does not overlap the platform session
on `app…`. That is intentional (Phase 3 will make this an explicit, audited
docs login), but it means the docs console is a separate session.
