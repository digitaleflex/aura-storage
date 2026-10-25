#!/usr/bin/env python3
"""Presigned multipart part PUT through the EDGE PROXY (Traefik) — plan gate item 6.

Companion of ``tests/multipart-proxy-4.48.sh`` (which starts an EPHEMERAL,
isolated SeaweedFS 4.48 stack plus TWO Traefik instances in front of the S3
gateway). It must never be pointed at the pilot stack.

What this proves:
  A. A 5 MiB presigned UploadPart PUT, throttled client-side to a slow rate,
     SUCCEEDS through Traefik configured exactly like production
     (``respondingTimeouts.readTimeout=7200s``). The part ETag must equal the
     local MD5 of the exact bytes sent: that proves the proxy delivered the
     whole body, not a truncated prefix.
  B. NEGATIVE CONTROL: the same upload through a second Traefik entrypoint that
     keeps the DEFAULT readTimeout (60s) is CUT OFF (~60s, non-200 / reset).
     This is what makes the harness able to catch a regression.
  C. Sizing arithmetic for the configured part sizes against the documented
     proxy deadline.
  Plus two browser-facing diagnostics: ``Expect: 100-continue`` and a CORS
  preflight, both through the proxy.

Design notes:
  * The control plane uses boto3 configured like ``api/s3.py`` (SigV4,
    path-style); the part body is then sent with a plain socket, i.e. what a
    browser does, NOT an SDK.
  * ``s3.test`` is resolved to 127.0.0.1 (Traefik's published loopback port) by
    overriding ``socket.getaddrinfo``. The URL, and therefore the signed
    ``Host`` header, keeps ``s3.test:<port>`` — no /etc/hosts edit, no root.
  * No secret and no full presigned URL is ever printed (path + query keys only).
  * No ``tc``, no root, no multi-GB fixture: throttling is client-side pacing.

Exit code 0 iff A passes, B is cut off, C is safe and no probe failed.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import select
import socket
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

KIB = 1024
MIB = 1024 * 1024
DEFAULT_READ_TIMEOUT_S = 7200
TRAEFIK_DEFAULT_READ_TIMEOUT_S = 60

PROXY_HOST = "s3.test"

_failures = 0
_unknowns = 0
_blocking_unknowns = 0
_passes = 0


# ---------------------------------------------------------------------------
# logging helpers (same vocabulary as the compat client)
# ---------------------------------------------------------------------------
def line(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def ok(msg: str) -> None:
    global _passes
    _passes += 1
    line("PASS", msg)


def fail(msg: str) -> None:
    global _failures
    _failures += 1
    line("FAIL", msg)


def unknown(msg: str, blocking: bool = False) -> None:
    global _unknowns, _blocking_unknowns
    _unknowns += 1
    if blocking:
        _blocking_unknowns += 1
    line("UNKNOWN", msg)


def info(msg: str) -> None:
    line("INFO", msg)


def evidence(msg: str) -> None:
    line("EVIDENCE", msg)


def safe_url(url: str) -> str:
    """Path + sorted query keys, never values (presigned sigs are secrets)."""
    p = urlparse(url)
    keys = ",".join(sorted(parse_qs(p.query)))
    return f"{p.scheme}://{p.netloc}{p.path}?<{keys}>"


def err_detail(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        e = exc.response.get("Error", {})
        return (f"Code={e.get('Code')!r} Message={e.get('Message')!r} "
                f"HTTPStatus={exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')}")
    return f"{type(exc).__name__}: {exc}"


def norm_etag(raw: str | None) -> str:
    return (raw or "").strip().strip('"')


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# DNS override: s3.test -> 127.0.0.1, port untouched
# ---------------------------------------------------------------------------
def install_dns_override(proxy_host: str) -> None:
    original = socket.getaddrinfo

    def patched(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == proxy_host:
            host = "127.0.0.1"
        return original(host, port, *args, **kwargs)

    socket.getaddrinfo = patched  # type: ignore[assignment]
    info(f"DNS override installed: {proxy_host} -> 127.0.0.1 (URL/Host stays "
         f"{proxy_host}:<port>, so the SigV4 signed host is unchanged)")


# ---------------------------------------------------------------------------
# S3 control plane (same shape as tests/multipart_compat_client.py)
# ---------------------------------------------------------------------------
def make_client(endpoint: str, ak: str, sk: str):
    return boto3.client(
        "s3", endpoint_url=endpoint,
        aws_access_key_id=ak, aws_secret_access_key=sk, region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def presign_part(client, bucket: str, key: str, uid: str, part: int) -> str:
    return client.generate_presigned_url(
        "upload_part",
        Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": part},
        ExpiresIn=3600)


# ---------------------------------------------------------------------------
# Throttled plain-socket PUT (what a browser XHR does)
# ---------------------------------------------------------------------------
def throttled_put(url: str, body: bytes, rate_kbps: int,
                  timeout: float = 300.0) -> dict:
    """PUT ``body`` at ~rate_kbps KiB/s, detecting an early proxy response.

    Pacing is a simple token schedule: after each chunk, wait until
    sent/rate bytes-per-second has elapsed. select() on the socket during that
    wait notices a proxy that answers/closes before the body ends (the whole
    point of the negative control).
    """
    p = urlparse(url)
    host, port = p.hostname, (p.port or 80)
    target = p.path or "/"
    if p.query:
        target += "?" + p.query

    rate_bps = max(1, int(rate_kbps)) * KIB
    chunk_size = max(KIB, rate_bps // 10)  # ~10 writes per second

    result = {
        "url": safe_url(url), "rate_kbps": rate_kbps, "chunk_size": chunk_size,
        "expected_seconds": len(body) / rate_bps, "sent": 0,
        "status": None, "headers": {}, "body": b"", "error": None,
        "early_response": False, "elapsed": None,
    }

    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    started = time.monotonic()
    try:
        conn.putrequest("PUT", target, skip_accept_encoding=True)
        conn.putheader("Content-Length", str(len(body)))
        conn.putheader("Content-Type", "application/octet-stream")
        conn.endheaders()
        sock = conn.sock
        if sock is None:  # pragma: no cover - defensive
            raise RuntimeError("http.client did not expose a socket after endheaders()")

        send_started = time.monotonic()
        offset = 0
        while offset < len(body):
            chunk = body[offset:offset + chunk_size]
            sock.sendall(chunk)
            offset += len(chunk)
            result["sent"] = offset
            wait = (offset / rate_bps) - (time.monotonic() - send_started)
            if wait > 0:
                readable, _, _ = select.select([sock], [], [], wait)
            else:
                readable, _, _ = select.select([sock], [], [], 0)
            if readable:
                result["early_response"] = True
                break

        resp = conn.getresponse()
        result["status"] = resp.status
        result["headers"] = {k.lower(): v for k, v in resp.getheaders()}
        result["body"] = resp.read(65536)
    except Exception as exc:  # noqa: BLE001 - a reset/timeout IS the evidence
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed"] = time.monotonic() - started
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return result


def put_evidence(tag: str, res: dict, expected_bytes: int) -> None:
    hdrs = res["headers"]
    evidence(
        f"{tag}: status={res['status']!r} error={res['error']!r} "
        f"elapsed={res['elapsed']:.3f}s expected_send={res['expected_seconds']:.2f}s "
        f"sent={res['sent']}/{expected_bytes} bytes "
        f"early_response={res['early_response']} rate={res['rate_kbps']}KiB/s "
        f"resp_headers={hdrs} "
        f"resp_body={res['body'][:300]!r}")


# ---------------------------------------------------------------------------
# Warm-up: the very first write allocates the first volume on the fresh volume
# server (seen as "Adds volume:1" in its log). Racing that with the measured
# 80s upload made the gateway answer 500 InternalError, so force the allocation
# with a tiny retried PUT before any assertion.
# ---------------------------------------------------------------------------
def warm_up(good, bucket: str) -> bool:
    key = "proxy/warmup.txt"
    for attempt in range(1, 16):
        try:
            good.put_object(Bucket=bucket, Key=key, Body=b"warmup")
            good.delete_object(Bucket=bucket, Key=key)
            ok(f"warm-up: stack writable after {attempt} attempt(s) "
               f"(first volume allocated)")
            return True
        except Exception as exc:  # noqa: BLE001
            info(f"warm-up attempt {attempt}/15 not writable yet: {err_detail(exc)}")
            time.sleep(2)
    fail("warm-up: the ephemeral stack never became writable")
    return False


# ---------------------------------------------------------------------------
# Fast control: the same 5 MiB part through the proxy at full speed. Isolates a
# proxy/path problem from a slow-upload problem before A runs.
# ---------------------------------------------------------------------------
def preflight_fast_part(good, bucket: str) -> None:
    print("\n=== PREFLIGHT: 5 MiB UploadPart through the proxy at full speed ===",
          flush=True)
    body = b"\x42" * (5 * MIB)
    key = f"proxy/preflight-{int(time.time())}.bin"
    uid = None
    try:
        uid = good.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        started = time.monotonic()
        resp = good.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=1, Body=body)
        elapsed = time.monotonic() - started
        etag = norm_etag(resp["ETag"]).lower()
        evidence(f"PREFLIGHT UploadPart {len(body)} bytes via boto3 through the proxy: "
                 f"elapsed={elapsed:.3f}s ETag={resp['ETag']!r} "
                 f"local_md5={md5_hex(body)} HTTP="
                 f"{resp['ResponseMetadata']['HTTPStatusCode']}")
        if etag == md5_hex(body):
            ok("PREFLIGHT: a normal-speed 5 MiB part PUT through the proxy succeeds")
        else:
            fail(f"PREFLIGHT: fast part PUT ETag {etag!r} != MD5 {md5_hex(body)}")
    except Exception as exc:  # noqa: BLE001
        fail(f"PREFLIGHT: fast 5 MiB part PUT through the proxy failed: "
             f"{err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                good.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# A — slow part through the production-timeout proxy SUCCEEDS
# ---------------------------------------------------------------------------
def point_a(good, bucket: str, part_bytes: int, rate_kbps: int,
            origin: str) -> dict | None:
    print("\n=== A. SLOW PART THROUGH PROXY (readTimeout=7200s) ===", flush=True)
    body = bytes(range(256)) * (part_bytes // 256) + bytes(range(part_bytes % 256))
    key = f"proxy/a-slow-{int(time.time())}.bin"
    uid = None
    try:
        uid = good.create_multipart_upload(Bucket=bucket, Key=key,
                                           ContentType="application/octet-stream")["UploadId"]
        url = presign_part(good, bucket, key, uid, 1)
        info(f"presigned UploadPart URL: {safe_url(url)} (PartNumber=1, "
             f"{part_bytes} bytes, {rate_kbps} KiB/s)")

        res = throttled_put(url, body, rate_kbps)
        put_evidence("A", res, part_bytes)
        local_md5 = md5_hex(body)
        etag = norm_etag(res["headers"].get("etag")).lower()
        evidence(f"A body_md5_local={local_md5} etag_raw={res['headers'].get('etag')!r} "
                 f"etag_norm={etag} bytes_sent={res['sent']} bytes_expected={part_bytes} "
                 f"full_body_sent={res['sent'] == part_bytes}")

        if res["status"] == 200 and etag and etag == local_md5 and res["sent"] == part_bytes:
            ok(f"A: slow {part_bytes}-byte part SUCCEEDED through the proxy in "
               f"{res['elapsed']:.1f}s (body fully received: ETag == MD5 of the "
               f"{part_bytes} bytes sent)")
        else:
            fail(f"A: slow part did NOT complete correctly (status={res['status']} "
                 f"error={res['error']} etag={etag!r} local_md5={local_md5} "
                 f"sent={res['sent']}/{part_bytes})")
            return None

        # Assemble a single-part object: proves the ETag is usable and the bytes
        # the gateway stored are exactly the bytes we throttled out.
        done = good.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": res["headers"].get("etag")}]})
        uid = None  # completed; nothing to abort
        head = good.head_object(Bucket=bucket, Key=key)
        evidence(f"A Complete -> ETag={done.get('ETag')!r}; HEAD ContentLength="
                 f"{head['ContentLength']} (expected {part_bytes})")
        if head["ContentLength"] == part_bytes:
            ok("A: assembled object length equals the bytes uploaded through the proxy")
        else:
            fail(f"A: assembled length {head['ContentLength']} != {part_bytes}")

        stored = good.get_object(Bucket=bucket, Key=key)["Body"].read()
        evidence(f"A GET bytes={len(stored)} sha256={hashlib.sha256(stored).hexdigest()} "
                 f"expected_sha256={hashlib.sha256(body).hexdigest()}")
        if stored == body:
            ok("A: GET round-trip after the proxied part PUT is byte-identical")
        else:
            fail("A: GET round-trip differs from the uploaded bytes")
        return res
    except Exception as exc:  # noqa: BLE001
        fail(f"A: probe raised: {err_detail(exc)}")
        return None
    finally:
        if uid is not None:
            try:
                good.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# B — negative control: default readTimeout (60s) cuts the same upload
# ---------------------------------------------------------------------------
def point_b(bad, bucket: str, part_bytes: int, rate_kbps: int) -> None:
    print("\n=== B. NEGATIVE CONTROL: same slow part, DEFAULT readTimeout (60s) ===",
          flush=True)
    body = bytes(range(256)) * (part_bytes // 256) + bytes(range(part_bytes % 256))
    key = f"proxy/b-default-timeout-{int(time.time())}.bin"
    uid = None
    try:
        uid = bad.create_multipart_upload(Bucket=bucket, Key=key,
                                          ContentType="application/octet-stream")["UploadId"]
        url = presign_part(bad, bucket, key, uid, 1)
        info(f"presigned UploadPart URL through the DEFAULT-timeout proxy: "
             f"{safe_url(url)}; sending {part_bytes} bytes at {rate_kbps} KiB/s "
             f"(expected send {part_bytes / (rate_kbps * KIB):.1f}s > 60s)")
        res = throttled_put(url, body, rate_kbps)
        put_evidence("B", res, part_bytes)
        local_md5 = md5_hex(body)
        etag = norm_etag(res["headers"].get("etag")).lower()
        elapsed = res["elapsed"]
        evidence(f"B body_md5_local={local_md5} etag_norm={etag!r} "
                 f"status={res['status']!r} error={res['error']!r} "
                 f"elapsed={elapsed:.3f}s sent={res['sent']}/{part_bytes} "
                 f"early_response={res['early_response']}")

        if res["status"] == 200 and etag == local_md5 and res["sent"] == part_bytes:
            unknown("B: NEGATIVE CONTROL DID NOT FAIL — the default-timeout proxy "
                    "accepted the whole slow part, so this harness cannot prove it "
                    "detects the readTimeout regression. Evidence above.", blocking=True)
            return
        if elapsed < TRAEFIK_DEFAULT_READ_TIMEOUT_S - 5:
            fail(f"B: request failed after only {elapsed:.1f}s, before the 60s "
                 f"readTimeout could fire — this is not proof of a timeout cutoff "
                 f"(status={res['status']!r} error={res['error']!r})")
            return
        ok(f"B: default-timeout proxy CUT OFF the slow part after {elapsed:.1f}s "
           f"(status={res['status']!r} error={res['error']!r} "
           f"sent={res['sent']}/{part_bytes}); the regression is detectable")
    except Exception as exc:  # noqa: BLE001
        fail(f"B: probe raised: {err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                bad.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# C — part-size sizing arithmetic
# ---------------------------------------------------------------------------
def point_c(pilot_part_bytes: int, default_part_bytes: int) -> None:
    print("\n=== C. SIZING: max part size under readTimeout=7200s ===", flush=True)
    info("docs/MULTIPART-UPLOAD-PLAN.md lines 42-65 state NO explicit worst-case "
         "client bandwidth. The slowest rate it measures is 300 KB/s (a 37.5 MB "
         "single PUT answered HTTP 502 at 60.05s). Using 300 KB/s as the doc's "
         "reference and 64 KiB/s as an explicit conservative assumption (the rate "
         "this harness actually tests, 0.5 Mbit/s).")
    rates = (
        ("conservative assumption (tested here)", 64),
        ("doc slowest measured rate", 300),
    )
    comfortable_limit = DEFAULT_READ_TIMEOUT_S / 2  # keep 50% headroom
    for label, rate_kbps in rates:
        bps = rate_kbps * KIB
        max_bytes = DEFAULT_READ_TIMEOUT_S * bps
        evidence(f"C {label}: {rate_kbps} KiB/s * {DEFAULT_READ_TIMEOUT_S}s = "
                 f"{max_bytes} bytes = {max_bytes / MIB:.2f} MiB maximum part; "
                 f"comfortable (50% budget = {comfortable_limit:.0f}s) = "
                 f"{max_bytes / 2 / MIB:.2f} MiB")
        for name, size in (("pilot AURA_MULTIPART_PART_BYTES", pilot_part_bytes),
                           ("code default AURA_MULTIPART_PART_BYTES",
                            default_part_bytes)):
            secs = size / bps
            evidence(f"C {label}: {name} = {size} bytes = {size / MIB:.2f} MiB "
                     f"-> {secs:.1f}s = {secs / DEFAULT_READ_TIMEOUT_S * 100:.2f}% "
                     f"of {DEFAULT_READ_TIMEOUT_S}s")

    conservative = 64 * KIB
    worst_secs = max(pilot_part_bytes, default_part_bytes) / conservative
    if worst_secs <= comfortable_limit:
        ok(f"C: both {pilot_part_bytes / MIB:.0f} MiB (pilot) and "
           f"{default_part_bytes / MIB:.0f} MiB (code default) parts use at most "
           f"{worst_secs:.1f}s / {DEFAULT_READ_TIMEOUT_S}s at 64 KiB/s — safe with "
           f"large margin")
    else:
        fail(f"C: {max(pilot_part_bytes, default_part_bytes) / MIB:.0f} MiB part "
             f"needs {worst_secs:.1f}s at 64 KiB/s, over the 50% comfort budget")


# ---------------------------------------------------------------------------
# Browser-facing diagnostics (through the proxy)
# ---------------------------------------------------------------------------
def http_request(url: str, method: str, data: bytes | None = None,
                 headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def diag_expect_continue(good, bucket: str, origin: str) -> None:
    print("\n=== DIAG. Expect: 100-continue through the proxy ===", flush=True)
    body = b"\x5a" * (1 * MIB)
    key = f"proxy/expect-{int(time.time())}.bin"
    uid = None
    try:
        uid = good.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        url = presign_part(good, bucket, key, uid, 1)
        p = urlparse(url)
        target = p.path + ("?" + p.query if p.query else "")
        host_hdr = f"{p.hostname}:{p.port or 80}"
        request = (
            f"PUT {target} HTTP/1.1\r\n"
            f"Host: {host_hdr}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Expect: 100-continue\r\n"
            f"Connection: close\r\n\r\n").encode()

        sock = socket.create_connection((p.hostname, p.port or 80), timeout=10)
        started = time.monotonic()
        sock.sendall(request)
        sock.settimeout(3)
        buf = b""
        interim = None
        try:
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass

        if buf.startswith(b"HTTP/") and b" 100 " in buf.split(b"\r\n", 1)[0]:
            interim = buf.split(b"\r\n", 1)[0].decode(errors="replace")
            t100 = time.monotonic() - started
            sock.settimeout(60)
            sock.sendall(body)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            evidence(f"Expect: proxy/backend sent interim {interim!r} after "
                     f"{t100:.3f}s")
        elif not buf.startswith(b"HTTP/"):
            info("Expect: no interim 100 within 3s (the request head was not "
                 "answered) — sending the body after the wait, as curl would")
            sock.settimeout(60)
            sock.sendall(body)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk

        head = buf.split(b"\r\n\r\n", 1)[0]
        lines = head.split(b"\r\n")
        status = int(lines[0].split()[1]) if len(lines[0].split()) >= 2 else None
        headers = {}
        for ln in lines[1:]:
            if b":" in ln:
                k, v = ln.split(b":", 1)
                headers[k.decode().lower()] = v.decode().strip()
        evidence(f"Expect: final status={status!r} elapsed={time.monotonic() - started:.3f}s "
                 f"etag={headers.get('etag')!r} headers={headers}")
        if status == 200 and headers.get("etag"):
            ok("DIAG: PUT with Expect: 100-continue completes through the proxy")
        else:
            info(f"DIAG: PUT with Expect: 100-continue returned {status!r} — "
                 f"browser quirk to note")
    except Exception as exc:  # noqa: BLE001
        info(f"DIAG: Expect: 100-continue probe could not complete: "
             f"{type(exc).__name__}: {exc}")
    finally:
        try:
            sock.close()  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        if uid is not None:
            try:
                good.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


def diag_cors(good, bucket: str, origin: str) -> None:
    print("\n=== DIAG. CORS preflight through the proxy ===", flush=True)
    key = f"proxy/cors-{int(time.time())}.bin"
    uid = None
    try:
        uid = good.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        url = presign_part(good, bucket, key, uid, 1)
        st, h, body = http_request(url, "OPTIONS", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        })
        cors = {k: v for k, v in h.items() if k.startswith("access-control")}
        evidence(f"CORS OPTIONS via proxy -> HTTP {st} {cors} body={body[:200]!r}")
        if cors.get("access-control-allow-origin") in (origin, "*"):
            ok("DIAG: CORS preflight for a proxied part PUT allows the origin")
        else:
            info("DIAG: CORS preflight through the proxy did not allow the origin "
                 "(browser upload would fail at preflight)")
    except Exception as exc:  # noqa: BLE001
        info(f"DIAG: CORS probe could not complete: {type(exc).__name__}: {exc}")
    finally:
        if uid is not None:
            try:
                good.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    global PROXY_HOST
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", required=True,
                    help="good proxy endpoint, e.g. http://s3.test:32768")
    ap.add_argument("--bad-endpoint", required=True,
                    help="default-readTimeout proxy endpoint")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--proxy-host", default=PROXY_HOST,
                    help="hostname routed by Traefik (resolved to 127.0.0.1)")
    ap.add_argument("--origin", default="https://proxy.example.test")
    ap.add_argument("--slow-rate-kbps", type=int, default=64,
                    help="client-side upload rate in KiB/s (default 64 = 0.5 Mbit/s)")
    ap.add_argument("--part-bytes", type=int, default=5 * MIB)
    ap.add_argument("--pilot-part-bytes", type=int, default=5 * MIB)
    ap.add_argument("--default-part-bytes", type=int, default=16 * MIB)
    ap.add_argument("--access-key", default=os.environ.get("S3_ACCESS_KEY"))
    ap.add_argument("--secret-key", default=os.environ.get("S3_SECRET_KEY"))
    args = ap.parse_args(argv)

    if not args.access_key or not args.secret_key:
        print("Set S3_ACCESS_KEY / S3_SECRET_KEY in the environment.", file=sys.stderr)
        return 2
    if args.part_bytes <= 0:
        print("--part-bytes must be positive.", file=sys.stderr)
        return 2
    if args.part_bytes / (args.slow_rate_kbps * KIB) <= TRAEFIK_DEFAULT_READ_TIMEOUT_S:
        print(f"WARNING: {args.part_bytes} bytes at {args.slow_rate_kbps} KiB/s takes "
              f"only {args.part_bytes / (args.slow_rate_kbps * KIB):.1f}s; it must "
              f"EXCEED {TRAEFIK_DEFAULT_READ_TIMEOUT_S}s for the negative control.",
              file=sys.stderr)

    PROXY_HOST = args.proxy_host
    install_dns_override(args.proxy_host)

    good = make_client(args.endpoint, args.access_key, args.secret_key)
    bad = make_client(args.bad_endpoint, args.access_key, args.secret_key)
    print(f"good_endpoint={args.endpoint} bad_endpoint={args.bad_endpoint} "
          f"bucket={args.bucket} origin={args.origin} "
          f"part_bytes={args.part_bytes} rate={args.slow_rate_kbps}KiB/s")

    try:
        good.create_bucket(Bucket=args.bucket)
        ok(f"CreateBucket {args.bucket} through the proxy")
    except ClientError as exc:
        info(f"CreateBucket: {err_detail(exc)} (continuing)")

    point_c(args.pilot_part_bytes, args.default_part_bytes)
    if not warm_up(good, args.bucket):
        print(f"\n=== SUMMARY: failures={_failures} blocking_unknowns="
              f"{_blocking_unknowns} other_unknowns={_unknowns - _blocking_unknowns} "
              f"passes={_passes} ===")
        return 1
    preflight_fast_part(good, args.bucket)
    point_a(good, args.bucket, args.part_bytes, args.slow_rate_kbps, args.origin)
    diag_expect_continue(good, args.bucket, args.origin)
    diag_cors(good, args.bucket, args.origin)
    point_b(bad, args.bucket, args.part_bytes, args.slow_rate_kbps)

    print(f"\n=== SUMMARY: failures={_failures} blocking_unknowns={_blocking_unknowns} "
          f"other_unknowns={_unknowns - _blocking_unknowns} passes={_passes} ===")
    return 1 if (_failures or _blocking_unknowns) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
