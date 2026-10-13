#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
docker compose ps
docker compose exec -T seaweedfs sh -lc 'wget -q -O /dev/null http://127.0.0.1:8333/'
echo "Local endpoint check passed; run authenticated S3 upload/download tests before accepting data."
