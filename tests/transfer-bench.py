#!/usr/bin/env python3
"""Transfer benchmark harness for the AURA transfer engine (C4)."""
import argparse
import hashlib
import http.cookiejar
import json
import os
import ssl
import time
import urllib.request

API = os.environ.get("AURA_API_BASE", "http://127.0.0.1:8000")
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
_CJ = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX), urllib.request.HTTPCookieProcessor(_CJ))


def login():
    req = urllib.request.Request(
        f"{API}/api/v1/login",
        data=json.dumps({"username": "admin",
                         "password": os.environ["AURA_API_ADMIN_PASSWORD"]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _OPENER.open(req) as r:
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
    with _OPENER.open(req) as r:
        return json.loads(r.read())


def run_one(size, csrf):
    data = os.urandom(size)
    digest = hashlib.sha256(data).hexdigest()
    t0 = time.perf_counter()
    meta = intent(csrf, size)
    t_intent = time.perf_counter() - t0
    put_req = urllib.request.Request(meta["upload_url"], data=data, method="PUT",
                                    headers=meta.get("headers", {}))
    t1 = time.perf_counter()
    with urllib.request.urlopen(put_req, context=_SSL_CTX):
        pass
    t_put = time.perf_counter() - t1
    t2 = time.perf_counter()
    creq = urllib.request.Request(
        f"{API}/api/v1/objects/{meta['id']}/commit",
        data=b"", headers={"X-CSRF-Token": csrf}, method="POST",
    )
    with _OPENER.open(creq) as r:
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
