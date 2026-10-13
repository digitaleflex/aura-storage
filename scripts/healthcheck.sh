#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

docker compose ps
docker compose exec -T seaweed-filer sh -lc 'wget -q -O /dev/null http://127.0.0.1:8333/' || {
  echo "ERROR: S3 endpoint check failed. Inspect container logs and verify wget exists in the selected image." >&2
  exit 1
}
echo "Local S3 endpoint HTTP check passed. This does not validate S3 authentication; run tests/s3-smoke-test.sh too."
