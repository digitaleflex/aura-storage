# AURA frontend — neutral scaffold (issue #20)

App shell with visual direction A applied (« Coffre Linear »).
Stack: Vite + TypeScript (strict) + TanStack Router + TanStack Query,
minimal house CSS (no Tailwind), Playwright for e2e.

## What it does

- `POST /api/v1/login` with username/password; session travels in the
  HttpOnly `aura_session` cookie, CSRF token kept in memory only and sent as
  `x-csrf-token` on mutations.
- Protected `/` route: a folder-aware file browser (breadcrumb, logical folder
  CRUD, object list / upload / download / soft-delete / purge), public `/login`
  route.
- Administration console at `/admin` (roles `operator`/`admin`): dashboard
  counters (`/api/v1/admin/stats`) and registries for applications, spaces and
  machine-to-machine identities. The nav entry and the route are hidden/refused
  for a plain `user`; the API stays authoritative. With `admin:write` (the
  `admin` role) the console also creates applications/spaces/identities, rotates
  and revokes identity tokens, and runs the expired-upload reconciliation. An
  identity token is displayed exactly once (creation or rotation) and never
  re-read.
- Typed API client (`src/lib/api.ts`): list objects (optionally filtered by
  folder), logical folder CRUD, upload intent → PUT to the short-lived URL →
  commit, download intent → open short-lived GET URL, soft-delete, purge, and
  the administration mutations.
- The UI never shows fake data as real: empty catalogue renders an explicit
  empty state, errors render explicit alerts.
- No S3 keys in the code or bundle. All calls use relative paths; in dev,
  Vite proxies `/api` and `/health` to the API below.

## Dev

```bash
cd web
npm install
npm run dev      # http://127.0.0.1:5173 only (strictPort)
```

The dev server proxies to `http://127.0.0.1:8081` (override with
`AURA_API_PROXY` only for local use).

## Build

```bash
npm run build    # tsc --noEmit + vite build -> web/dist/
npm run preview  # serves web/dist on 127.0.0.1:5173
```

## E2E smoke

Needs two local servers. The API runs with an in-memory catalogue and dummy
S3 credentials; a rejected login never contacts S3.

`e2e/login.spec.ts` checks that a wrong password is rejected.
`e2e/admin.spec.ts` checks that `/admin` requires auth and that an `admin`
login reaches the console with its write controls.
`e2e/admin-mutations.spec.ts` creates an application, space and identity,
asserts the token is shown once, then revokes it.
`e2e/folders.spec.ts` creates, renames, opens and deletes a folder.
(All use the local admin password below.)

```bash
# Terminal 1 — API (from repo root; values are throwaway local-only secrets)
AURA_API_ADMIN_PASSWORD=local-smoke-test-password \
AURA_S3_ACCESS_KEY=dummy AURA_S3_SECRET_KEY=dummy \
AURA_API_DB=':memory:' AURA_COOKIE_SECURE=0 \
  .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8081 --workers 1

# Terminal 2 — frontend
cd web && npm run dev

# Terminal 3 — smoke test
cd web && npx playwright test
```

On minimal hosts without system browser libraries (no GTK/ATK/fonts), the
Playwright Chromium needs user-local libraries — no root required:

```bash
# one-time: fetch Ubuntu libs + DejaVu fonts into /tmp/opencode/pwlibs
# (see exact package list in the issue report) then run tests with:
export LD_LIBRARY_PATH=/tmp/opencode/pwlibs/root/usr/lib/x86_64-linux-gnu
export FONTCONFIG_FILE=/tmp/opencode/pwlibs/fontconf/fonts.conf
npx playwright test
```

## Limits

- CSRF token lives in memory: a page reload requires logging in again even
  though the session cookie is still valid.
- Uploads rely on the server's default space bucket (the client no longer
  hard-codes `aura`); a folder can be chosen as the upload target.
- The folder tree is loaded breadth-first from the per-level list endpoint
  (bounded to 500 nodes); there is no single "list all folders" route.
- Production serving (static `dist/` + same-origin `/api` proxy) is a
  deployment concern and is not configured here.
