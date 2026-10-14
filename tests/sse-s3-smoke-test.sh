#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] || { echo "ERROR: .env is missing." >&2; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI v2 is required." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a
: "${S3_DOMAIN:?Set S3_DOMAIN in .env}"
: "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY in .env}"
: "${S3_SECRET_KEY:?Set S3_SECRET_KEY in .env}"
: "${WEED_S3_SSE_KEK:?Set WEED_S3_SSE_KEK in .env}"
if [[ ! "$WEED_S3_SSE_KEK" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "ERROR: WEED_S3_SSE_KEK must be 64 hexadecimal characters." >&2; exit 1
fi
export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export AWS_DEFAULT_REGION="us-east-1" AWS_EC2_METADATA_DISABLED=true
endpoint="https://$S3_DOMAIN"
bucket="aura-sse-test-$(python3 -c 'import secrets; print(secrets.token_hex(5))')"
workdir="$(mktemp -d)"
object_key="sse-s3-smoke-test.txt"
cleanup() {
  aws --no-cli-pager --endpoint-url "$endpoint" s3api delete-object --bucket "$bucket" --key "$object_key" >/dev/null 2>&1 || true
  aws --no-cli-pager --endpoint-url "$endpoint" s3api delete-bucket --bucket "$bucket" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT
printf 'AURA SSE-S3 acceptance test %s\n' "$(date -u +%FT%TZ)" > "$workdir/source.txt"
sha_before="$(sha256sum "$workdir/source.txt" | awk '{print $1}')"
echo "Creating temporary test bucket..."
aws --no-cli-pager --endpoint-url "$endpoint" s3api create-bucket --bucket "$bucket" >/dev/null
echo "Uploading object with SSE-S3 explicitly requested..."
aws --no-cli-pager --endpoint-url "$endpoint" s3api put-object --bucket "$bucket" --key "$object_key" --body "$workdir/source.txt" --server-side-encryption AES256 >/dev/null
echo "Verifying server-reported encryption..."
aws --no-cli-pager --endpoint-url "$endpoint" s3api head-object --bucket "$bucket" --key "$object_key" > "$workdir/head.json"
python3 - "$workdir/head.json" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
if result.get("ServerSideEncryption") != "AES256":
    raise SystemExit("FAIL: S3 did not report ServerSideEncryption=AES256.")
print("PASS: S3 reports ServerSideEncryption=AES256.")
PY
echo "Downloading object and verifying integrity..."
aws --no-cli-pager --endpoint-url "$endpoint" s3api get-object --bucket "$bucket" --key "$object_key" "$workdir/downloaded.txt" >/dev/null
sha_after="$(sha256sum "$workdir/downloaded.txt" | awk '{print $1}')"
[[ "$sha_before" == "$sha_after" ]] || { echo "FAIL: SHA-256 mismatch after download." >&2; exit 1; }
echo "PASS: SSE-S3 was reported and the downloaded object matches the original."
echo "Note: this proves the S3 API path only; it does not prove independent backup/restore or disk-level encryption."
