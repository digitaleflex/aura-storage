# AURA frontend — neutral scaffold (issue #20)

App shell with visual direction A applied (« Coffre Linear »).
Stack: Vite + TypeScript (strict) + TanStack Router + TanStack Query,
minimal house CSS (no Tailwind), Playwright for e2e.

## What it does

- `POST /api/v1/login` with username/password; session travels in the
  HttpOnly `aura_session` cookie, CSRF token kept in memory only and sent as
  `x-csrf-token` on mutations.
- Protected `/` route: a folder-aware file browser (breadcrumb, logical folder
  CRUD, object list with pagination, search/filter/sort, upload / download /
  file-in-folder / soft-delete / purge, and an object details panel), public
  `/login` route.
- Administration console at `/admin` (roles `operator`/`admin`): dashboard
  counters (`/api/v1/admin/stats`) and registries for applications, spaces,
  buckets and machine-to-machine identities. The nav entry and the route are
  hidden/refused for a plain `user`; the API stays authoritative. With
  `admin:write` (the `admin` role) the console also creates applications and
  spaces, renames or activates/deactivates them, registers buckets and sets their
  default, creates identities, rotates and revokes identity tokens, and runs the
  expired-upload reconciliation. A space cannot be moved to another application,
  nothing is deleted through the API, and no bucket payload ever carries an S3
  credential. An identity token is displayed exactly once (creation or rotation)
  and never re-read.
- Typed API client (`src/lib/api.ts`): list objects with server-side search,
  filters, sort and paging (name substring, status, MIME type, size range,
  creation period), logical folder CRUD, upload intent → PUT to the short-lived
  URL → commit, download intent → open short-lived GET URL, file/unfile an
  object into a folder, soft-delete, purge, and the administration mutations.
- Uploads run through the M03 transfer engine (`src/lib/transfer.ts`): real XHR
  upload progress, explicit phases (autorisation → envoi → vérification
  d'intégrité → disponible), bounded retries with exponential backoff + jitter,
  automatic recovery from an expired presigned URL, an accidental-double-submit
  guard backed by an `Idempotency-Key`, and cancellation that calls the backend
  `abort` endpoint. Success is shown only after the backend confirms the commit.
  The queue runs **4 files at once by default** and backs off on congestion; a
  failing commit is retried on its own (the file is not re-sent); a file waiting
  for the server's integrity check (`202 verifying`) releases its upload slot.
  See [Vault transfer engine](../docs/TRANSFER-ENGINE.md).
- Import tray (`src/components/UploadTray.tsx`, memoised): one sentence per file
  on what is happening, step duration, a one-line breakdown, a per-file detail
  view (step timeline, object id, server SHA-256), a filter and a 100-row cap on
  batches above 30 files, throughput over a 20 s sliding window, pause/resume,
  retry of failed files while the import runs, and confirmation before stopping.
  Progress-only updates are coalesced to one per 250 ms.
- Inline preview (`PreviewModal`): images (PNG/JPEG/GIF/WebP/AVIF), PDF, audio,
  **video** (MP4/WebM/OGG in a `<video>` player) and the **text family** — plain
  text, Markdown, JSON (indented), CSV/TSV (table, 200 rows × 30 columns at most).
  Text is read with `fetch` (first 256 KiB only, then the transfer is cancelled) and
  rendered as escaped text; if the browser cannot read the storage URL it falls back
  to a sandboxed frame. HTML, SVG, XML and scripts are never previewed (they would
  run in the storage origin). Word/Excel/PowerPoint have no preview: download only.
  The server allow-list is `PREVIEWABLE_CONTENT_TYPES` in `api/main.py`
  (mirrored in `src/lib/preview.ts`).
- Files page: a vault overview (space used vs capacity, verified files, files
  awaiting validation, per-file size limit — real catalogue figures only), a
  ledger with file-type tiles and status pills, a welcoming empty state, and a
  branded French error page for render failures (`src/components/RouteError.tsx`).
  The administration console groups its sections into panels and shows the
  supervision lines in French (`src/lib/adminText.ts`).
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

See also [Local validation](../docs/LOCAL-VALIDATION.md) for the full pre-push checklist (API, PostgreSQL, web, shell).

## Layout of the shared code

- `src/lib/transfer.ts` — upload engine and queue (no React; every side effect is
  injected, so it is tested in a Playwright worker, no browser).
- `src/lib/cascade.ts` — recursive folder deletion plan (leaves first, the target
  last), with its own unit tests.
- `src/lib/throughput.ts`, `src/lib/adminText.ts` — small pure helpers.
- `src/components/` — `UploadTray`, `FileDetail`, `VaultOverview`, `Elapsed`,
  `RouteError`, dialogs, toasts, layout.
- `src/DESIGN-SYSTEM.md` — tokens and rules; every new colour pair must exist in
  both themes.

## E2E smoke

Needs two local servers. The API runs with an in-memory catalogue and dummy
S3 credentials; a rejected login never contacts S3.

`e2e/login.spec.ts` checks that a wrong password is rejected.
`e2e/admin.spec.ts` checks that `/admin` requires auth and that an `admin`
login reaches the console with its write controls.
`e2e/admin-mutations.spec.ts` creates an application, space and identity,
asserts the token is shown once, then revokes it.
`e2e/admin-management.spec.ts` renames, deactivates/reactivates an application,
re-environments a space, registers a bucket and makes it the default.
`e2e/folders.spec.ts` creates, renames, opens and deletes a folder.
`e2e/transfer-engine.spec.ts` unit-tests the upload state machine (retry,
expiry, cancellation, never-fake-success); it needs no browser or servers.
`e2e/upload-flow.spec.ts` mocks the API and the presigned endpoint to check
progress/phase display, the double-submit guard, server-error surfacing,
expired-URL recovery and real cancellation.
`e2e/ui-keyboard-a11y.spec.ts` mocks the API to check the `?` legend, `/` and
`Suppr` shortcuts, row-menu Arrow/Escape focus handling and the mobile drawer's
focus trap.
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
- The folder tree is loaded in a single request (`GET /api/v1/folders?all=true`,
  flat list rebuilt client-side from `parent_id`).
- The object table is paged (50 per page, "Charger plus" increments `offset`).
  Search, filters (status, MIME type, size range, creation period) and sort run
  **server-side** over the whole catalogue (`GET /api/v1/objects`, M02), so the
  UI never loads every object to answer a query. `q` is a display-name substring
  and never matches the internal object key.
- The object details panel shows only fields the API exposes (name, id, MIME
  type, exact/readable size, status, folder, `created_at`/`updated_at`, SHA-256).
  The logical storage key, bucket, space and application are **not** returned by
  the catalogue API; the panel says so instead of inventing values.
- A pending object has `size_bytes = -1` until its upload is committed, so it
  renders as "taille inconnue" and is excluded by any `min_size`/`max_size`
  filter. That is faithful to the catalogue, not a UI bug.
- Filing an object into a folder uses `PATCH /api/v1/objects/{id}`; folders are
  human-owned, so a machine identity cannot file objects.
- Zero-byte uploads are refused unless the API sets `AURA_ALLOW_EMPTY_OBJECTS=1`;
  the allowed media types are enforced server-side (`AURA_ALLOWED_CONTENT_TYPES`),
  not by the file picker.
- Cancellation is offered only because the backend has `POST /api/v1/objects/{id}/abort`.
  Retries are bounded (3 attempts, exponential backoff with jitter) and an expired
  presigned URL is re-issued at most twice per transfer.
- The e2e suite (~136 tests) runs against mocked or local servers. The CI
  workflow `web.yml` only runs `npm ci` and `npm run build`, so Playwright and the
  visual-regression snapshots (`e2e/visual-regression.spec.ts-snapshots`) are
  **not** enforced there; regenerate the snapshots with
  `npx playwright test e2e/visual-regression.spec.ts --update-snapshots` on the
  machine whose rendering you want as the baseline (they are stale after the
  2026-10-22 design pass).
- Production serving (static `dist/` + same-origin `/api` proxy) is a
  deployment concern and is not configured here.
