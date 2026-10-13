#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed. See docs/DEPLOYMENT.md." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose plugin is unavailable." >&2; exit 1; }

[[ -f .env ]] || { echo "ERROR: .env is missing. Copy .env.example and replace all placeholders." >&2; exit 1; }
[[ -f config/seaweedfs/s3.json ]] || { echo "ERROR: config/seaweedfs/s3.json is missing; create and secure it." >&2; exit 1; }
if grep -Eq 'replace-with-|example\.invalid|REPLACE_WITH_' .env config/seaweedfs/s3.json; then
  echo "ERROR: Placeholder values remain in deployment configuration." >&2
  exit 1
fi

mkdir -p data
chmod 700 data
docker compose config --quiet
echo "Compose configuration syntax validated; production readiness is not implied."
