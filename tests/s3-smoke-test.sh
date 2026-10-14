#!/usr/bin/env bash
set -Eeuo pipefail
: "${S3_ENDPOINT:?Set S3_ENDPOINT, e.g. https://storage.example.tld}"
: "${S3_BUCKET:?Set S3_BUCKET to a pre-created test bucket}"
: "${AWS_ACCESS_KEY_ID:?Set a restricted test access key}"
: "${AWS_SECRET_ACCESS_KEY:?Set the restricted test secret}"
command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI is required." >&2; exit 1; }

tmp="$(mktemp)"
downloaded="$(mktemp)"
trap 'rm -f "$tmp" "$downloaded"' EXIT
printf 'AURA S3 smoke test %s\n' "$(date -u +%FT%TZ)" > "$tmp"
key="aura-smoke-test/$(date -u +%s)-$$.txt"
aws --endpoint-url "$S3_ENDPOINT" s3 cp "$tmp" "s3://$S3_BUCKET/$key"
aws --endpoint-url "$S3_ENDPOINT" s3 cp "s3://$S3_BUCKET/$key" "$downloaded"
cmp -- "$tmp" "$downloaded"
aws --endpoint-url "$S3_ENDPOINT" s3 rm "s3://$S3_BUCKET/$key"
echo "S3 upload/download integrity smoke test passed."
