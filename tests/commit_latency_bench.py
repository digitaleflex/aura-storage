#!/usr/bin/env python3
"""Commit-latency benchmark for the AURA transfer engine (COMMIT-LATENCY-01).

Measures the **hidden** cost between "the browser's PUT finished" and "the object
is ``available``". That window is what users experience as
"the upload finished but the file stays pending for ages".

Every phase mirrors the real code path; nothing here is a guess:

  a) ``PUT``  : one ``put_object`` with ``ServerSideEncryption='AES256'`` —
                the same request a presigned single PUT performs
                (``api/s3.py:47-79``, SSE is signed into the URL).
  b) ``HEAD`` : ``head_object`` — exactly what the commit handler does first
                (``api/main.py:679``).
  c) ``REHASH``: ``get_object(...)["Body"]`` then
                ``iter_chunks(chunk_size=1048576)`` feeding ``hashlib.sha256()``
                — an exact emulation of ``api/main.py:700-704`` and
                ``api/s3.py:135-149`` (``stream_sha256``), with the default
                ``AURA_COMMIT_CHUNK_BYTES`` = 1 MiB (``api/config.py:89``).
                The object is never buffered whole in memory.

Derived numbers:

  ``commit_ratio``   = rehash_s / put_s
  ``hidden_seconds`` = head_ms/1000 + rehash_s

i.e. how long the object stays non-``available`` after the PUT has ended.

Isolation contract (see ``tests/commit-latency-bench.sh``): this client is only
ever pointed at the ephemeral ``bench-commit-*`` stack. It never reads the pilot
``.env`` and never prints credentials.

Exit code 0 when the run completed; non-zero only on a hard error (no size could
be measured at all). Per-size failures are reported as ``UNKNOWN``/``ERROR`` and
keep the run going.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    import boto3
    from botocore.client import Config
except Exception as exc:  # pragma: no cover - dependency guard
    print(f"ERROR: boto3 is required ({exc}). Use .venv/bin/python.", file=sys.stderr)
    raise SystemExit(2)

TEST_ID = "COMMIT-LATENCY-01"
CHUNK_DEFAULT = 1048576  # api/config.py:89 AURA_COMMIT_CHUNK_BYTES default
BLOCK = bytes(range(256)) * 4096  # 1 MiB deterministic, non-trivial payload

UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# streaming payload — never materialise the whole object on the client
# --------------------------------------------------------------------------- #
class BlockReader:
    """Deterministic, rewindable, streaming body of ``total`` bytes."""

    def __init__(self, total: int):
        self._total = total
        self._pos = 0

    def read(self, amt: int = -1) -> bytes:
        if amt is None or amt < 0:
            amt = min(self._total - self._pos, len(BLOCK))
        n = min(int(amt), self._total - self._pos)
        if n <= 0:
            return b""
        self._pos += n
        if n <= len(BLOCK):
            return BLOCK[:n]
        return BLOCK * (n // len(BLOCK)) + BLOCK[: n % len(BLOCK)]

    def tell(self) -> int:
        return self._pos

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        else:
            self._pos = self._total + pos
        return self._pos


class Timed:
    def __init__(self):
        self.t0 = time.perf_counter()

    def done(self) -> float:
        return time.perf_counter() - self.t0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def parse_sizes(text: str) -> list[int]:
    """``8,64,256`` (MiB) or ``8M,256M,1G`` -> sorted unique MiB list."""
    out: list[int] = []
    for raw in text.split(","):
        tok = raw.strip()
        if not tok:
            continue
        mult = 1
        num = tok
        for suffix, factor in (("GIB", 1024), ("MIB", 1), ("KIB", 1 / 1024),
                               ("GB", 1024), ("MB", 1), ("KB", 1 / 1024),
                               ("G", 1024), ("M", 1), ("K", 1 / 1024),
                               ("B", 1 / (1024 * 1024))):
            if tok.upper().endswith(suffix):
                num = tok[: len(tok) - len(suffix)]
                mult = factor
                break
        value = float(num) * mult
        if value < 1:
            raise ValueError(f"size {tok!r} is below 1 MiB (single-PUT bench domain)")
        out.append(int(round(value)))
    if not out:
        raise ValueError("no sizes given")
    return sorted(set(out))


def fmt(value, spec: str = ".3f") -> str:
    if value is None:
        return UNKNOWN
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return UNKNOWN


def make_client(endpoint: str, ak: str, sk: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={
                "addressing_style": "path",
                # The app uploads via a PRESIGNED url, and presigned S3 URLs use
                # UNSIGNED-PAYLOAD. Signing the body here would make the client
                # read (and SHA-256) every byte twice, inflating put_s with pure
                # client CPU. The server-visible request is otherwise identical.
                "payload_signing_enabled": False,
            },
            request_checksum_calculation="when_required",
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


def docker(*args: str) -> str:
    """Run docker directly, falling back to ``sg docker -c`` (host group setup)."""
    try:
        res = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    try:
        cmd = "docker " + " ".join("'%s'" % a.replace("'", "'\\''") for a in args)
        res = subprocess.run(["sg", "docker", "-c", cmd], capture_output=True,
                             text=True, timeout=30)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def fingerprint(workdir: str) -> dict:
    image_id = docker("image", "inspect", "chrislusf/seaweedfs:4.48", "--format", "{{.Id}}")
    digest = docker("image", "inspect", "chrislusf/seaweedfs:4.48",
                    "--format", "{{range .RepoDigests}}{{.}}{{end}}")
    df = {}
    try:
        usage = shutil.disk_usage(workdir)
        df = {"path": workdir, "total_mib": round(usage.total / 2**20, 1),
              "free_mib": round(usage.free / 2**20, 1)}
    except OSError:
        df = {"path": workdir, UNKNOWN: True}
    try:
        loadavg = list(os.getloadavg())
    except OSError:
        loadavg = None
    import platform
    return {
        "image": "chrislusf/seaweedfs:4.48",
        "image_id": image_id or UNKNOWN,
        "image_digest": digest or UNKNOWN,
        "nproc": os.cpu_count(),
        "df_workdir": df,
        "loadavg_at_start": loadavg,
        "python": platform.python_version(),
        "boto3": getattr(boto3, "__version__", UNKNOWN),
        "host": platform.node(),
        "kernel": platform.release(),
    }


def free_mib(path: str) -> float | None:
    try:
        return shutil.disk_usage(path).free / 2**20
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# measurement phases
# --------------------------------------------------------------------------- #
def put_once(client, bucket: str, key: str, size_bytes: int) -> float:
    """(a) single streaming PUT with SSE-S3 AES256; returns seconds."""
    timer = Timed()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=BlockReader(size_bytes),
        ContentLength=size_bytes,
        ContentType="application/octet-stream",
        ServerSideEncryption="AES256",
    )
    return timer.done()


def head_latency(client, bucket: str, key: str, samples: int = 3) -> tuple:
    """(b) head_object latency in ms: (median_ms, all_ms, sse_algorithm)."""
    values: list[float] = []
    sse = None
    for _ in range(samples):
        timer = Timed()
        resp = client.head_object(Bucket=bucket, Key=key)
        values.append(timer.done() * 1000.0)
        sse = resp.get("ServerSideEncryption", "")
    values_sorted = sorted(values)
    median = values_sorted[len(values_sorted) // 2]
    return median, values, sse


def rehash_once(client, bucket: str, key: str, chunk_bytes: int) -> tuple:
    """(c) exact emulation of api/main.py:700-704 (+ api/s3.py stream_sha256).

    ``get_object`` body -> ``iter_chunks(1 MiB)`` -> incremental sha256.
    Returns (seconds, total_bytes, hex_digest).
    """
    timer = Timed()
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    digest = hashlib.sha256()
    total = 0
    try:
        for chunk in body.iter_chunks(chunk_size=chunk_bytes):
            total += len(chunk)
            digest.update(chunk)
    finally:
        body.close()
    return timer.done(), total, digest.hexdigest()


def conc_puts(client, bucket: str, keys: list[str], size_bytes: int) -> dict:
    """N parallel PUTs started as simultaneously as threads allow."""
    durations: list[float] = []
    errors: list[str] = []
    barrier = threading.Barrier(len(keys))
    started = threading.Event()

    def worker(key: str) -> None:
        try:
            barrier.wait(timeout=60)
        except Exception:
            pass
        started.set()
        try:
            durations.append(put_once(client, bucket, key, size_bytes))
        except Exception as exc:  # keep the other threads meaningful
            errors.append(f"{type(exc).__name__}: {exc}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futures = [pool.submit(worker, k) for k in keys]
        started.wait(timeout=60)
        for fut in futures:
            fut.result()
    wall = time.perf_counter() - t0
    return {"wall_s": wall, "durations": sorted(durations), "errors": errors,
            "started_event": started}


def rehash_under_load(client, bucket: str, key: str, chunk_bytes: int,
                      load_keys: list[str], size_bytes: int) -> dict:
    """(e) one rehash while N PUTs are running — contention proof."""
    inflight = {"count": 0}
    lock = threading.Lock()
    done_puts: list[float] = []
    errors: list[str] = []
    barrier = threading.Barrier(len(load_keys))
    started = threading.Event()
    stop_after_rehash = threading.Event()

    def worker(k: str) -> None:
        try:
            barrier.wait(timeout=60)
        except Exception:
            pass
        started.set()
        try:
            done_puts.append(put_once(client, bucket, k, size_bytes))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            with lock:
                inflight["count"] -= 1

    with lock:
        inflight["count"] = len(load_keys)
    with ThreadPoolExecutor(max_workers=len(load_keys)) as pool:
        futures = [pool.submit(worker, k) for k in load_keys]
        started.wait(timeout=60)
        rehash_s, total, digest = rehash_once(client, bucket, key, chunk_bytes)
        stop_after_rehash.set()
        in_flight_at_end = inflight["count"]
        for fut in futures:
            fut.result()

    return {
        "rehash_s": rehash_s,
        "rehash_bytes": total,
        "rehash_digest_prefix": digest[:16],
        "puts_ok": len(done_puts),
        "put_errors": errors,
        "puts_still_running_when_rehash_ended": max(in_flight_at_end, 0),
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def print_table(rows: list[dict], chunk_bytes: int, concurrency: int) -> None:
    header = (f"{'size':>9} | {'put_s':>8} | {'put MiB/s':>9} | {'head_ms':>8} | "
              f"{'rehash_s':>8} | {'rh MiB/s':>8} | {'ratio':>6} | {'hidden_s':>8} | state")
    print()
    print(f"=== COMMIT-LATENCY-01 — commit cost after the PUT ends "
          f"(chunk={chunk_bytes} B, concurrency={concurrency}) ===")
    print(header)
    print("-" * len(header))
    for r in rows:
        size = f"{r['size_mib']} MiB"
        print(f"{size:>9} | {fmt(r['put_s'], '.3f'):>8} | {fmt(r['put_mb_s'], '.1f'):>9} | "
              f"{fmt(r['head_ms'], '.1f'):>8} | {fmt(r['rehash_s'], '.3f'):>8} | "
              f"{fmt(r['rehash_mb_s'], '.1f'):>8} | {fmt(r['commit_ratio'], '.2f'):>6} | "
              f"{fmt(r['hidden_seconds'], '.3f'):>8} | {r['status']}")
    print()
    print("ratio = rehash_s / put_s ; hidden_s = head_ms/1000 + rehash_s "
          "(time the object is not `available` after the PUT returns)")


def print_concurrency(rows: list[dict]) -> None:
    if not rows:
        return
    header = (f"{'size':>9} | {'N':>2} | {'put wall_s':>10} | {'agg MiB/s':>9} | "
              f"{'rehash_s':>8} | {'base_s':>7} | {'got/exp':>8} | {'in-flight@end':>13} | state")
    print()
    print("=== concurrency run: N parallel PUTs, then one rehash while N PUTs run ===")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['size_mib']:>7} MiB | {r['n']:>2} | {fmt(r['put_wall_s'], '.3f'):>10} | "
              f"{fmt(r['put_mb_s_agg'], '.1f'):>9} | {fmt(r['rehash_loaded_s'], '.3f'):>8} | "
              f"{fmt(r['rehash_baseline_s'], '.3f'):>7} | "
              f"{fmt(r['slowdown_got'], '.2f'):>8} | "
              f"{str(r['puts_in_flight_at_rehash_end']):>13} | {r['status']}")
    print()
    print("got/exp = rehash_s under N parallel PUTs / rehash_s when idle "
          "(expected 1.00 with no contention)")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description=f"{TEST_ID}: measure put / head / commit-rehash cost against "
                    "an ISOLATED SeaweedFS stack.")
    ap.add_argument("--endpoint", required=True, help="e.g. http://127.0.0.1:49123")
    ap.add_argument("--bucket", default=None,
                    help="bucket to use (created if missing); default bench-<hex>")
    ap.add_argument("--sizes", default="8,64,256",
                    help="comma list; bare numbers are MiB, or use 8M,256M,1G")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="N parallel PUTs + rehash-under-load probe (default 1 = off)")
    ap.add_argument("--chunk-bytes", type=int, default=CHUNK_DEFAULT,
                    help=f"commit rehash chunk size (default {CHUNK_DEFAULT} = "
                         "AURA_COMMIT_CHUNK_BYTES)")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="write raw numbers + fingerprint to this path")
    ap.add_argument("--workdir", default=os.getcwd(),
                    help="ephemeral data dir, used only for the df fingerprint")
    ap.add_argument("--keep-objects", action="store_true",
                    help="do not delete benchmark objects after each size")
    args = ap.parse_args()

    ak = os.environ.get("S3_ACCESS_KEY", "")
    sk = os.environ.get("S3_SECRET_KEY", "")
    if not ak or not sk:
        print("ERROR: S3_ACCESS_KEY / S3_SECRET_KEY must be set (wrapper does this).",
              file=sys.stderr)
        return 2

    try:
        sizes = parse_sizes(args.sizes)
    except ValueError as exc:
        print(f"ERROR: bad --sizes: {exc}", file=sys.stderr)
        return 2

    concurrency = max(1, int(args.concurrency))
    chunk_bytes = max(64 * 1024, int(args.chunk_bytes))
    bucket = args.bucket or ("bench-" + hashlib.sha256(os.urandom(16)).hexdigest()[:12])
    run_token = hashlib.sha256(os.urandom(16)).hexdigest()[:10]

    print(f"[{TEST_ID}] endpoint={args.endpoint} bucket={bucket} "
          f"sizes={sizes} MiB chunk={chunk_bytes} concurrency={concurrency}")
    print(f"[{TEST_ID}] workdir={args.workdir}")

    fp = fingerprint(args.workdir)
    print(f"[{TEST_ID}] image_id={fp['image_id']} nproc={fp['nproc']} "
          f"free={fp['df_workdir'].get('free_mib', UNKNOWN)} MiB")

    client = make_client(args.endpoint, ak, sk)

    hard_error = None
    try:
        try:
            client.head_bucket(Bucket=bucket)
        except Exception:
            client.create_bucket(Bucket=bucket)
    except Exception as exc:
        print(f"ERROR: cannot reach/use S3 gateway: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    rows: list[dict] = []
    conc_rows: list[dict] = []
    keys_to_delete: list[str] = []

    avail = free_mib(args.workdir)
    for size_mib in sizes:
        size_bytes = size_mib * 1024 * 1024
        key = f"bench/{run_token}/{size_mib}m.bin"
        row = {
            "size_mib": size_mib,
            "size_bytes": size_bytes,
            "key": key,
            "put_s": None,
            "put_mb_s": None,
            "head_ms": None,
            "head_samples_ms": [],
            "sse": UNKNOWN,
            "rehash_s": None,
            "rehash_mb_s": None,
            "rehash_bytes": None,
            "commit_ratio": None,
            "hidden_seconds": None,
            "status": "OK",
            "error": None,
        }

        # Disk guard: this stack writes every object twice (replicated volume
        # data + filer metadata), so require 3x headroom before starting.
        needed_mib = size_bytes / 2**20 * concurrency * 3
        if avail is not None and avail < needed_mib:
            row["status"] = "SKIPPED"
            row["error"] = (f"free disk {avail:.0f} MiB < {needed_mib:.0f} MiB "
                            f"needed (3x headroom)")
            print(f"[{TEST_ID}] skip {size_mib} MiB: {row['error']}")
            rows.append(row)
            continue

        try:
            # phase order per size: put -> head -> rehash
            row["put_s"] = put_once(client, bucket, key, size_bytes)
            row["put_mb_s"] = size_mib / row["put_s"] if row["put_s"] else None
            keys_to_delete.append(key)

            median_ms, all_ms, sse = head_latency(client, bucket, key)
            row["head_ms"] = median_ms
            row["head_samples_ms"] = all_ms
            row["sse"] = sse or "none"

            rehash_s, total, _digest = rehash_once(client, bucket, key, chunk_bytes)
            row["rehash_s"] = rehash_s
            row["rehash_mb_s"] = (total / 2**20) / rehash_s if rehash_s else None
            row["rehash_bytes"] = total
            if row["put_s"]:
                row["commit_ratio"] = rehash_s / row["put_s"]
            row["hidden_seconds"] = median_ms / 1000.0 + rehash_s

            notes = []
            if total != size_bytes:
                notes.append(f"rehash read {total} B != {size_bytes} B")
            if row["sse"] != "AES256":
                notes.append(f"SSE={row['sse']}")
            if notes:
                row["status"] = "WARN"
                row["error"] = "; ".join(notes)
        except Exception as exc:
            row["status"] = "ERROR"
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[{TEST_ID}] {size_mib} MiB failed in phase: {row['error']}")

        rows.append(row)
        avail = free_mib(args.workdir)

        # ---- optional contention probe for this size
        if concurrency > 1 and row["rehash_s"] is not None:
            try:
                load_keys = [f"bench/{run_token}/{size_mib}m-c{i}.bin"
                             for i in range(concurrency)]
                conc = conc_puts(client, bucket, load_keys, size_bytes)
                keys_to_delete.extend(load_keys)
                load_keys2 = [f"bench/{run_token}/{size_mib}m-d{i}.bin"
                              for i in range(concurrency)]
                loaded = rehash_under_load(client, bucket, key, chunk_bytes,
                                           load_keys2, size_bytes)
                keys_to_delete.extend(load_keys2)
                put_wall = conc["wall_s"]
                c_row = {
                    "size_mib": size_mib,
                    "n": concurrency,
                    "put_wall_s": put_wall,
                    "put_mb_s_agg": (size_mib * concurrency / put_wall) if put_wall else None,
                    "put_durations_s": conc["durations"],
                    "put_errors": conc["errors"],
                    "rehash_loaded_s": loaded["rehash_s"],
                    "rehash_baseline_s": row["rehash_s"],
                    "slowdown_got": (loaded["rehash_s"] / row["rehash_s"]
                                     if row["rehash_s"] else None),
                    "slowdown_expected": 1.0,
                    "puts_in_flight_at_rehash_end":
                        loaded["puts_still_running_when_rehash_ended"],
                    "rehash_under_load_errors": loaded["put_errors"],
                    "status": "OK",
                }
                if conc["errors"] or loaded["puts_ok"] < concurrency:
                    c_row["status"] = "WARN"
                conc_rows.append(c_row)
            except Exception as exc:
                conc_rows.append({
                    "size_mib": size_mib, "n": concurrency, "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            avail = free_mib(args.workdir)

        if not args.keep_objects:
            try:
                for k in keys_to_delete:
                    client.delete_object(Bucket=bucket, Key=k)
                keys_to_delete.clear()
            except Exception:
                keys_to_delete.clear()

    if not args.keep_objects:
        for k in keys_to_delete:
            try:
                client.delete_object(Bucket=bucket, Key=k)
            except Exception:
                pass
        if bucket.startswith("bench-"):
            try:
                client.delete_bucket(Bucket=bucket)
            except Exception:
                pass

    print_table(rows, chunk_bytes, concurrency)
    print_concurrency(conc_rows)

    measured = [r for r in rows if r["put_s"] is not None]
    print(f"[{TEST_ID}] sizes attempted={len(rows)} measured={len(measured)}")
    if not measured:
        hard_error = "no size could be measured (see errors above)"

    payload = {
        "test_id": TEST_ID,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": args.endpoint,
        "bucket": bucket,
        "chunk_bytes": chunk_bytes,
        "concurrency": concurrency,
        "sizes_mib": sizes,
        "rows": rows,
        "concurrency_rows": conc_rows,
        "fingerprint": fp,
        "hard_error": hard_error,
    }
    if args.json_path:
        try:
            with open(args.json_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            print(f"[{TEST_ID}] raw numbers written to {args.json_path}")
        except OSError as exc:
            print(f"WARNING: could not write --json {args.json_path}: {exc}",
                  file=sys.stderr)

    if hard_error:
        print(f"ERROR: {hard_error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
