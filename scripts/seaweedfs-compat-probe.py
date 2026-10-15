#!/usr/bin/env python3
"""AURA / SeaweedFS transfer compatibility probe (MANUAL, DESTRUCTIVE-LITE).

This is the proposed acceptance gate for the multipart / checksum / Range work
described in docs/TRANSFER-ENGINE.md. It is NOT part of CI and must be run by a
human against a disposable bucket on the exact pinned SeaweedFS release.

It writes and deletes temporary objects, and it prints no secret material and no
full presigned URL (only HTTP status codes and the URL path).

Usage (explicit opt-in is required):

    export AURA_S3_ACCESS_KEY=...
    export AURA_S3_SECRET_KEY=...        # never pass secrets as CLI args
    python3 scripts/seaweedfs-compat-probe.py \
        --endpoint https://storage.example.test \
        --bucket aura-compat-probe \
        --i-understand-this-writes-to-the-endpoint

Exit code 0 = every probe passed; 1 = at least one failed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import boto3
from botocore.client import Config

PART_SIZE = 5 * 1024 * 1024  # 5 MiB: the classic S3 minimum part size (except the last)
SMALL = b"AURA compat probe payload %s" % hashlib.sha256(b"seed").digest()[:8]


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, label: str, detail: str = "") -> None:
        print(f"PASS  {label}{(' — ' + detail) if detail else ''}")

    def fail(self, label: str, detail: str = "") -> None:
        self.failures += 1
        print(f"FAIL  {label}{(' — ' + detail) if detail else ''}")

    def info(self, label: str, detail: str = "") -> None:
        print(f"INFO  {label}{(' — ' + detail) if detail else ''}")


def build_client(endpoint: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["AURA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["AURA_S3_SECRET_KEY"],
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def safe_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path


def http_request(method: str, url: str, data: bytes | None = None,
                 headers: dict | None = None, timeout: int = 60):
    """Perform an HTTP request and never raise on an HTTP error status.

    Returns ``(status, headers, body)``. Used to exercise *presigned* URLs the way
    a browser would (the API does not proxy the bytes), while still printing no
    query string.
    """
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def probe_single_put_get(r: Report, client, bucket: str) -> None:
    key = "probe/single.bin"
    try:
        client.put_object(Bucket=bucket, Key=key, Body=SMALL,
                          ContentType="application/octet-stream")
        head = client.head_object(Bucket=bucket, Key=key)
        if int(head["ContentLength"]) == len(SMALL):
            r.ok("single PUT + HEAD ContentLength")
        else:
            r.fail("single PUT HEAD ContentLength", str(head.get("ContentLength")))
        r.info("HEAD ETag", str(head.get("ETag")))
        r.info("HEAD ServerSideEncryption", str(head.get("ServerSideEncryption")))
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(body).hexdigest() == hashlib.sha256(SMALL).hexdigest():
            r.ok("GET round-trip SHA-256 matches")
        else:
            r.fail("GET round-trip SHA-256 mismatch")
        ranged = client.get_object(Bucket=bucket, Key=key, Range="bytes=0-3")["Body"].read()
        if ranged == SMALL[:4]:
            r.ok("Range GET returns the requested prefix")
        else:
            r.fail("Range GET prefix mismatch", repr(ranged[:16]))
    except Exception as exc:  # noqa: BLE001 - probe reports, never raises
        r.fail("single PUT/GET", f"{type(exc).__name__}: {exc}")
    finally:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def probe_presigned_expiry(r: Report, client, bucket: str) -> None:
    key = "probe/expiry.txt"
    try:
        client.put_object(Bucket=bucket, Key=key, Body=b"x")
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=2
        )
        r.info("presigned GET path", safe_path(url))
        time.sleep(4)
        try:
            client.get_object(Bucket=bucket, Key=key)  # direct call proves the object exists
            r.info("presigned target exists (direct GET)")
        except Exception as exc:  # noqa: BLE001
            r.fail("direct GET before expiry probe", type(exc).__name__)
        # The expiry itself is proven by the smoke suite / live test using an HTTP
        # client; here we only assert the URL is issued and carries an expiry.
        if "X-Amz-Expires=" in url:
            r.ok("presigned URL carries X-Amz-Expires")
        else:
            r.fail("presigned URL missing X-Amz-Expires")
    except Exception as exc:  # noqa: BLE001
        r.fail("presigned GET issuance", type(exc).__name__)
    finally:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def probe_multipart(r: Report, client, bucket: str) -> None:
    key = "probe/multipart.bin"
    part1 = b"\x01" * PART_SIZE
    part2 = b"\x02" * (PART_SIZE // 2)
    whole = part1 + part2
    want = hashlib.sha256(whole).hexdigest()
    upload_id = None
    try:
        created = client.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType="application/octet-stream"
        )
        upload_id = created["UploadId"]
        r.ok("CreateMultipartUpload", f"upload id present={bool(upload_id)}")

        # Part 1 goes through a PRESIGNED upload_part URL over HTTP: this is the
        # exact capability a browser would use, and the most backend-specific
        # point of the whole multipart flow. The URL query is never printed.
        etag1 = None
        part1_url = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": upload_id, "PartNumber": 1},
            ExpiresIn=300,
        )
        status, headers, _ = http_request(
            "PUT", part1_url, data=part1,
            headers={"Content-Type": "application/octet-stream"},
        )
        if status in (200, 201):
            etag1 = headers.get("ETag")
            r.ok("presigned UploadPart URL accepted", f"HTTP {status}")
        else:
            r.fail("presigned UploadPart URL", f"HTTP {status}")
        if not etag1:
            # Fall back to a direct call so the remaining checks still run; the
            # presigned-part failure above is already recorded.
            etag1 = client.upload_part(
                Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=1, Body=part1
            )["ETag"]

        p2 = client.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                                PartNumber=2, Body=part2)
        r.ok("UploadPart ×2")

        client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": [
                {"PartNumber": 1, "ETag": etag1},
                {"PartNumber": 2, "ETag": p2["ETag"]},
            ]},
        )
        head = client.head_object(Bucket=bucket, Key=key)
        etag = str(head.get("ETag", "")).strip('"')
        r.info("multipart ETag", etag)
        if "-" in etag:
            r.ok("multipart ETag is composite (not a single MD5/SHA-256)")
        else:
            r.info("multipart ETag has no '-' suffix (backend-specific)")
        if etag.replace("-", "") != want:
            r.info("multipart ETag differs from full-object SHA-256 (as expected)")

        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(body).hexdigest() == want:
            r.ok("multipart GET round-trip SHA-256 matches")
        else:
            r.fail("multipart GET round-trip SHA-256 mismatch")

        prefix = client.get_object(
            Bucket=bucket, Key=key, Range="bytes=0-9"
        )["Body"].read()
        if prefix == whole[:10]:
            r.ok("Range GET on a multipart object returns the requested prefix")
        else:
            r.fail("Range GET on a multipart object", repr(prefix[:16]))
    except Exception as exc:  # noqa: BLE001
        r.fail("multipart round trip", f"{type(exc).__name__}: {exc}")
    finally:
        if upload_id is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
                r.ok("AbortMultipartUpload (idempotent)")
            except Exception as exc:  # noqa: BLE001
                r.info("AbortMultipartUpload after complete", type(exc).__name__)
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def probe_small_part_policy(r: Report, client, bucket: str) -> None:
    """Discover the backend's minimum non-last part size (informational).

    AWS rejects a non-last part below 5 MiB at completion; some S3-compatible
    backends accept it. This is recorded, not asserted, so the AURA part size is
    chosen from the actual pinned release rather than an AWS assumption.
    """
    key = "probe/small-parts.bin"
    upload_id = None
    body = b"\x00" * (1024 * 1024)  # 1 MiB
    try:
        upload_id = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        p1 = client.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                                PartNumber=1, Body=body)
        p2 = client.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                                PartNumber=2, Body=body)
        try:
            client.complete_multipart_upload(
                Bucket=bucket, Key=key, UploadId=upload_id,
                MultipartUpload={"Parts": [
                    {"PartNumber": 1, "ETag": p1["ETag"]},
                    {"PartNumber": 2, "ETag": p2["ETag"]},
                ]},
            )
            r.info("small non-last part (<5 MiB)", "accepted by this backend")
        except Exception as exc:  # noqa: BLE001
            r.info("small non-last part (<5 MiB)", f"rejected: {type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001
        r.info("small-part policy probe", f"skipped: {type(exc).__name__}")
    finally:
        if upload_id is not None:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--i-understand-this-writes-to-the-endpoint",
        action="store_true",
        help="required acknowledgement: this probe creates and deletes objects",
    )
    args = parser.parse_args(argv)

    if not args.i_understand_this_writes_to_the_endpoint:
        print("Refusing to run without --i-understand-this-writes-to-the-endpoint",
              file=sys.stderr)
        return 2
    if not os.environ.get("AURA_S3_ACCESS_KEY") or not os.environ.get("AURA_S3_SECRET_KEY"):
        print("Set AURA_S3_ACCESS_KEY and AURA_S3_SECRET_KEY in the environment "
              "(never as CLI arguments).", file=sys.stderr)
        return 2

    r = Report()
    client = build_client(args.endpoint, args.region)
    probe_single_put_get(r, client, args.bucket)
    probe_presigned_expiry(r, client, args.bucket)
    probe_multipart(r, client, args.bucket)
    probe_small_part_policy(r, client, args.bucket)

    print()
    if r.failures:
        print(f"{r.failures} probe(s) FAILED against the pinned release.")
        return 1
    print("All probes passed. Record the image tag with this result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
