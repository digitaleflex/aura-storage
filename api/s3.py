"""S3 data-plane access. Keys stay server-side; browsers only get presigned URLs."""
import hashlib

import boto3
from botocore.client import Config


def make_client(endpoint: str, access_key: str, secret_key: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def make_clients(public_endpoint: str, internal_endpoint: str,
                 access_key: str, secret_key: str, region: str):
    """(presign_client, ops_client): presigning is local crypto (no network),
    so it uses the public base; all real calls use the internal endpoint."""
    presign = make_client(public_endpoint, access_key, secret_key, region)
    ops = make_client(internal_endpoint, access_key, secret_key, region)
    return presign, ops


def presigned_put(client, bucket: str, key: str, content_type: str, expires: int) -> str:
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )


def presigned_get(client, bucket: str, key: str, expires: int) -> str:
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
    )


class ObjectTooLarge(Exception):
    """Raised by stream_sha256 when the object exceeds the configured limit."""


def stream_sha256(body, max_bytes: int, chunk_bytes: int = 1024 * 1024):
    """Hash a streaming S3 body without ever holding the whole object in memory.

    Returns ``(total_bytes, hex_digest)``. Raises :class:`ObjectTooLarge` as soon
    as the accumulated size exceeds ``max_bytes`` so the API aborts early (#37).
    """
    digest = hashlib.sha256()
    total = 0
    for chunk in body.iter_chunks(chunk_size=chunk_bytes):
        total += len(chunk)
        if total > max_bytes:
            raise ObjectTooLarge()
        digest.update(chunk)
    return total, digest.hexdigest()
