# AURA frontend — neutral scaffold (issue #20)

Neutral app shell, no definitive visual direction (direction A to follow).
Stack: Vite + TypeScript (strict) + TanStack Router + TanStack Query,
minimal house CSS (no Tailwind), Playwright for e2e.

## What it does

- `POST /api/v1/login` with username/password; session travels in the
  HttpOnly `aura_session` cookie, CSRF token kept in memory only and sent as
  `x-csrf-token` on mutations.
- Protected `/` route (object list + upload), public `/login` route.
- Typed API client (`src/lib/api.ts`): list objects, upload intent → PUT to
  the short-lived URL → commit, download intent → open short-lived GET URL.
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

## E2E smoke (login KO rejected)

Needs two local servers. The API runs with an in-memory catalogue and dummy
S3 credentials; a rejected login never contacts S3.

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
- Uploads use a fixed `aura` bucket; folder selection is not implemented.
- Production serving (static `dist/` + same-origin `/api` proxy) is a
  deployment concern and is not configured here.
- Board/product wording and visual direction are intentionally not applied.
