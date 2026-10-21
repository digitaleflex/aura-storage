#!/usr/bin/env python3
"""Transfer benchmark harness for the AURA transfer engine (C4).

Runs against a live (or local) SeaweedFS endpoint and reports throughput and
commit latency for a matrix of object sizes and connection counts. Output is
JSON on stdout plus a Markdown table on stderr.

Usage:
    AURA_API_BASE=http://127.0.0.1:8000 \\
    AURA_API_ADMIN_PASSWORD=... AURA_S3_ENDPOINT=... \\
    python3 tests/transfer-bench.py [--sizes 1,10,100] [--conns 1,4] [--out baseline.json]

This script is NOT run in CI: it needs a real storage backend. It is the
evidence base for any future tuning decision (G11).
"""
import argparse
import hashlib
import json
import os
import time
import urllib.request

API = os.environ.get("AURA_API_BASE", "http://127.0.0.1:8000")


def login():
    req = urllib.request.Request(
        f"{API}/api/v1/login",
        data=json.dumps({"username": "admin",
                         "password": os.environ["AURA_API_ADMIN_PASSWORD"]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        body = json.loads(r.read())
    return body["csrf_token"]


def intent(csrf, size):
    req = urllib.request.Request(
        f"{API}/api/v1/objects/upload-intents",
        data=json.dumps({"bucket": "aura", "display_name": f"bench-{size}.bin",
                         "content_type": "application/octet-stream",
                         "size_bytes": size}).encode(),
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def run_one(size, csrf):
    data = os.urandom(size)
    digest = hashlib.sha256(data).hexdigest()
    t0 = time.perf_counter()
    meta = intent(csrf, size)
    t_intent = time.perf_counter() - t0
    # PUT (single request) — bytes never traverse the API.
    put_req = urllib.request.Request(meta["upload_url"], data=data, method="PUT",
                                    headers=meta.get("headers", {}))
    t1 = time.perf_counter()
    with urllib.request.urlopen(put_req):
        pass
    t_put = time.perf_counter() - t1
    # commit
    t2 = time.perf_counter()
    creq = urllib.request.Request(
        f"{API}/api/v1/objects/{meta['id']}/commit",
        data=b"", headers={"X-CSRF-Token": csrf}, method="POST",
    )
    with urllib.request.urlopen(creq) as r:
        cbody = json.loads(r.read())
    t_commit = time.perf_counter() - t2
    assert cbody["checksum_sha256"] == digest
    total = time.perf_counter() - t0
    return {
        "size_bytes": size,
        "intent_s": round(t_intent, 4),
        "put_s": round(t_put, 4),
        "commit_s": round(t_commit, 4),
        "total_s": round(total, 4),
        "throughput_mib_s": round((size / (1024 * 1024)) / total, 3) if total else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1048576,10485760,104857600")
    ap.add_argument("--conns", default="1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    sizes = [int(x) for x in args.sizes.split(",")]
    csrf = login()
    results = []
    for size in sizes:
        r = run_one(size, csrf)
        results.append(r)
        print(json.dumps(r))
    table = "| size (MiB) | put (s) | commit (s) | total (s) | MiB/s |\n|---|---|---|---|---|\n"
    for r in results:
        table += f"| {r['size_bytes']/(1024*1024):.1f} | {r['put_s']} | {r['commit_s']} | {r['total_s']} | {r['throughput_mib_s']} |\n"
    import sys
    print(table, file=sys.stderr)
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"results": results, "generated_at": time.time()}, f, indent=2)


if __name__ == "__main__":
    main()
PY
chmod +x tests/transfer-bench.py && echo created