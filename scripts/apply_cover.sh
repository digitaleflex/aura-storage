#!/usr/bin/env bash
# Publish one operator-provided cover image for a published audiobook.
# Usage: scripts/apply_cover.sh OBJECT_ID /path/to/cover.jpg|https://.../cover.jpg
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

OBJECT_ID="${1:?Usage: apply_cover.sh OBJECT_ID IMAGE_PATH}"
SOURCE="${2:?Usage: apply_cover.sh OBJECT_ID IMAGE_PATH}"
REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-candidates.json"
TMP_REVIEW=/tmp/aura-cover-candidates.json
TMP_IMAGE=/tmp/aura-cover-input

cleanup() {
  docker compose exec -T api rm -f "$TMP_IMAGE" "$TMP_REVIEW" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ -f "$REVIEW_FILE" ]]; then
  docker compose exec -T -i api sh -c "cat > $TMP_REVIEW" < "$REVIEW_FILE"
fi

if [[ "$SOURCE" =~ ^https?:// ]]; then
  SOURCE_ARGS=(--url "$SOURCE")
else
  [[ -f "$SOURCE" ]] || { echo "image introuvable: $SOURCE" >&2; exit 1; }
  docker compose exec -T -i api sh -c "cat > $TMP_IMAGE" < "$SOURCE"
  SOURCE_ARGS=(--file "$TMP_IMAGE")
fi

docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  -e AURA_COVER_REVIEW_FILE="$TMP_REVIEW" \
  api python - --apply --object-id "$OBJECT_ID" "${SOURCE_ARGS[@]}" \
  < scripts/cover_candidates.py

mkdir -p "$(dirname "$REVIEW_FILE")"
docker compose exec -T api cat "$TMP_REVIEW" > "$REVIEW_FILE"
