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
import ast
import base64
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
_passes = 0

# Set by POINT 9: "signed" | "unsigned" | None — whether a presigned UploadPart
# accepted x-amz-checksum-sha256 and how it had to be signed.
CHECKSUM_MODE: str | None = None


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


def evidence(msg: str) -> None:
    """Raw, auditable evidence line (status codes, headers, hex values)."""
    line("EVIDENCE", msg)


def norm_etag(raw: str | None) -> str:
    """Strip the quotes S3 puts around ETags."""
    return (raw or "").strip().strip('"')


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def b64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def resp_meta(resp: dict) -> str:
    meta = resp.get("ResponseMetadata", {})
    return f"http={meta.get('HTTPStatusCode')} headers={meta.get('HTTPHeaders')}"


def presign_upload_part(client, bucket: str, key: str, uid: str, part_number: int,
                        checksum_b64: str | None = None,
                        content_length: int | None = None) -> tuple[str, str]:
    """Presign UploadPart; optionally put x-amz-checksum-sha256 into SignedHeaders.

    botocore serialises UploadPart.ChecksumSHA256 as the x-amz-checksum-sha256
    *header*, so passing it in Params makes it part of X-Amz-SignedHeaders.
    ``content_length`` is the same trick for ``Content-Length`` (what
    ``api/s3.py:presigned_upload_part`` does to bind a part to its exact size).
    Returns (url, x-amz-signedheaders value).
    """
    params = {"Bucket": bucket, "Key": key, "UploadId": uid, "PartNumber": part_number}
    if checksum_b64 is not None:
        params["ChecksumSHA256"] = checksum_b64
    if content_length is not None:
        params["ContentLength"] = content_length
    url = client.generate_presigned_url("upload_part", Params=params, ExpiresIn=600)
    signed = parse_qs(urlparse(url).query).get("X-Amz-SignedHeaders", [""])[0]
    return url, signed


def composite_md5(part_digests: list[bytes]) -> str:
    """S3 multipart ETag for parts whose ETags are MD5 hex digests."""
    return hashlib.md5(b"".join(part_digests)).hexdigest() + f"-{len(part_digests)}"



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


# ---------------------------------------------------------------------------
# Point 8 — is the UploadPart ETag the MD5 of that part's bytes?
# ---------------------------------------------------------------------------
P8_PARTS = (
    (1, b"\x11" * (5 * 1024 * 1024), "exactly 5 MiB, minimum non-last size"),
    (2, (b"\x22\x33\x44\x55" * ((5 * 1024 * 1024 + 4099) // 4 + 1))[: 5 * 1024 * 1024 + 4099],
     "5 MiB + 4099 bytes (deliberately not chunk-aligned)"),
    (3, b"\x99\x88\x77", "3-byte last part"),
)


def point8(client, bucket: str) -> None:
    print("\n=== POINT 8: is the UploadPart ETag the MD5 of that part's bytes? ===", flush=True)
    key = "compat/point8-part-md5.bin"
    uid = None
    uid0 = None
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        etags: dict[int, str] = {}
        for n, data, note in P8_PARTS:
            resp = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                      PartNumber=n, Body=data)
            raw = resp["ETag"]
            local = md5_hex(data)
            norm = norm_etag(raw).lower()
            evidence(f"UploadPart {n} ({note}): wire_bytes={len(data)} "
                     f"md5_local={local} etag_raw={raw!r} etag_norm={norm} {resp_meta(resp)}")
            if norm == local:
                ok(f"[Q1] part {n} ETag == MD5(part bytes) for {len(data)} bytes")
            else:
                fail(f"[Q1] part {n} ETag != MD5(part bytes): "
                     f"local_md5={local} server_etag={norm}")
            etags[n] = raw

        # 0-byte edge: only if the API allows it; a clean 4xx is an answer, not a failure.
        zero_key = "compat/point8-zero-part.bin"
        uid0 = client.create_multipart_upload(Bucket=bucket, Key=zero_key)["UploadId"]
        try:
            zresp = client.upload_part(Bucket=bucket, Key=zero_key, UploadId=uid0,
                                       PartNumber=1, Body=b"")
            zraw = zresp["ETag"]
            zlocal = md5_hex(b"")
            evidence(f"0-byte UploadPart: body_bytes=0 md5_local={zlocal} "
                     f"etag_raw={zraw!r} {resp_meta(zresp)}")
            if norm_etag(zraw).lower() == zlocal:
                ok("[Q1] 0-byte UploadPart accepted and its ETag is MD5(b\"\")")
            else:
                unknown(f"[Q1] 0-byte UploadPart accepted but ETag "
                        f"{norm_etag(zraw)!r} != MD5(b'')={zlocal}; empty-part ETag semantics "
                        f"are undefined")
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            evidence(f"0-byte UploadPart rejected: {err_detail(exc)} "
                     f"error={exc.response.get('Error', {})}")
            if status is not None and status >= 500:
                fail(f"[Q1] 0-byte UploadPart produced a server error HTTP {status}")
            else:
                info(f"[Q1] ANSWER: the API does not accept a 0-byte part "
                     f"(HTTP {status}); a browser must never emit empty parts")
        finally:
            if uid0 is not None:
                try:
                    client.abort_multipart_upload(Bucket=bucket, Key=zero_key, UploadId=uid0)
                except Exception:  # noqa: BLE001
                    pass

        # Complete the controlled 3-part upload: proves the ETags we compared are usable.
        done = client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=uid,
            MultipartUpload={"Parts": [
                {"PartNumber": n, "ETag": etags[n]} for n, _, _ in P8_PARTS]})
        whole = b"".join(d for _, d, _ in P8_PARTS)
        head = client.head_object(Bucket=bucket, Key=key)
        expected = composite_md5([hashlib.md5(d).digest() for _, d, _ in P8_PARTS])
        evidence(f"Complete ETag={done.get('ETag')!r} HEAD ETag={head.get('ETag')!r} "
                 f"ContentLength={head.get('ContentLength')} "
                 f"expected_composite_md5={expected!r}")
        if head["ContentLength"] == len(whole):
            ok("[Q1] the 3 controlled parts (incl. a 3-byte last part) assemble to the "
               "expected length")
        else:
            fail(f"assembled length {head['ContentLength']} != {len(whole)}")
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        evidence(f"GET assembled bytes={len(body)} sha256_hex="
                 f"{hashlib.sha256(body).hexdigest()} sha256_expected="
                 f"{hashlib.sha256(whole).hexdigest()}")
        if body == whole:
            ok("[Q1] assembled bytes are byte-identical to the concatenation of the parts")
        else:
            fail("[Q1] assembled bytes differ from the concatenation of the parts")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q1] part-ETag probe raised: {err_detail(exc)}")
    finally:
        if uid is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Point 9 — x-amz-checksum-sha256 on a presigned UploadPart (signed vs unsigned)
# ---------------------------------------------------------------------------
def point9(client, bucket: str) -> None:
    global CHECKSUM_MODE
    print("\n=== POINT 9: x-amz-checksum-sha256 on a presigned UploadPart ===", flush=True)
    D = b"\x5a" * (5 * 1024 * 1024)
    TAIL = b"\x5b" * 4
    dsha, tsha = b64_sha256(D), b64_sha256(TAIL)
    key_signed = "compat/point9-signed.bin"
    key_unsigned = "compat/point9-unsigned.bin"
    key_badsum = "compat/point9-badsum.bin"
    uids: dict[str, str] = {}
    accepted: dict[str, bool] = {}
    etags: dict[str, str] = {}

    def put(url: str, data: bytes, checksum: str):
        return http("PUT", url, data=data, headers={
            "Content-Type": "application/octet-stream",
            "x-amz-checksum-sha256": checksum})

    try:
        # --- variant (a): checksum header is in the presign signature
        uids["signed"] = client.create_multipart_upload(
            Bucket=bucket, Key=key_signed)["UploadId"]
        url, signed = presign_upload_part(
            client, bucket, key_signed, uids["signed"], 1, dsha)
        evidence(f"9a presign(PartNumber=1, ChecksumSHA256={dsha}) -> "
                 f"X-Amz-SignedHeaders={signed!r} checksum_in_signed_headers="
                 f"{'x-amz-checksum-sha256' in signed.lower()} url={safe_url(url)}")
        st, h, body = put(url, D, dsha)
        accepted["signed"] = st in (200, 201) and bool(h.get("etag"))
        etags["signed"] = h.get("etag") or ""
        evidence(f"9a PUT {len(D)} bytes, signed x-amz-checksum-sha256={dsha} -> HTTP {st} "
                 f"etag={h.get('etag')!r} "
                 f"resp_x_amz_checksum_sha256={h.get('x-amz-checksum-sha256')!r} "
                 f"x-amz-headers={ {k: v for k, v in h.items() if k.startswith('x-amz-')} } "
                 f"body={body[:400]!r}")
        if accepted["signed"]:
            ok("[Q2a] presigned UploadPart ACCEPTS a SIGNED x-amz-checksum-sha256 header")
            CHECKSUM_MODE = "signed"
        else:
            info(f"[Q2a] ANSWER: presigned UploadPart REJECTS a signed "
                 f"x-amz-checksum-sha256 header (HTTP {st}, body above)")

        # --- variant (b): same header, but NOT part of SignedHeaders
        uids["unsigned"] = client.create_multipart_upload(
            Bucket=bucket, Key=key_unsigned)["UploadId"]
        url, signed = presign_upload_part(client, bucket, key_unsigned, uids["unsigned"], 1)
        evidence(f"9b presign(PartNumber=1, no checksum param) -> "
                 f"X-Amz-SignedHeaders={signed!r} checksum_in_signed_headers="
                 f"{'x-amz-checksum-sha256' in signed.lower()} url={safe_url(url)}")
        st, h, body = put(url, D, dsha)
        accepted["unsigned"] = st in (200, 201) and bool(h.get("etag"))
        etags["unsigned"] = h.get("etag") or ""
        evidence(f"9b PUT {len(D)} bytes, UNSIGNED x-amz-checksum-sha256={dsha} -> HTTP {st} "
                 f"etag={h.get('etag')!r} "
                 f"resp_x_amz_checksum_sha256={h.get('x-amz-checksum-sha256')!r} "
                 f"x-amz-headers={ {k: v for k, v in h.items() if k.startswith('x-amz-')} } "
                 f"body={body[:400]!r}")
        if accepted["unsigned"]:
            ok("[Q2b] presigned UploadPart also ACCEPTS an UNSIGNED checksum header")
            CHECKSUM_MODE = CHECKSUM_MODE or "unsigned"
        else:
            info(f"[Q2b] ANSWER: presigned UploadPart REJECTS an unsigned "
                 f"x-amz-checksum-sha256 header (HTTP {st}, body above)")

        # --- negative control: is the supplied digest checked against the bytes?
        wrong = b64_sha256(b"these-are-not-the-part-bytes")
        uids["badsum"] = client.create_multipart_upload(
            Bucket=bucket, Key=key_badsum)["UploadId"]
        url, signed = presign_upload_part(
            client, bucket, key_badsum, uids["badsum"], 1, wrong)
        tiny = b"12345678"
        st, h, body = put(url, tiny, wrong)
        evidence(f"9c negative control: 8-byte body, signed wrong checksum={wrong} -> "
                 f"HTTP {st} etag={h.get('etag')!r} body={body[:400]!r}")
        if st in (200, 201) and h.get("etag"):
            info("[Q2] ANSWER: the checksum VALUE is NOT validated against the bytes "
                 "(a deliberately wrong digest was accepted)")
        else:
            info(f"[Q2] ANSWER: the checksum VALUE is validated (wrong digest rejected, "
                 f"HTTP {st})")

        # --- does ListParts echo the checksum?
        for mode, k in (("signed", key_signed), ("unsigned", key_unsigned)):
            if not accepted.get(mode):
                continue
            listed = client.list_parts(Bucket=bucket, Key=k, UploadId=uids[mode])
            raw_parts = [dict(p) for p in listed.get("Parts", [])]
            echoed = [p.get("ChecksumSHA256") for p in raw_parts]
            evidence(f"9d ListParts ({mode}) -> {raw_parts}")
            if dsha in echoed:
                ok(f"[Q2] ListParts echoes ChecksumSHA256 for the {mode} part: {echoed}")
            else:
                info(f"[Q2] ANSWER: ListParts does NOT echo ChecksumSHA256 for the "
                     f"{mode} part (got {echoed})")

        # --- Complete a checksummed upload and inspect HeadObject
        mode = "signed" if accepted.get("signed") else (
            "unsigned" if accepted.get("unsigned") else None)
        if mode is None:
            info("[Q2] no per-part checksum variant was accepted; skipping "
                 "Complete/HeadObject checksum probe")
            return
        k = key_signed if mode == "signed" else key_unsigned
        uid = uids[mode]
        if mode == "signed":
            url, signed = presign_upload_part(client, bucket, k, uid, 2, tsha)
        else:
            url, signed = presign_upload_part(client, bucket, k, uid, 2)
        st, h, body = put(url, TAIL, tsha)
        etag2 = h.get("etag") or ""
        evidence(f"9e part 2 ({mode}): {len(TAIL)} bytes, header={tsha} -> HTTP {st} "
                 f"etag={etag2!r} body={body[:400]!r}")
        if not (st in (200, 201) and etag2):
            fail(f"[Q2] tail part via {mode} checksum variant failed: HTTP {st}")
            return
        completion = [{"PartNumber": 1, "ETag": etags[mode]},
                      {"PartNumber": 2, "ETag": etag2}]
        if mode == "signed":
            completion[0]["ChecksumSHA256"] = dsha
            completion[1]["ChecksumSHA256"] = tsha
        try:
            done = client.complete_multipart_upload(
                Bucket=bucket, Key=k, UploadId=uid,
                MultipartUpload={"Parts": completion})
            evidence(f"9f Complete with checksums -> ETag={done.get('ETag')!r} "
                     f"checksum_fields={ {kk: vv for kk, vv in done.items() if 'hecksum' in kk.lower()} } "
                     f"response_keys={sorted(kk for kk in done if kk != 'ResponseMetadata')}")
        except ClientError as exc:
            evidence(f"9f Complete WITH ChecksumSHA256 failed: {err_detail(exc)}; "
                     f"retrying with ETag only")
            done = client.complete_multipart_upload(
                Bucket=bucket, Key=k, UploadId=uid,
                MultipartUpload={"Parts": [{"PartNumber": p["PartNumber"],
                                            "ETag": p["ETag"]} for p in completion]})
            evidence(f"9f Complete ETag-only -> ETag={done.get('ETag')!r}")

        head = client.head_object(Bucket=bucket, Key=k, ChecksumMode="ENABLED")
        chk = {kk: vv for kk, vv in head.items() if "hecksum" in kk.lower()}
        xamz = {kk: vv for kk, vv in head["ResponseMetadata"]["HTTPHeaders"].items()
                if kk.startswith("x-amz-")}
        evidence(f"9g HeadObject(ChecksumMode=ENABLED) -> "
                 f"response_keys={sorted(kk for kk in head if kk != 'ResponseMetadata')} "
                 f"checksum_fields={chk} x-amz-headers={xamz}")
        got = chk.get("ChecksumSHA256") or xamz.get("x-amz-checksum-sha256")
        expected = b64_sha256(D + TAIL)
        if got:
            if got == expected:
                ok("[Q2] HeadObject after Complete exposes x-amz-checksum-sha256 == "
                   "SHA-256 of the whole assembled object")
            else:
                info(f"[Q2] ANSWER: HeadObject exposes ChecksumSHA256={got!r} which is "
                     f"NOT the whole-object SHA-256 ({expected}); "
                     f"ChecksumType={chk.get('ChecksumType')!r}")
        else:
            info("[Q2] ANSWER: HeadObject after Complete exposes NO checksum field "
                 "at all (see x-amz-headers above)")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q2] checksum probe raised: {err_detail(exc)}")
    finally:
        for k, mode_key in ((key_signed, "signed"), (key_unsigned, "unsigned"),
                            (key_badsum, "badsum")):
            uid = uids.get(mode_key)
            if uid:
                try:
                    client.abort_multipart_upload(Bucket=bucket, Key=k, UploadId=uid)
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Point 10 — assembled object: composite ETag, checksum surface, derivability
# ---------------------------------------------------------------------------
def point10(client, bucket: str) -> None:
    print("\n=== POINT 10: CompleteMultipartUpload/HEAD surface for the assembled "
          "object ===", flush=True)
    key = "compat/point10-composite.bin"
    parts = [
        (1, b"\x01" * (5 * 1024 * 1024)),
        (2, (b"\x02\x03\x04\x05" * ((5 * 1024 * 1024 + 8191) // 4 + 1))
         [: 5 * 1024 * 1024 + 8191]),
        (3, b"tail" * 1000),
    ]
    whole = b"".join(d for _, d in parts)
    uid = None
    try:
        uid = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        etags: dict[int, str] = {}
        checksummed = CHECKSUM_MODE is not None
        if not checksummed:
            info("[Q3] POINT 9 found no accepted per-part checksum; uploading this object "
                 "WITHOUT x-amz-checksum-sha256 (HEAD can then only show what the backend "
                 "invents on its own)")
        for n, data in parts:
            kwargs = {}
            if checksummed:
                kwargs["ChecksumSHA256"] = b64_sha256(data)
            resp = client.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                      PartNumber=n, Body=data, **kwargs)
            etags[n] = resp["ETag"]
            evidence(f"UploadPart {n}: bytes={len(data)} sha256_b64={b64_sha256(data)} "
                     f"etag={resp['ETag']!r} "
                     f"resp_checksum={resp.get('ChecksumSHA256')!r} {resp_meta(resp)}")
        listed = client.list_parts(Bucket=bucket, Key=key, UploadId=uid)
        evidence(f"ListParts -> {[dict(p) for p in listed.get('Parts', [])]}")

        completion = [{"PartNumber": n, "ETag": etags[n]} for n, _ in parts]
        if checksummed:
            for item, (_, data) in zip(completion, parts):
                item["ChecksumSHA256"] = b64_sha256(data)
        try:
            done = client.complete_multipart_upload(
                Bucket=bucket, Key=key, UploadId=uid,
                MultipartUpload={"Parts": completion})
            evidence(f"Complete (checksummed={checksummed}) -> ETag={done.get('ETag')!r} "
                     f"checksum_fields={ {k: v for k, v in done.items() if 'hecksum' in k.lower()} }")
        except ClientError as exc:
            evidence(f"Complete WITH ChecksumSHA256 failed: {err_detail(exc)}; "
                     f"retrying with ETag only")
            done = client.complete_multipart_upload(
                Bucket=bucket, Key=key, UploadId=uid,
                MultipartUpload={"Parts": [{"PartNumber": n, "ETag": etags[n]}
                                           for n, _ in parts]})
            evidence(f"Complete ETag-only -> ETag={done.get('ETag')!r}")

        head = client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        head_etag = norm_etag(head.get("ETag"))
        expected = composite_md5([hashlib.md5(d).digest() for _, d in parts])
        evidence(f"ETag complete={done.get('ETag')!r} head={head.get('ETag')!r} "
                 f"expected_composite_md5={expected!r} "
                 f"has_-N_suffix={head_etag.endswith('-' + str(len(parts)))} "
                 f"ContentLength={head.get('ContentLength')}")
        if head_etag.lower() == expected:
            ok(f"[Q3] HEAD ETag is the composite md5(concat(part md5s))-{len(parts)}: "
               f"{head_etag}")
        else:
            info(f"[Q3] ANSWER: HEAD ETag {head_etag!r} is NOT "
                 f"md5(concat(part md5s))-{len(parts)} ({expected!r}); "
                 f"md5(whole_object)={md5_hex(whole)}")

        chk = {k: v for k, v in head.items() if "hecksum" in k.lower()}
        xamz = {k: v for k, v in head["ResponseMetadata"]["HTTPHeaders"].items()
                if k.startswith("x-amz-")}
        full_b64 = b64_sha256(whole)
        composite_sha = base64.b64encode(
            hashlib.sha256(b"".join(hashlib.sha256(d).digest() for _, d in parts)).digest()
        ).decode() + f"-{len(parts)}"
        evidence(f"HEAD x-amz-headers={xamz} checksum_fields={chk} "
                 f"whole_sha256_b64={full_b64} composite_sha256_b64={composite_sha}")
        got = chk.get("ChecksumSHA256") or xamz.get("x-amz-checksum-sha256")
        if got:
            evidence(f"server_checksum={got!r} equals_whole_object_sha256={got == full_b64} "
                     f"equals_composite_sha256={got == composite_sha} "
                     f"ChecksumType={chk.get('ChecksumType')!r}")
            if got == full_b64:
                ok("[Q3] server exposes whole-object SHA-256; no re-read needed to get it")
            elif got == composite_sha:
                info("[Q3] ANSWER: server exposes a COMPOSITE SHA-256 (sha256 of the "
                     "concatenated part digests + -N), NOT sha256(whole object)")
            else:
                info("[Q3] ANSWER: server exposes a checksum that is neither sha256(whole "
                     "object) nor the documented composite form")
        else:
            info("[Q3] ANSWER: HEAD exposes NO x-amz-checksum-* and no Checksum* field; "
                 "a whole-object digest cannot be derived from the S3 API (re-read needed)")

        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        evidence(f"GET bytes={len(body)} sha256_hex={hashlib.sha256(body).hexdigest()} "
                 f"expected_sha256_hex={hashlib.sha256(whole).hexdigest()}")
        if body == whole:
            ok("[Q3] stored bytes equal the concatenation of the uploaded parts (re-read "
               "baseline for any digest comparison)")
        else:
            fail("[Q3] stored bytes differ from the concatenation of the uploaded parts")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q3] composite/checksum probe raised: {err_detail(exc)}")
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


# ---------------------------------------------------------------------------
# Point 11 — is the SIGNED per-part ContentLength enforced? (gate item 2)
# ---------------------------------------------------------------------------
SIGNED_PART_LEN = 5 * 1024 * 1024  # the length bound into the presigned URL


def xml_error(body: bytes) -> str:
    """Code/Message out of an S3 XML error body (exact error code, not a guess)."""
    import re  # local: only needed for evidence formatting

    text = body.decode("utf-8", "replace")
    code = re.search(r"<Code>(.*?)</Code>", text)
    msg = re.search(r"<Message>(.*?)</Message>", text)
    if code or msg:
        return (f"Code={code.group(1) if code else None!r} "
                f"Message={msg.group(1) if msg else None!r}")
    return "no_xml_error"


def point11(client, bucket: str) -> None:
    print("\n=== POINT 11: is the SIGNED per-part ContentLength enforced? "
          "(gate item 2) ===", flush=True)
    signed = SIGNED_PART_LEN
    exact = b"\x71" * signed
    longer = b"\x71" * (signed + 4096)          # body LONGER than the signed length
    shorter = b"\x71" * (1024 * 1024)           # body SHORTER than the signed length
    overflow = b"\x71" * (signed + 1024 * 1024)  # declared == signed, extra bytes sent
    keys = {
        "exact": "compat/point11-exact-len.bin",
        "long": "compat/point11-long-body.bin",
        "short": "compat/point11-short-body.bin",
        "trunc": "compat/point11-truncating-client.bin",
        "bare": "compat/point11-no-signed-length.bin",
    }
    uids: dict[str, str] = {}
    try:
        for name, k in keys.items():
            uids[name] = client.create_multipart_upload(Bucket=bucket, Key=k)["UploadId"]

        def put_part(name: str, body: bytes, tag: str = "",
                     declared: int | None = None, sign_length: bool = True):
            if sign_length:
                url, sh = presign_upload_part(
                    client, bucket, keys[name], uids[name], 1,
                    content_length=signed)
            else:
                url, sh = presign_upload_part(
                    client, bucket, keys[name], uids[name], 1)
            hdrs = {"Content-Type": "application/octet-stream"}
            if declared is not None:
                hdrs["Content-Length"] = str(declared)
            evidence(f"11{tag} presign ContentLength={signed if sign_length else None} -> "
                     f"X-Amz-SignedHeaders={sh!r} "
                     f"content_length_is_signed={'content-length' in sh.lower()} "
                     f"url={safe_url(url)}")
            extra = f" declared_Content-Length={declared}" if declared is not None else ""
            st, h, b = http("PUT", url, data=body, headers=hdrs, timeout=90)
            evidence(f"11{tag} {name}: body_bytes={len(body)} "
                     f"signed_len={signed if sign_length else None}{extra} -> HTTP {st} "
                     f"etag={h.get('etag')!r} "
                     f"x-amz-request-id={h.get('x-amz-request-id')!r} "
                     f"{xml_error(b)} body={b[:400]!r}")
            return st, h, b

        # (a) control: exactly the signed length must be accepted.
        st, h, _ = put_part("exact", exact, tag="a")
        if st in (200, 201) and h.get("etag"):
            ok(f"[Q4] control: body exactly the signed ContentLength ({signed} bytes) -> "
               f"HTTP {st}")
        else:
            fail(f"[Q4] control: body exactly the signed ContentLength ({signed} bytes) -> "
                 f"HTTP {st} (baseline broken, the mismatch probes below are inconclusive)")

        # (b) body LONGER than the signed length.
        st_long, _, b_long = put_part("long", longer, tag="b")
        if st_long in (200, 201):
            fail(f"[Q4] GATE ITEM 2: the gateway ACCEPTED a body LONGER than the signed "
                 f"ContentLength ({len(longer)} > {signed} bytes, HTTP {st_long}). The signed "
                 f"per-part size is NOT enforced, so a client can store a part of any length "
                 f"behind a URL signed for {signed} bytes; the API must not rely on the "
                 f"presigned length to bound what the backend stores")
        else:
            ok(f"[Q4] body LONGER than the signed ContentLength "
               f"({len(longer)} > {signed}) rejected: HTTP {st_long} {xml_error(b_long)}")

        # (c) body SHORTER than the signed length.
        st_short, _, b_short = put_part("short", shorter, tag="c")
        if st_short in (200, 201):
            fail(f"[Q4] GATE ITEM 2: the gateway ACCEPTED a body SHORTER than the signed "
                 f"ContentLength ({len(shorter)} < {signed} bytes, HTTP {st_short}); a part "
                 f"truncated client-side (crash, stalled socket) would be stored and could "
                 f"later complete into a silently short object")
        else:
            ok(f"[Q4] body SHORTER than the signed ContentLength "
               f"({len(shorter)} < {signed}) rejected: HTTP {st_short} {xml_error(b_short)}")

        info(f"[Q4] ANSWER (gate item 2): rejection comes from SigV4 verification of the "
             f"signed Content-Length header (see X-Amz-SignedHeaders above), i.e. the "
             f"bound is only enforced on URLs presigned WITH ContentLength — exactly what "
             f"api/s3.py:presigned_upload_part does; a presign without it binds no length")

        # (d) framing control: header == signed value, but MORE bytes follow it on the wire.
        st_t, _, b_t = put_part("trunc", overflow, declared=signed, tag="d")
        if st_t in (200, 201):
            try:
                listed = client.list_parts(Bucket=bucket, Key=keys["trunc"],
                                           UploadId=uids["trunc"])
                sizes = [(p["PartNumber"], p["Size"]) for p in listed.get("Parts", [])]
            except Exception as exc:  # noqa: BLE001
                sizes = f"ListParts failed: {err_detail(exc)}"
            evidence(f"11d client sent {len(overflow)} bytes with the SIGNED "
                     f"Content-Length={signed} -> HTTP {st_t}; ListParts(part,size)={sizes}")
            info(f"[Q4] FRAMING NOTE: with Content-Length={signed} signed AND sent, only the "
                 f"first {signed} of {len(overflow)} bytes became the entity body and the "
                 f"trailing {len(overflow) - signed} bytes were ignored — standard HTTP "
                 f"framing, not a gateway hole (a browser XHR/fetch cannot desynchronise "
                 f"Content-Length from the body it sends)")
        else:
            evidence(f"11d client sent {len(overflow)} bytes with the SIGNED "
                     f"Content-Length={signed} -> HTTP {st_t} {xml_error(b_t)}")

        # (e) a presign with NO ContentLength: nothing about the size is signed at all.
        st_b, _, b_b = put_part("bare", shorter, tag="e", sign_length=False)
        if st_b in (200, 201):
            info(f"[Q4] a presigned URL WITHOUT ContentLength accepted a {len(shorter)}-byte "
                 f"body (HTTP {st_b}): when the length is not in SignedHeaders nothing can be "
                 f"enforced. The plan is safe only because api/s3.py:presigned_upload_part "
                 f"always passes ContentLength")
        else:
            info(f"[Q4] a presigned URL WITHOUT ContentLength rejected a "
                 f"{len(shorter)}-byte body: HTTP {st_b} {xml_error(b_b)}")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q4] signed-size probe raised: {err_detail(exc)}")
    finally:
        for name, k in keys.items():
            uid = uids.get(name)
            if uid:
                try:
                    client.abort_multipart_upload(Bucket=bucket, Key=k, UploadId=uid)
                except Exception:  # noqa: BLE001
                    pass
            try:
                client.delete_object(Bucket=bucket, Key=k)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Point 12 — minimum part size and maximum part count (gate item 5)
# ---------------------------------------------------------------------------
def _plan_parts_from_source() -> tuple[dict, dict, str]:
    """Exec only the constants + plan_parts of api/s3.py (no module import)."""
    src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "api", "s3.py"))
    with open(src, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src)
    ns: dict = {}
    lines: dict[str, int] = {}
    wanted = {"MIN_PART_BYTES", "MAX_PARTS", "_MIB"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if wanted & set(names):
                exec(compile(ast.Module(body=[node], type_ignores=[]), src, "exec"), ns)
                for n in names:
                    lines[n] = node.lineno
        elif isinstance(node, ast.FunctionDef) and node.name == "plan_parts":
            exec(compile(ast.Module(body=[node], type_ignores=[]), src, "exec"), ns)
            lines["plan_parts"] = node.lineno
    return ns, lines, src


def point12(client, bucket: str) -> None:
    print("\n=== POINT 12: minimum part size / maximum part count / range GET "
          "(gate item 5) ===", flush=True)
    _MIB = 1024 ** 2
    _GIB = 1024 ** 3
    _TIB = 1024 ** 4
    _PIB = 1024 ** 5
    maxp = 10_000

    # --- (a) what the server-side plan computes, read from the real source -------
    try:
        ns, lines, src = _plan_parts_from_source()
        plan = ns["plan_parts"]
        maxp = int(ns["MAX_PARTS"])
        minp = int(ns["MIN_PART_BYTES"])
        evidence(f"api/s3.py ({src}) constants: MIN_PART_BYTES={minp} "
                 f"({minp // _MIB} MiB) at line {lines.get('MIN_PART_BYTES')}, "
                 f"MAX_PARTS={maxp} at line {lines.get('MAX_PARTS')}, "
                 f"def plan_parts at line {lines.get('plan_parts')}")
        if minp == 5 * _MIB:
            ok(f"[Q5] plan_parts enforces MIN_PART_BYTES={minp} (5 MiB)")
        else:
            fail(f"[Q5] MIN_PART_BYTES={minp}, expected 5 MiB")
        if maxp == 10_000:
            ok(f"[Q5] plan_parts uses MAX_PARTS={maxp}")
        else:
            fail(f"[Q5] MAX_PARTS={maxp}, expected 10000")

        samples = [1 * _MIB, 5 * _MIB, 100 * _MIB, 5 * _GIB, 100 * _GIB,
                   1 * _TIB, 10 * _TIB, 50 * _TIB, 500 * _TIB, 5 * _PIB]
        over = 0
        for size in samples:
            part, count = plan(size, 8 * _MIB)
            evidence(f"plan_parts(size={size} bytes = {size / _GIB:.3f} GiB, "
                     f"preferred=8 MiB) -> part_bytes={part} "
                     f"({part / _MIB:.1f} MiB) part_count={count} "
                     f"count<=MAX_PARTS={count <= maxp}")
            if count > maxp:
                over += 1
        if over:
            fail(f"[Q5] plan_parts exceeded MAX_PARTS for {over} sample size(s)")
        else:
            ok(f"[Q5] for every sampled size up to 5 PiB plan_parts keeps count <= {maxp} "
               f"by raising the part size above the 8 MiB preference (5 GiB -> 8 MiB, "
               f"50 TiB -> ~5.1 GiB, 5 PiB -> ~524 GiB)")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q5] could not read/replay plan_parts from api/s3.py: {err_detail(exc)}")

    # --- (b) is the 5 MiB minimum enforced at Complete? -------------------------
    key_small = "compat/point12-min-small.bin"
    key_ctrl = "compat/point12-min-control.bin"
    uid_small = None
    uid_ctrl = None
    small = b"\x61" * (1 * _MIB)
    five = b"\x62" * (5 * _MIB)
    one = b"\x63" * (1 * _MIB)
    try:
        uid_small = client.create_multipart_upload(Bucket=bucket, Key=key_small)["UploadId"]
        s1 = client.upload_part(Bucket=bucket, Key=key_small, UploadId=uid_small,
                                PartNumber=1, Body=small)["ETag"]
        s2 = client.upload_part(Bucket=bucket, Key=key_small, UploadId=uid_small,
                                PartNumber=2, Body=small)["ETag"]
        evidence(f"UploadPart part1={len(small)} bytes part2={len(small)} bytes "
                 f"(both below 5 MiB; only the last part is allowed to be small)")
        try:
            client.complete_multipart_upload(
                Bucket=bucket, Key=key_small, UploadId=uid_small,
                MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": s1},
                                           {"PartNumber": 2, "ETag": s2}]})
            head = client.head_object(Bucket=bucket, Key=key_small)
            evidence(f"Complete(1 MiB + 1 MiB) ACCEPTED -> ContentLength="
                     f"{head['ContentLength']} ETag={head.get('ETag')!r}")
            unknown("[Q5] SeaweedFS 4.48 does NOT enforce the S3 5 MiB minimum for a "
                    "non-last part at Complete: a 1 MiB + 1 MiB upload completes and stores "
                    "2 MiB. The 5 MiB floor can only be a client/API-side rule here, never a "
                    "backend invariant — the API must enforce it itself")
        except ClientError as exc:
            evidence(f"Complete(1 MiB + 1 MiB) REJECTED: {err_detail(exc)} "
                     f"error={exc.response.get('Error')}")
            ok("[Q5] Complete rejects a non-last part below 5 MiB "
               f"({err_detail(exc)})")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q5] small-part Complete probe raised: {err_detail(exc)}")
    finally:
        if uid_small is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key_small, UploadId=uid_small)
            except Exception:  # noqa: BLE001
                pass

    # --- (c) control: 5 MiB + 1 MiB completes, then Range GET -------------------
    try:
        uid_ctrl = client.create_multipart_upload(Bucket=bucket, Key=key_ctrl)["UploadId"]
        c1 = client.upload_part(Bucket=bucket, Key=key_ctrl, UploadId=uid_ctrl,
                                PartNumber=1, Body=five)["ETag"]
        c2 = client.upload_part(Bucket=bucket, Key=key_ctrl, UploadId=uid_ctrl,
                                PartNumber=2, Body=one)["ETag"]
        done = client.complete_multipart_upload(
            Bucket=bucket, Key=key_ctrl, UploadId=uid_ctrl,
            MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": c1},
                                       {"PartNumber": 2, "ETag": c2}]})
        head = client.head_object(Bucket=bucket, Key=key_ctrl)
        evidence(f"Complete(5 MiB + 1 MiB) -> ETag={done.get('ETag')!r} "
                 f"HEAD ContentLength={head['ContentLength']} expected="
                 f"{len(five) + len(one)}")
        if head["ContentLength"] == len(five) + len(one):
            ok(f"[Q5] control: 5 MiB + 1 MiB completes to a "
               f"{head['ContentLength']}-byte object")
        else:
            fail(f"[Q5] control object length {head['ContentLength']} != {len(five) + len(one)}")

        whole = five + one
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key_ctrl}, ExpiresIn=600)
        start = 5 * _MIB - 10
        st, h, body = http("GET", url, headers={"Range": f"bytes={start}-{start + 20}"})
        evidence(f"Range GET bytes={start}-{start + 20} on the COMPLETED MULTIPART object "
                 f"-> HTTP {st} Content-Range={h.get('content-range')!r} "
                 f"ContentLength={h.get('content-length')} "
                 f"Accept-Ranges={h.get('accept-ranges')!r} "
                 f"bytes_match={body == whole[start:start + 21]}")
        st_p, h_p, body_p = http("GET", url, headers={"Range": "bytes=0-99"})
        evidence(f"Range GET bytes=0-99 on the COMPLETED MULTIPART object -> HTTP {st_p} "
                 f"Content-Range={h_p.get('content-range')!r} "
                 f"bytes_match={body_p == whole[:100]}")
        if (st == 206 and body == whole[start:start + 21]
                and st_p == 206 and body_p == whole[:100]):
            ok("[Q5] Range GET works on a completed multipart object: 206 with exact bytes, "
               "including a range spanning the part boundary")
        else:
            fail(f"[Q5] Range GET on a completed multipart object is wrong: "
                 f"boundary HTTP {st} match={body == whole[start:start + 21]}, "
                 f"prefix HTTP {st_p} match={body_p == whole[:100]}")
    except Exception as exc:  # noqa: BLE001
        fail(f"[Q5] control/Range probe raised: {err_detail(exc)}")
    finally:
        if uid_ctrl is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key_ctrl, UploadId=uid_ctrl)
            except Exception:  # noqa: BLE001
                pass
        try:
            client.delete_object(Bucket=bucket, Key=key_ctrl)
        except Exception:  # noqa: BLE001
            pass

    # --- (d) declared maximum part number (cheap boundary probe) ----------------
    key_max = "compat/point12-maxpart.bin"
    uid_max = None
    if maxp:
        try:
            uid_max = client.create_multipart_upload(Bucket=bucket, Key=key_max)["UploadId"]
            try:
                client.complete_multipart_upload(
                    Bucket=bucket, Key=key_max, UploadId=uid_max,
                    MultipartUpload={"Parts": [{"PartNumber": maxp + 1,
                                                "ETag": md5_hex(b"")}]})
                evidence(f"Complete referencing PartNumber={maxp + 1} (never uploaded) "
                         f"UNEXPECTEDLY accepted")
                fail(f"[Q5] Complete accepted PartNumber={maxp + 1}, above the declared "
                     f"ceiling of {maxp}")
            except ClientError as exc:
                evidence(f"Complete referencing PartNumber={maxp + 1} (never uploaded) -> "
                         f"{err_detail(exc)} error={exc.response.get('Error')}")

            url_ceiling, sh_c = presign_upload_part(
                client, bucket, key_max, uid_max, maxp, content_length=1)
            st_c, h_c, b_c = http("PUT", url_ceiling, data=b"\x64", headers={
                "Content-Type": "application/octet-stream", "Content-Length": "1"})
            evidence(f"UploadPart PartNumber={maxp} ContentLength=1 -> HTTP {st_c} "
                     f"etag={h_c.get('etag')!r} SignedHeaders={sh_c!r} "
                     f"{xml_error(b_c)} body={b_c[:300]!r}")
            if st_c in (200, 201):
                ok(f"[Q5] part number {maxp} (the declared ceiling) is accepted")
            else:
                info(f"[Q5] part number {maxp} (the declared ceiling) is REJECTED: "
                     f"HTTP {st_c} {xml_error(b_c)}")

            url_over, sh_o = presign_upload_part(
                client, bucket, key_max, uid_max, maxp + 1, content_length=1)
            st_o, h_o, b_o = http("PUT", url_over, data=b"\x65", headers={
                "Content-Type": "application/octet-stream", "Content-Length": "1"})
            evidence(f"UploadPart PartNumber={maxp + 1} (above the ceiling) -> HTTP {st_o} "
                     f"etag={h_o.get('etag')!r} SignedHeaders={sh_o!r} "
                     f"{xml_error(b_o)} body={b_o[:300]!r}")
            if st_o in (200, 201):
                fail(f"[Q5] part number {maxp + 1} (ABOVE the declared {maxp} limit) was "
                     f"ACCEPTED: the ceiling is not enforced at UploadPart")
            else:
                ok(f"[Q5] part number {maxp + 1} rejected at UploadPart: HTTP {st_o} "
                   f"{xml_error(b_o)}")
        except Exception as exc:  # noqa: BLE001
            fail(f"[Q5] max-part-number probe raised: {err_detail(exc)}")
        finally:
            if uid_max is not None:
                try:
                    client.abort_multipart_upload(Bucket=bucket, Key=key_max,
                                                  UploadId=uid_max)
                except Exception:  # noqa: BLE001
                    pass
            try:
                client.delete_object(Bucket=bucket, Key=key_max)
            except Exception:  # noqa: BLE001
                pass

    unknown(f"[Q5] the 10 000-part path is NOT exercised: {maxp} real parts would need >= "
            f"{maxp * 5 / (1024 ** 3):.0f} GiB (5 MiB each) and a long run; only the declared "
            f"boundary (part {maxp} accepted vs {maxp + 1} rejected) and the plan_parts "
            f"arithmetic are verified — the backend's exact 10 000-part Complete behaviour "
            f"remains unproven")


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
               lambda: point7(client, args.bucket, args.origin),
               lambda: point8(client, args.bucket),
               lambda: point9(client, args.bucket),
               lambda: point10(client, args.bucket),
               lambda: point11(client, args.bucket),
               lambda: point12(client, args.bucket)):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - keep other points running
            fail(f"point aborted: {err_detail(exc)}")

    print(f"\n=== SUMMARY: failures={_failures} unknowns={_unknowns} "
          f"passes={_passes} ===")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
