"""#41: default bucket names derived by the API obey the S3 naming rules.

Pure unit tests — no catalogue, no S3 endpoint.
"""
import pytest

from api.s3 import is_valid_bucket_name


@pytest.mark.parametrize("name", [
    "aura",
    "aura-space-abc12345-test",
    "my.bucket-01",
    "a1b",
    "0-start-and-end-9",
    "x" * 63,
])
def test_valid_bucket_names(name):
    assert is_valid_bucket_name(name) is True


@pytest.mark.parametrize("name", [
    "",
    "ab",                      # too short
    "x" * 64,                  # too long
    "Aura",                    # uppercase
    "aura_bucket",             # underscore
    "-aura",                   # leading hyphen
    "aura-",                   # trailing hyphen
    "aura..bucket",            # consecutive dots
    "aura.-bucket",            # dot then hyphen
    "aura-.bucket",            # hyphen then dot
    "192.168.0.1",             # IP-address shaped
    "xn--aura",                # reserved prefix
    "sthree-aura",             # reserved prefix
    "amzn-s3-demo-bucket",     # reserved prefix
    "aura-s3alias",            # reserved suffix
    "aura--ol-s3",             # reserved suffix
])
def test_invalid_bucket_names(name):
    assert is_valid_bucket_name(name) is False
