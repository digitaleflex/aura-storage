#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed. See docs/DEPLOYMENT.md." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose plugin is unavailable." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm (Node.js) is required to build the web frontend. See docs/DEPLOYMENT.md." >&2; exit 1; }

[[ -f .env ]] || { echo "ERROR: .env is missing. Copy .env.example and replace all placeholders." >&2; exit 1; }

# Load only the operator-owned local .env for validation. Never source an untrusted file.
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${AURA_INSTANCE_ID:?Set AURA_INSTANCE_ID in .env}"
: "${TRAEFIK_IMAGE:?Set TRAEFIK_IMAGE in .env}"
: "${SEAWEEDFS_IMAGE:?Set SEAWEEDFS_IMAGE in .env}"
: "${S3_DOMAIN:?Set S3_DOMAIN in .env}"
: "${ACME_EMAIL:?Set ACME_EMAIL in .env}"
: "${AURA_DATA_DIR:?Set AURA_DATA_DIR in .env}"
: "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY in .env}"
: "${S3_SECRET_KEY:?Set S3_SECRET_KEY in .env}"
: "${WEED_S3_SSE_KEK:?Set WEED_S3_SSE_KEK in .env}"

if grep -Eq 'REPLACE_WITH_|example\.com|example\.invalid|replace-with-' .env; then
  echo "ERROR: Placeholder values remain in .env. Replace them before deployment." >&2
  exit 1
fi

if [[ ! "$WEED_S3_SSE_KEK" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "ERROR: WEED_S3_SSE_KEK must be exactly 64 hexadecimal characters (32 bytes)." >&2
  exit 1
fi

if [[ ${#S3_ACCESS_KEY} -lt 16 || ${#S3_SECRET_KEY} -lt 32 ]]; then
  echo "ERROR: S3_ACCESS_KEY must be at least 16 chars and S3_SECRET_KEY at least 32 chars." >&2
  exit 1
fi

mkdir -p config/seaweedfs
bash ./scripts/generate-config.sh

# Make sure the storage root exists on the configured filesystem.
mkdir -p "$AURA_DATA_DIR"/{master,volume,filer}
chmod 700 "$AURA_DATA_DIR" "$AURA_DATA_DIR"/{master,volume,filer}

docker compose config --quiet
echo "Compose configuration syntax validated; verify SSE-S3 with tests/sse-s3-smoke-test.sh before importing valuable data."
