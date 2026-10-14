"""S3 data-plane access. Keys stay server-side; browsers only get presigned URLs."""
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
