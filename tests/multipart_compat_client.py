#!/usr/bin/env python3
"""Multipart compatibility client for the SeaweedFS 4.48 compatibility harness.

Companion of ``tests/multipart-compat-4.48.sh`` (which starts an EPHEMERAL,
isolated SeaweedFS stack). It must never be pointed at the pilot stack.

Design contract for this probe (issue #84 / [ENG-03]):
  * The control plane is driven with boto3 configured exactly like ``api/s3.py``
    (SigV4, path-style). boto3 only *signs*; it is the same library the server
    already uses, so no hand-rolled SigV4 duplication is needed.
  * Presigned per-part URLs are then *consumed* with a plain HTTP client
    (``urllib``) — i.e. what a browser does, NOT an SDK.
  * No secret and no full presigned URL is ever printed (path + query keys only).
  * Every assertion is backed by real command output against the pinned image.

Exit code 0 iff every asserted check passed; non-zero otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

PART1 = b"\x11" * (5 * 1024 * 1024)  # exactly the 5 MiB minimum
PART2 = b"\x22" * (1 * 1024 * 1024)
SMALL = b"\x33" * (1024 * 1024)  # 1 MiB, below the minimum non-last part size

_failures = 0
_unknowns = 0


def line(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def ok(msg: str) -> None:
    line("PASS", msg)


def fail(msg: str) -> None:
    global _failures
    _failures += 1
    line("FAIL", msg)


def unknown(msg: str) -> None:
    global _unknowns
    _unknowns += 1
    line("UNKNOWN", msg)


def info(msg: str) -> None:
    line("INFO", msg)


def safe_url(url: str) -> str:
    """Path + sorted query keys, never values (presigned sigs are secrets)."""
    p = urlparse(url)
    keys = ",".join(sorted(parse_qs(p.query)))
    return f"{p.scheme}://{p.netloc}{p.path}?<{keys}>"


def http(method: str, url: str, data: bytes | None = None,
         headers: dict | None = None, timeout: int = 120):
    """Return (status, dict-of-lowercased-headers, body). Never raises on 4xx/5xx."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, resp.read()
    except urllib.error.HTTPError as exc:
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, hdrs, exc.read()


def err_detail(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        e = exc.response.get("Error", {})
        return (f"Code={e.get('Code')!r} Message={e.get('Message')!r} "
                f"HTTPStatus={exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')}")
    return f"{type(exc).__name__}: {exc}"


def make_client(endpoint: str, ak: str, sk: str):
    return boto3.client(
        "s3", endpoint_url=endpoint,
        aws_access_key_id=ak, aws_secret_access_key=sk, region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def volume_stats(container: str | None) -> tuple[int, int] | None:
    """(file_count, total_bytes) for /data inside the volume container, or None."""
    if not container:
        return None
    try:
        out = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             "c=$(find /data -type f 2>/dev/null | wc -l); "
             "b=$(du -sb /data 2>/dev/null | awk '{print $1}'); echo \"$c $b\""],
            capture_output=True, text=True, timeout=30, check=True,
        )
        count_s, bytes_s = out.stdout.strip().split()
        return int(count_s), int(bytes_s)
    except Exception as exc:  # noqa: BLE001 - evidence gathering only
        info(f"volume stats unavailable: {type(exc).__name__}")
        return None


# ---------------------------------------------------------------------------
# Point 1 — full multipart lifecycle + abort
# ---------------------------------------------------------------------------
def point1(client, bucket: str) -> None:
    print("\n=== POINT 1: CreateMultipartUpload / UploadPart / ListParts / "
          "CompleteMultipartUpload / AbortMultipartUpload ===", flush=True)
    key = "compat/point1.bin"
    try:
        created = client.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType="application/octet-stream")
        uid = created["UploadId"]
        ok(f"CreateMultipartUpload -> UploadId present={bool(uid)}")
        info(f"create response keys: {sorted(created.keys())}")

        e1 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=1, Body=PART1)["ETag"]
        e2 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=2, Body=PART2)["ETag"]
        ok(f"UploadPart x2 -> ETag1={e1!r} ETag2={e2!r}")

        parts = client.list_parts(Bucket=bucket, Key=key, UploadId=uid)
        listed = [(p["PartNumber"], p["ETag"], p["Size"]) for p in parts.get("Parts", [])]
        info(f"ListParts -> {listed}")
        if sorted(n for n, _, _ in listed) == [1, 2]:
            ok("ListParts reports both parts")
        else:
            fail("ListParts did not report exactly parts 1 and 2")

        done = client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": e1}, {"PartNumber": 2, "ETag": e2}]})
        info(f"CompleteMultipartUpload -> ETag={done.get('ETag')!r} "
             f"Location={done.get('Location')!r}")
        head = client.head_object(Bucket=bucket, Key=key)
        info(f"HEAD -> ContentLength={head['ContentLength']} ETag={head['ETag']!r}")
        if head["ContentLength"] != len(PART1) + len(PART2):
            fail("HEAD ContentLength != sum of parts")
        else:
            ok("HEAD ContentLength matches sum of parts")
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(body).hexdigest() == hashlib.sha256(PART1 + PART2).hexdigest():
            ok("GET round-trip SHA-256 matches")
        else:
            fail("GET round-trip SHA-256 mismatch")

        # Abort on a second upload.
        uid2 = client.create_multipart_upload(Bucket=bucket, Key="compat/point1-abort.bin")["UploadId"]
        client.upload_part(Bucket=bucket, Key="compat/point1-abort.bin",
                           UploadId=uid2, PartNumber=1, Body=SMALL)
        client.abort_multipart_upload(Bucket=bucket, Key="compat/point1-abort.bin", UploadId=uid2)
        ok("AbortMultipartUpload accepted")
        try:
            client.list_parts(Bucket=bucket, Key="compat/point1-abort.bin", UploadId=uid2)
            fail("ListParts after abort unexpectedly succeeded")
        except ClientError as exc:
            ok(f"ListParts after abort is gone ({err_detail(exc)})")
    except Exception as exc:  # noqa: BLE001
        fail(f"multipart lifecycle raised: {err_detail(exc)}")
        raise


# ---------------------------------------------------------------------------
# Point 2 — minimum non-last part size
# ---------------------------------------------------------------------------
def point2(client, bucket: str) -> None:
    print("\n=== POINT 2: minimum-part-size rule (non-last part < 5 MiB) ===", flush=True)
    key = "compat/point2-small.bin"
    uid = None
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        e1 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=1, Body=SMALL)["ETag"]
        e2 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=2, Body=SMALL)["ETag"]
        info("UploadPart of two 1 MiB parts succeeded; now attempting Complete ...")
        try:
            client.complete_multipart_upload(
                Bucket=bucket, Key=key, UploadId=uid,
                MultipartUpload={"Parts": [
                    {"PartNumber": 1, "ETag": e1}, {"PartNumber": 2, "ETag": e2}]})
            info("Complete accepted a non-last part < 5 MiB (backend-specific)")
            global _unknowns
            _unknowns += 1
            print("[UNKNOWN] backend accepted small non-last part: cannot rely on the "
                  "5 MiB minimum being enforced", flush=True)
        except ClientError as exc:
            ok(f"Complete rejected small non-last part: {err_detail(exc)}")
        try:
            client.get_object(Bucket=bucket, Key=key)
            info("an object exists at the key after a rejected Complete (unexpected)")
        except ClientError as exc:
            info(f"no object at the key after rejected Complete ({exc.response['Error'].get('Code')})")
    except Exception as exc:  # noqa: BLE001
        fail(f"small-part probe raised: {err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Point 3 — presigned per-part URL consumed by a plain HTTP client
# ---------------------------------------------------------------------------
def point3(client, bucket: str) -> None:
    print("\n=== POINT 3: presigned per-part URL via plain HTTP client (urllib) ===", flush=True)
    key = "compat/point3-presigned.bin"
    uid = None
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        url1 = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": 1},
            ExpiresIn=600)
        info(f"presigned upload_part URL: {safe_url(url1)}")
        st, hdrs, _ = http("PUT", url1, data=PART1,
                           headers={"Content-Type": "application/octet-stream"})
        etag1 = hdrs.get("etag")
        if st in (200, 201) and etag1:
            ok(f"plain-HTTP PUT of part 1 via presigned URL -> HTTP {st} ETag={etag1!r}")
        else:
            fail(f"plain-HTTP PUT of part 1 failed: HTTP {st} ETag={etag1!r}")
            return

        url2 = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": 2},
            ExpiresIn=600)
        st2, hdrs2, _ = http("PUT", url2, data=PART2,
                             headers={"Content-Type": "application/octet-stream"})
        etag2 = hdrs2.get("etag")
        if st2 in (200, 201) and etag2:
            ok(f"plain-HTTP PUT of part 2 via presigned URL -> HTTP {st2} ETag={etag2!r}")
        else:
            fail(f"plain-HTTP PUT of part 2 failed: HTTP {st2} ETag={etag2!r}")
            return

        # Complete with EXACTLY the ETags echoed back by the gateway.
        done = client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": etag1}, {"PartNumber": 2, "ETag": etag2}]})
        ok(f"CompleteMultipartUpload with exact returned ETags -> ETag={done.get('ETag')!r}")
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(body).hexdigest() == hashlib.sha256(PART1 + PART2).hexdigest():
            ok("presigned-part upload round-trip SHA-256 matches")
        else:
            fail("presigned-part upload round-trip SHA-256 mismatch")
    except Exception as exc:  # noqa: BLE001
        fail(f"presigned-part probe raised: {err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Point 4 — SSE-S3 (AES256) across multipart
# ---------------------------------------------------------------------------
def point4(client, bucket: str) -> None:
    print("\n=== POINT 4: ServerSideEncryption=AES256 on multipart ===", flush=True)
    key = "compat/point4-sse.bin"
    uid = None
    uid2 = None

    # Environment sanity: a single PUT with SSE-S3 (what the pilot smoke test does)
    # proves whether the KEK is active at all before blaming multipart.
    single = "compat/point4-single.bin"
    try:
        client.put_object(Bucket=bucket, Key=single, Body=b"sse-sanity",
                          ServerSideEncryption="AES256")
        h = client.head_object(Bucket=bucket, Key=single)
        info(f"single PUT HEAD ServerSideEncryption={h.get('ServerSideEncryption')!r}")
        if h.get("ServerSideEncryption") == "AES256":
            ok("single PUT with SSE-S3 reports AES256 (KEK active)")
        else:
            fail("single PUT with SSE-S3 did not report AES256: SSE-S3 not active here")
    except Exception as exc:  # noqa: BLE001
        fail(f"single PUT SSE sanity raised: {err_detail(exc)}")

    try:
        created = client.create_multipart_upload(
            Bucket=bucket, Key=key, ServerSideEncryption="AES256",
            ContentType="application/octet-stream")
        uid = created["UploadId"]
        info(f"CreateMultipartUpload response ServerSideEncryption="
             f"{created.get('ServerSideEncryption')!r}")
        if created.get("ServerSideEncryption") == "AES256":
            ok("CreateMultipartUpload echoed ServerSideEncryption=AES256")
        else:
            info("CreateMultipartUpload did not echo SSE (SeaweedFS may apply it "
                 "server-side anyway; HEAD after Complete is the authoritative check)")

        # (a) UploadPart via presigned URL WITH the SSE header added by the client.
        url1 = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": 1},
            ExpiresIn=600)
        st_with, h_with, b_with = http("PUT", url1, data=PART1, headers={
            "Content-Type": "application/octet-stream",
            "x-amz-server-side-encryption": "AES256"})
        info(f"UploadPart 1 WITH x-amz-server-side-encryption (unsigned) -> "
             f"HTTP {st_with} body={b_with[:160]!r}")

        # (b) The same part through a fresh presigned URL, WITHOUT the header.
        uid2 = client.create_multipart_upload(
            Bucket=bucket, Key=key, ServerSideEncryption="AES256")["UploadId"]
        url1b = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid2, "PartNumber": 1},
            ExpiresIn=600)
        url2b = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid2, "PartNumber": 2},
            ExpiresIn=600)
        st1, h1, b1 = http("PUT", url1b, data=PART1,
                           headers={"Content-Type": "application/octet-stream"})
        st2, h2, b2 = http("PUT", url2b, data=PART2,
                           headers={"Content-Type": "application/octet-stream"})
        info(f"UploadPart 1 WITHOUT SSE header -> HTTP {st1} ETag={h1.get('etag')!r}")
        info(f"UploadPart 2 WITHOUT SSE header -> HTTP {st2} ETag={h2.get('etag')!r}")

        if st_with == 200:
            info("SSE header accepted on UploadPart (no re-send problem)")
        else:
            info("SSE header REJECTED on UploadPart when unsigned -> the SSE-S3 header "
                 "must NOT be re-sent on a presigned UploadPart (see doc)")
        if st1 in (200, 201) and st2 in (200, 201) and h1.get("etag") and h2.get("etag"):
            ok("UploadPart without the SSE header succeeds (header not required per part)")
        else:
            fail(f"UploadPart without SSE header failed: part1={st1} part2={st2}")

        done = client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid2,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": h1.get("etag")},
                {"PartNumber": 2, "ETag": h2.get("etag")}]})
        ok(f"CompleteMultipartUpload (SSE at create) -> ETag={done.get('ETag')!r}")
        head = client.head_object(Bucket=bucket, Key=key)
        seen = head.get("ServerSideEncryption")
        info(f"HEAD after Complete x-amz-server-side-encryption={seen!r}")
        if seen == "AES256":
            ok("HEAD after Complete reports AES256 (multipart inherited SSE)")
        else:
            fail(f"HEAD after Complete reports {seen!r}, expected AES256 — SSE-S3 not "
                 f"applied to the multipart object")
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(body).hexdigest() == hashlib.sha256(PART1 + PART2).hexdigest():
            ok("SSE multipart download bytes match uploaded SHA-256")
        else:
            fail("SSE multipart download bytes differ from uploaded SHA-256")
    except Exception as exc:  # noqa: BLE001
        fail(f"SSE multipart probe raised: {err_detail(exc)}")
    finally:
        for u in (uid, uid2):
            if u is not None:
                try:
                    client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=u)
                except Exception:  # noqa: BLE001
                    pass
        try:
            client.delete_object(Bucket=bucket, Key=single)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Point 5 — byte-range GET
# ---------------------------------------------------------------------------
def point5(client, bucket: str) -> None:
    print("\n=== POINT 5: byte-range GET ===", flush=True)
    key = "compat/point5-range.bin"
    whole = PART1 + PART2
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        e1 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=1, Body=PART1)["ETag"]
        e2 = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                PartNumber=2, Body=PART2)["ETag"]
        client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": e1}, {"PartNumber": 2, "ETag": e2}]})
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=600)

        st, h, body = http("GET", url)
        info(f"full GET -> HTTP {st} ContentLength={h.get('content-length')} "
             f"Accept-Ranges={h.get('accept-ranges')!r}")
        if st == 200 and body == whole:
            ok("full GET returns whole object")
        else:
            fail("full GET did not return the whole object")

        st, h, body = http("GET", url, headers={"Range": "bytes=0-99"})
        info(f"Range 0-99 -> HTTP {st} Content-Range={h.get('content-range')!r} "
             f"ContentLength={h.get('content-length')} Accept-Ranges={h.get('accept-ranges')!r}")
        if st == 206 and body == whole[:100]:
            ok("prefix range returns 206 with 100 bytes")
        else:
            fail("prefix range incorrect")

        st, h, body = http("GET", url, headers={"Range": "bytes=-50"})
        info(f"suffix Range -50 -> HTTP {st} Content-Range={h.get('content-range')!r}")
        if st == 206 and body == whole[-50:]:
            ok("suffix range returns last 50 bytes")
        else:
            fail("suffix range incorrect")

        st, h, body = http("GET", url, headers={"Range": f"bytes={len(whole) + 1000}-"})
        info(f"out-of-range -> HTTP {st} Content-Range={h.get('content-range')!r} "
             f"body={body[:200]!r}")
        if st == 416:
            ok("out-of-range range returns 416")
        else:
            fail(f"out-of-range range returned HTTP {st}, expected 416")

        st, h, body = http("GET", url, headers={"Range": "bytes=0-9,20-29"})
        ct = h.get("content-type")
        got_first = whole[:10] in body
        got_second = whole[20:30] in body
        info(f"multi-range -> HTTP {st} Content-Type={ct!r} "
             f"contains-first={got_first} contains-second={got_second} len={len(body)}")
    except Exception as exc:  # noqa: BLE001
        fail(f"range probe raised: {err_detail(exc)}")


# ---------------------------------------------------------------------------
# Point 6 — abort removes the upload and (best effort) its data
# ---------------------------------------------------------------------------
def point6(client, bucket: str, volume_container: str | None) -> None:
    print("\n=== POINT 6: abort cleanup ===", flush=True)
    key = "compat/point6-cleanup.bin"
    before = volume_stats(volume_container)
    info(f"volume /data stats (files,bytes) before upload: {before}")
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        client.upload_part(Bucket=bucket, Key=key, UploadId=uid, PartNumber=1, Body=PART1)
        client.upload_part(Bucket=bucket, Key=key, UploadId=uid, PartNumber=2, Body=PART1)
        after_upload = volume_stats(volume_container)
        info(f"volume /data stats after 2x5MiB parts: {after_upload}")
        uploads = client.list_multipart_uploads(Bucket=bucket, Prefix=key)
        names = [u["Key"] for u in uploads.get("Uploads", [])]
        info(f"ListMultipartUploads before abort -> {names}")
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
        ok("AbortMultipartUpload accepted")
        try:
            client.list_parts(Bucket=bucket, Key=key, UploadId=uid)
            fail("ListParts after abort unexpectedly succeeded")
        except ClientError as exc:
            ok(f"ListParts after abort gone ({err_detail(exc)})")
        uploads = client.list_multipart_uploads(Bucket=bucket, Prefix=key)
        names = [u["Key"] for u in uploads.get("Uploads", [])]
        info(f"ListMultipartUploads after abort -> {names}")
        after_abort = volume_stats(volume_container)
        info(f"volume /data stats after abort: {after_abort}")
        if before is None or after_upload is None or after_abort is None:
            unknown("volume stats unavailable: disk-level removal is UNKNOWN")
        else:
            info(f"volume bytes: before={before[1]} after_upload={after_upload[1]} "
                 f"after_abort={after_abort[1]} (SeaweedFS appends to shared .dat files, "
                 f"so a byte delta is not attributable to a single upload)")
            unknown("disk-level removal not provable from volume stats; the S3 API "
                    "guarantee (ListParts/ListMultipartUploads gone) is what is VERIFIED")
    except Exception as exc:  # noqa: BLE001
        fail(f"abort cleanup probe raised: {err_detail(exc)}")


# ---------------------------------------------------------------------------
# Point 7 — CORS surface for browser part upload/download
# ---------------------------------------------------------------------------
def point7(client, bucket: str, origin: str) -> None:
    print("\n=== POINT 7: CORS surface (browser part PUT / GET) ===", flush=True)
    key = "compat/point7-cors.bin"
    uid = None
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        url = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": 1},
            ExpiresIn=600)
        st, h, _ = http("OPTIONS", url, headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-amz-server-side-encryption",
        })
        cors = {k: v for k, v in h.items() if k.startswith("access-control")}
        info(f"OPTIONS preflight PUT -> HTTP {st} {cors}")
        if cors.get("access-control-allow-origin") in (origin, "*"):
            ok("preflight allows the origin")
        else:
            fail(f"preflight did not allow origin: {cors!r}")
        if "put" in (cors.get("access-control-allow-methods", "").lower()):
            ok("preflight allows PUT")
        else:
            fail(f"preflight does not advertise PUT: {cors.get('access-control-allow-methods')!r}")

        st, h, _ = http("PUT", url, data=PART1, headers={
            "Origin": origin, "Content-Type": "application/octet-stream"})
        cors = {k: v for k, v in h.items() if k.startswith("access-control")}
        exposed = cors.get("access-control-expose-headers", "")
        info(f"PUT with Origin -> HTTP {st} {cors}")
        if "etag" in exposed.lower():
            ok("part PUT exposes ETag to the browser (Access-Control-Expose-Headers)")
        else:
            unknown(f"ETag NOT advertised in Access-Control-Expose-Headers "
                    f"(value={exposed!r}) — browser cannot read it without config/JS workaround")
        if h.get("etag"):
            info(f"part PUT ETag header present on the wire: {h.get('etag')!r}")

        # Complete and check CORS on a downloadable GET.
        url2 = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": 2},
            ExpiresIn=600)
        _, h2, _ = http("PUT", url2, data=PART2,
                        headers={"Content-Type": "application/octet-stream"})
        client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": h.get("etag") or ""},
                {"PartNumber": 2, "ETag": h2.get("etag") or ""}]})
        get_url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=600)
        st, h, _ = http("GET", get_url, headers={"Origin": origin})
        cors = {k: v for k, v in h.items() if k.startswith("access-control")}
        info(f"GET with Origin -> HTTP {st} {cors}")
    except Exception as exc:  # noqa: BLE001
        fail(f"CORS probe raised: {err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--origin", default="https://compat.example.test")
    ap.add_argument("--volume-container", default=None)
    ap.add_argument("--access-key", default=os.environ.get("S3_ACCESS_KEY"))
    ap.add_argument("--secret-key", default=os.environ.get("S3_SECRET_KEY"))
    args = ap.parse_args(argv)

    if not args.access_key or not args.secret_key:
        print("Set S3_ACCESS_KEY / S3_SECRET_KEY in the environment.", file=sys.stderr)
        return 2

    client = make_client(args.endpoint, args.access_key, args.secret_key)
    print(f"endpoint={args.endpoint} bucket={args.bucket} origin={args.origin}")
    try:
        client.create_bucket(Bucket=args.bucket)
        ok(f"CreateBucket {args.bucket}")
    except ClientError as exc:
        info(f"CreateBucket: {err_detail(exc)} (continuing)")

    for fn in (lambda: point1(client, args.bucket),
               lambda: point2(client, args.bucket),
               lambda: point3(client, args.bucket),
               lambda: point4(client, args.bucket),
               lambda: point5(client, args.bucket),
               lambda: point6(client, args.bucket, args.volume_container),
               lambda: point7(client, args.bucket, args.origin)):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - keep other points running
            fail(f"point aborted: {err_detail(exc)}")

    print(f"\n=== SUMMARY: failures={_failures} unknowns={_unknowns} ===")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
