# Third-party components

AURA Storage itself is proprietary (see `LICENSE`). It uses, runs or will use
the components below. Each remains under its own license; nothing in the AURA
license alters those terms.

Two integration modes matter for license obligations:

- **Separate service** — a container/process AURA talks to over HTTP, S3 or a
  Unix socket, unmodified. No copyleft obligation flows into AURA's own code.
- **In-tree dependency** — an imported library, bundled asset or copied source
  file. That component's license applies to the resulting work.

## Runtime dependencies (in-tree)

| Component | Version (pinned) | License | Obligation |
|---|---|---|---|
| FastAPI | 0.143.1 | MIT | Keep copyright notice |
| Uvicorn | 0.54.0 | BSD-3-Clause | Keep copyright notice |
| boto3 / botocore | 1.43.113 | Apache-2.0 | Keep notice; `NOTICE` if present |
| argon2-cffi | 25.1.0 | MIT | Keep copyright notice |
| psycopg | 3.3.6 | LGPL-3.0 | Dynamic use only; do not vendor or modify in-tree |
| psycopg-binary | 3.3.6 | LGPL-3.0 (+ libpq, PostgreSQL License) | Same as psycopg |

## Frontend dependencies (in-tree, `web/package.json`)

| Component | License | Obligation |
|---|---|---|
| React, React DOM | MIT | Keep copyright notice |
| @tanstack/react-query, @tanstack/react-router | MIT | Keep copyright notice |
| Vite, @vitejs/plugin-react | MIT | Keep copyright notice |
| TypeScript | Apache-2.0 | Keep notice |
| Playwright (@playwright/test) | Apache-2.0 | Keep notice; test tooling only |

## Infrastructure (separate services, unmodified)

| Component | License | Mode | Obligation |
|---|---|---|---|
| SeaweedFS | Apache-2.0 | Container; S3 + filer API | Attribution in this file only |
| Traefik | MIT | Container; reverse proxy | Attribution only |
| PostgreSQL | PostgreSQL License | Container; catalogue | Attribution only |
| Swagger UI | Apache-2.0 | Container | Attribution only |

## Planned components (not integrated yet)

| Component | License | Intended mode | Constraint |
|---|---|---|---|
| ClamAV | GPL-2.0 | Separate sidecar, scanned over `clamd` socket | Never link `libclamav` into `api/` |
| restic | BSD-2-Clause | Separate binary for backups | None |
| rclone | MIT | Separate binary for offsite copy | None |
| Authelia | Apache-2.0 | Separate container in front of Traefik | None |
| Casbin (pycasbin) | Apache-2.0 | In-tree library | Keep notice |

## Explicitly out of scope

AGPL-3.0 components (MinIO, Garage, SFTPGo, Nextcloud, Seafile, Pydio) must
never be copied, imported or modified inside this repository. They may only be
run as separate, unmodified services. If that ever changes, the license
decision in `docs/DECISIONS.md` (ADR-006) must be revisited first.

## Verification

Versions above match `api/requirements.txt` and `web/package.json` at the time
of writing. Re-check them whenever dependencies are bumped; container tags are
set through `.env` (`TRAEFIK_IMAGE`, `SEAWEEDFS_IMAGE`, `POSTGRES_IMAGE`) and
are not pinned in Git.
