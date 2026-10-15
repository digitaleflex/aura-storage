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