#!/usr/bin/env python3
"""Measure the PostgreSQL catalogue pool under concurrent load (#325).

    python3 scripts/db-pool-load-test.py \
        'postgresql://aura:secret@127.0.0.1:5432/aura_ci' \
        --threads 24 --ops 60 --min 2 --max 10 --timeout 5

The DSN must point to a **disposable** database. The script only reads
(`SELECT 1`, `pg_backend_pid`) and prints aggregate figures: no credentials,
row contents or local identifiers leave the process. An optional `--exhaust`
run uses a tiny pool and a short timeout to verify failures stay bounded.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db_pg import Repository  # noqa: E402


def open_cost(dsn: str, samples: int) -> float:
    import psycopg
    durations = []
    for _ in range(samples):
        t0 = time.perf_counter()
        conn = psycopg.connect(dsn, autocommit=True)
        conn.close()
        durations.append((time.perf_counter() - t0) * 1000)
    return statistics.median(durations)


def worker(repo: Repository, ops: int) -> tuple[int, set[int], list[str]]:
    pids: set[int] = set()
    errors: list[str] = []
    for _ in range(ops):
        try:
            row = repo._one("SELECT pg_backend_pid() AS pid")
            pids.add(int(row["pid"]))
        except Exception as exc:  # bounded: recorded, never printed verbatim
            errors.append(type(exc).__name__)
    return ops, pids, errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dsn", help="DSN of a disposable PostgreSQL database")
    ap.add_argument("--threads", type=int, default=24)
    ap.add_argument("--ops", type=int, default=60)
    ap.add_argument("--min", dest="pool_min", type=int, default=2)
    ap.add_argument("--max", dest="pool_max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--exhaust", action="store_true", help="also run a deliberately tiny pool")
    args = ap.parse_args()

    repo = Repository(args.dsn, pool_min=args.pool_min, pool_max=args.pool_max,
                      pool_timeout=args.timeout)
    try:
        before = repo.pool_metrics()
        median_open_ms = open_cost(args.dsn, 10)
        t0 = time.perf_counter()
        all_pids: set[int] = set()
        errors: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as pool:
            for count, pids, errs in pool.map(
                lambda _: worker(repo, args.ops), range(args.threads)
            ):
                all_pids.update(pids)
                errors.extend(errs)
        elapsed = time.perf_counter() - t0
        after = repo.pool_metrics()
        total = args.threads * args.ops
        print(f"load: threads={args.threads} ops={total} elapsed_s={elapsed:.2f} "
              f"ops_per_s={total / elapsed:.0f}")
        print(f"backend_pids_used={len(all_pids)} (pool max={args.pool_max}, "
              f"plus 1 legacy connection)")
        print(f"errors={len(errors)} types={sorted(set(errors))}")
        print(f"pool_before={before}")
        print(f"pool_after={after}")
        print(f"median_raw_connect_ms={median_open_ms:.1f} "
              f"avg_pool_acquire_ms={after['avg_acquire_ms']}")
        if errors or after["size"] > args.pool_max:
            print("RESULT FAIL")
            return 1
        print("RESULT PASS")
    finally:
        repo.close_pool()
        repo.conn.close()

    if args.exhaust:
        tiny = Repository(args.dsn, pool_min=1, pool_max=2, pool_timeout=0.2)
        try:
            def hold(_):
                try:
                    with tiny._connection():
                        time.sleep(0.5)
                    return "ok"
                except Exception as exc:
                    return type(exc).__name__
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                outcomes = list(pool.map(hold, range(12)))
            print(f"bounded_exhaustion: {dict((k, outcomes.count(k)) for k in set(outcomes))} "
                  f"metrics={tiny.pool_metrics()}")
        finally:
            tiny.close_pool()
            tiny.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
