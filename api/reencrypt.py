"""Re-encrypt objects stored before uploads requested SSE-S3.

    docker compose exec -T api python -m api.reencrypt            # dry run
    docker compose exec -T api python -m api.reencrypt --apply

Lists every object of every bucket (or ``--bucket``) and rewrites the ones the
storage does not report as ``AES256`` with a server-side copy onto themselves.
Content type and user metadata are preserved; the bytes never leave SeaweedFS.
SeaweedFS refuses a self-copy with ``MetadataDirective=COPY`` even when the
encryption changes, hence ``REPLACE`` with the original values.

The plaintext needles stay in the volume files until SeaweedFS compacts them:
run ``volume.vacuum -garbageThreshold=0.0001`` in ``weed shell`` afterwards.
Take a backup first (scripts/backup.sh).
"""
import argparse
import sys

from .config import settings
from .s3 import SSE_ALGORITHM, make_client


def iter_keys(client, bucket):
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            yield item["Key"]


def reencrypt(client, buckets, apply: bool, out=sys.stdout) -> dict:
    counts = {"encrypted": 0, "rewritten": 0, "pending": 0, "errors": 0}
    for bucket in buckets:
        for key in iter_keys(client, bucket):
            try:
                head = client.head_object(Bucket=bucket, Key=key)
                if head.get("ServerSideEncryption") == SSE_ALGORITHM:
                    counts["encrypted"] += 1
                    continue
                if not apply:
                    counts["pending"] += 1
                    continue
                client.copy_object(
                    Bucket=bucket, Key=key,
                    CopySource={"Bucket": bucket, "Key": key},
                    ServerSideEncryption=SSE_ALGORITHM,
                    MetadataDirective="REPLACE",
                    ContentType=head.get("ContentType", "binary/octet-stream"),
                    Metadata=head.get("Metadata", {}),
                )
                after = client.head_object(Bucket=bucket, Key=key)
                if (after.get("ServerSideEncryption") != SSE_ALGORITHM
                        or after.get("ContentLength") != head.get("ContentLength")):
                    raise RuntimeError("verification after copy failed")
                counts["rewritten"] += 1
            except Exception as exc:  # report and continue with the next object
                counts["errors"] += 1
                print(f"ERROR {bucket}: {type(exc).__name__}", file=out)
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="rewrite (default: dry run)")
    parser.add_argument("--bucket", action="append", help="limit to this bucket (repeatable)")
    args = parser.parse_args(argv)
    client = make_client(settings.s3_internal_endpoint, settings.s3_access_key,
                         settings.s3_secret_key, settings.s3_region)
    buckets = args.bucket or [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    counts = reencrypt(client, buckets, args.apply)
    mode = "apply" if args.apply else "dry-run"
    print(f"{mode}: buckets={len(buckets)} " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
