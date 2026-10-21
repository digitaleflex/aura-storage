# Architecture Decisions

## ADR-001 — Independent storage service (Accepted)

AURA is operated independently from OpenBooks, Axiom and Azure. Applications consume an S3-compatible interface; ordinary file access does not require the control plane.

## ADR-002 — Single VPS first (Accepted for MVP)

Begin with one VPS to control complexity. This is not high availability. Independent backups and a tested restore are mandatory before importing production data.

## ADR-003 — SeaweedFS candidate (Proposed; verify)

Validate release maturity, S3 API compatibility, data layout, security, upgrades and resource use before committing production content.

## ADR-004 — Separate data and control planes (Accepted)

Normal object requests use the S3 interface. Future management integration can observe health/capacity and perform restricted operations, but Axiom must not be required for normal data access.

## ADR-005 — One catalogue connection, serialized in-process (Accepted for MVP)

The catalogue keeps a single connection per process (SQLite in dev/test, psycopg on
the pilot). FastAPI runs sync endpoints in a worker threadpool, so the repository
serializes every operation with a per-instance re-entrant lock (`api/dblock.py`).

- Reason: neither `sqlite3` nor `psycopg` supports concurrent use of one
  connection; interleaving produced `sqlite3.InterfaceError: bad parameter or
  other API misuse` and transient 401/500 responses (see `tests/test_db_concurrency.py`).
- Trade-off: database access is one operation at a time. Acceptable for a
  single-worker pilot where the data plane (S3) carries the bytes.
- Follow-up at scale: replace the lock with a real connection pool; the decorator
  is the only thing to remove, method bodies stay unchanged. Multiple uvicorn
  workers already each get their own connection and lock.
  Measured 2026-10-18 (local PostgreSQL 16, one uvicorn worker, 20 concurrent
  clients, authenticated object listing): the global lock serves ~210 req/s; a
  psycopg_pool prototype (one connection + transaction per repository call)
  served ~125 req/s, ~175-210 req/s without the per-borrow health check and in
  autocommit. The lock is not the bottleneck at pilot scale (CPU-bound Python
  in one process is), so the pool was not adopted. Revisit with a remote
  database or several workers (which first needs shared rate-limiter state).

## ADR-006 — Proprietary license, private API-only deployment (Accepted)

AURA is licensed as proprietary software, all rights reserved (`LICENSE`). It is
operated for its owner on a private VPS. External services consume it only
through its HTTP/S3 API; they never receive, link or embed AURA's source. The
repository is not a distribution of reusable code, and no open-source rights are
granted.

- Reason: an outbound license only governs what others may do with the code. It
  has no effect on integrations, which depend on *how* a component is used
  (separate unmodified service vs in-tree import). A permissive license such as
  Apache-2.0 would grant reuse rights the owner does not intend to grant.
- Reason: nothing is distributed, so no copyleft obligation is triggered for
  AURA's own code. AGPL/GPL components may still be run as separate, unmodified
  services (ClamAV planned; MinIO/Garage/SFTPGo explicitly out of scope).
- Constraint: no AGPL-3.0 code may enter the repository. If a component must be
  patched, ADR-006 must be revisited before that patch is committed.
- Consequence: while the owner is the sole copyright holder, no CLA is needed.
  Any external contributor must sign a written copyright assignment, otherwise
  their contribution cannot be relicensed later.
- Revisit if: AURA is distributed, offered to third parties, opened to external
  contributors, or a component must be modified in-tree. The easiest pivot at
  that point is Apache-2.0 (patent grant, permissive) or AGPL-3.0 (network
  copyleft) — see `docs/engineering/issues-2026-10-18/N9-license.md`.
