"""Opt-in PostgreSQL pool test (#325); skipped unless AURA_TEST_PG_DSN is set.

Use a disposable database: this module only reads (`SELECT pg_backend_pid()`)
and never mutates catalogue rows. It checks that concurrent catalogue access
stays inside the configured limits and that exhaustion is bounded by the
acquisition timeout, never by an unbounded hang.
"""
import concurrent.futures
import os
import time

import pytest

DSN = os.environ.get("AURA_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="AURA_TEST_PG_DSN not set")


def _repo(max_size=6, timeout=2.0, min_size=2):
    pytest.importorskip("psycopg_pool")
    from api.db_pg import Repository
    return Repository(DSN, pool_min=min_size, pool_max=max_size, pool_timeout=timeout)


def test_concurrent_reads_stay_within_pool_limits():
    repo = _repo()
    try:
        def read(_):
            return int(repo._one("SELECT pg_backend_pid() AS pid")["pid"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
            pids = list(workers.map(read, range(120)))
        metrics = repo.pool_metrics()
        assert len(set(pids)) <= metrics["max"]
        assert metrics["acquisitions"] >= 120
        assert metrics["timeouts"] == 0
        assert metrics["size"] <= metrics["max"]
        assert metrics["avg_acquire_ms"] >= 0
    finally:
        repo.close_pool()
        repo.conn.close()


def test_small_pool_exhaustion_is_bounded_by_timeout():
    repo = _repo(max_size=1, timeout=0.1, min_size=1)
    try:
        def hold(_):
            try:
                with repo._connection():
                    time.sleep(0.3)
                return "ok"
            except Exception as exc:
                return type(exc).__name__

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as workers:
            outcomes = list(workers.map(hold, range(6)))
        assert outcomes.count("ok") == 1
        assert outcomes.count("PoolTimeout") == 5
        assert repo.pool_metrics()["timeouts"] == 5
        # The pool recovers: a later call still works after the timeouts.
        assert repo._one("SELECT 1 AS ok")["ok"] == 1
    finally:
        repo.close_pool()
        repo.conn.close()
