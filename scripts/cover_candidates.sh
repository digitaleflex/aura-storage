#!/usr/bin/env bash
# Prepare (never publish) external cover candidates inside the api container.
# Usage: scripts/cover_candidates.sh [limit] [itunes|openlibrary|all]
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

LIMIT="${1:-20}"
PROVIDER="${2:-all}"
REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-candidates.json"
TMP_REVIEW=/tmp/aura-cover-candidates.json
mkdir -p "$(dirname "$REVIEW_FILE")"

docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  -e AURA_COVER_REVIEW_FILE="$TMP_REVIEW" \
  api python - --candidates --limit "$LIMIT" --provider "$PROVIDER" \
  < scripts/cover_candidates.py

# The api container has a read-only rootfs: stream its /tmp review file back to
# the operator-owned host directory (docker cp cannot see that tmpfs here).
docker compose exec -T api cat "$TMP_REVIEW" > "$REVIEW_FILE"
docker compose exec -T api rm -f "$TMP_REVIEW" >/dev/null 2>&1 || true
echo "Fichier de revue: $REVIEW_FILE"
