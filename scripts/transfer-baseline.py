#!/usr/bin/env python3
"""Read-only summary of how uploads behave, from logs you already have.

Nothing here talks to the pilot: save the logs to files, then run

    docker logs aura-001-api  > api.log 2>&1
    docker logs aura-001-traefik > traefik.log 2>&1
    python3 scripts/transfer-baseline.py --api-log api.log --traefik-log traefik.log

and keep the output next to the date and the version that was deployed, before
and after a change. It reports:

* commit re-read cost: ``commit timings`` lines (api/main.py) bucketed by size,
  p50/p95 of ``hash_ms`` and ``total_ms``, and the effective re-read MiB/s;
* uploads killed by the proxy: PUT requests answered 499/502/504 or lasting at
  least ``--cut-seconds`` (Traefik ``readTimeout`` is 1200 s);
* storage throttling: ``SlowDown`` / ``Throttling`` / ``ThrottlingException``
  in the API log (a shared adaptive retry limiter slows every worker after one).
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter

COMMIT_RE = re.compile(
    r"commit timings oid=(?P<oid>\S+) bytes=(?P<bytes>\d+) "
    r"head_ms=(?P<head>[\d.]+) hash_ms=(?P<hash>[\d.]+) total_ms=(?P<total>[\d.]+)"
)
# Traefik common log format: ... "PUT /path HTTP/2.0" 200 123 "-" "-" 42 "router" "url" 1234ms
TRAEFIK_RE = re.compile(
    r'"(?P<method>[A-Z]+) (?P<path>\S+) [^"]*" (?P<status>\d{3}) .*? (?P<ms>\d+)ms\s*$'
)
THROTTLE_RE = re.compile(r"SlowDown|Throttling(Exception)?|RequestLimitExceeded", re.I)

MIB = 1024 * 1024
BUCKETS = [(0, 1 * MIB, "< 1 MiB"), (1 * MIB, 32 * MIB, "1-32 MiB"),
           (32 * MIB, 256 * MIB, "32-256 MiB"), (256 * MIB, float("inf"), ">= 256 MiB")]


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize_commits(lines) -> dict:
    rows = []
    for line in lines:
        m = COMMIT_RE.search(line)
        if m:
            rows.append((int(m["bytes"]), float(m["hash"]), float(m["total"])))
    out = {"count": len(rows), "buckets": []}
    for lo, hi, label in BUCKETS:
        sel = [r for r in rows if lo <= r[0] < hi]
        if not sel:
            continue
        hashes = [r[1] for r in sel]
        totals = [r[2] for r in sel]
        seconds = sum(h for h in hashes) / 1000.0
        rate = (sum(r[0] for r in sel) / MIB) / seconds if seconds > 0 else 0.0
        out["buckets"].append({
            "label": label, "n": len(sel),
            "hash_p50_ms": _pct(hashes, 0.5), "hash_p95_ms": _pct(hashes, 0.95),
            "total_p50_ms": _pct(totals, 0.5), "total_p95_ms": _pct(totals, 0.95),
            "reread_mib_s": rate,
        })
    return out


def summarize_proxy(lines, cut_seconds: float) -> dict:
    puts = 0
    cut = []
    statuses: Counter = Counter()
    durations = []
    for line in lines:
        m = TRAEFIK_RE.search(line)
        if not m or m["method"] != "PUT":
            continue
        puts += 1
        status = int(m["status"])
        seconds = int(m["ms"]) / 1000.0
        statuses[status] += 1
        durations.append(seconds)
        if status in (499, 502, 504) or seconds >= cut_seconds:
            cut.append((m["path"].split("?")[0], status, seconds))
    return {
        "puts": puts, "statuses": dict(statuses), "cut": cut,
        "duration_p50_s": statistics.median(durations) if durations else 0.0,
        "duration_max_s": max(durations) if durations else 0.0,
    }


def count_throttling(lines) -> int:
    return sum(1 for line in lines if THROTTLE_RE.search(line))


def render(commits: dict | None, proxy: dict | None, throttled: int | None, cut_seconds: float) -> str:
    out = []
    if commits is not None:
        out.append(f"== Commit re-read ({commits['count']} commits)")
        if not commits["buckets"]:
            out.append("  no 'commit timings' line found")
        for b in commits["buckets"]:
            out.append(
                f"  {b['label']:<11} n={b['n']:<5} hash p50={b['hash_p50_ms']:.0f} ms "
                f"p95={b['hash_p95_ms']:.0f} ms | total p95={b['total_p95_ms']:.0f} ms | "
                f"re-read {b['reread_mib_s']:.1f} MiB/s"
            )
    if proxy is not None:
        out.append(f"== Proxy PUTs ({proxy['puts']})")
        out.append(f"  statuses: {proxy['statuses']}")
        out.append(f"  duration p50={proxy['duration_p50_s']:.1f}s max={proxy['duration_max_s']:.1f}s")
        out.append(f"  cut or >= {cut_seconds:.0f}s: {len(proxy['cut'])}")
        for path, status, seconds in proxy["cut"][:10]:
            out.append(f"    {status} after {seconds:.0f}s  {path}")
    if throttled is not None:
        out.append(f"== Storage throttling lines: {throttled}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api-log")
    ap.add_argument("--traefik-log")
    ap.add_argument("--cut-seconds", type=float, default=1100.0)
    args = ap.parse_args(argv)
    if not args.api_log and not args.traefik_log:
        ap.error("give --api-log and/or --traefik-log")
    commits = proxy = throttled = None
    if args.api_log:
        with open(args.api_log, encoding="utf-8", errors="replace") as fh:
            api_lines = fh.readlines()
        commits = summarize_commits(api_lines)
        throttled = count_throttling(api_lines)
    if args.traefik_log:
        with open(args.traefik_log, encoding="utf-8", errors="replace") as fh:
            proxy = summarize_proxy(fh.readlines(), args.cut_seconds)
    print(render(commits, proxy, throttled, args.cut_seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
