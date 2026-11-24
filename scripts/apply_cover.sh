#!/usr/bin/env bash
# Publish one operator-provided cover image for a published audiobook.
# Usage: scripts/apply_cover.sh OBJECT_ID /path/to/cover.jpg|https://.../cover.jpg
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

OBJECT_ID="${1:?Usage: apply_cover.sh OBJECT_ID IMAGE_PATH}"
SOURCE="${2:?Usage: apply_cover.sh OBJECT_ID IMAGE_PATH}"

LOCK_FILE="${TMPDIR:-/tmp}/aura-cover-review.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "une autre operation sur les couvertures est en cours" >&2
  exit 1
fi

REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-candidates.json"
TMP_REVIEW="/tmp/aura-cover-review-$$.json"
TMP_IMAGE="/tmp/aura-cover-input-$$"
HOST_OUTPUT="$REVIEW_FILE.tmp.$$"
mkdir -p "$(dirname "$REVIEW_FILE")"

valid_review() {
  python3 - "$1" <<'PY'
import json
import sys

def reject_constant(value):
    raise ValueError(f"valeur JSON non autorisee: {value}")

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        data = json.load(source, parse_constant=reject_constant)
except (OSError, ValueError) as exc:
    raise SystemExit(f"fichier de revue illisible: {exc}")
if not isinstance(data, dict) or not isinstance(data.get("books"), list):
    raise SystemExit("fichier de revue invalide: liste 'books' absente")
for book in data["books"]:
    if not isinstance(book, dict):
        raise SystemExit("fichier de revue invalide: entree de livre non objet")
    candidates = book.get("candidates", [])
    if candidates is not None and (
        not isinstance(candidates, list)
        or any(not isinstance(candidate, dict) for candidate in candidates)
    ):
        raise SystemExit("fichier de revue invalide: candidat non objet")
PY
}

cleanup() {
  rm -f "$HOST_OUTPUT"
  docker compose exec -T api rm -f "$TMP_IMAGE" "$TMP_REVIEW" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ -f "$REVIEW_FILE" ]]; then
  valid_review "$REVIEW_FILE"
  docker compose exec -T -i api sh -c "cat > '$TMP_REVIEW'" < "$REVIEW_FILE"
else
  docker compose exec -T api rm -f "$TMP_REVIEW" >/dev/null 2>&1 || true
fi

if [[ "$SOURCE" =~ ^https?:// ]]; then
  SOURCE_ARGS=(--url "$SOURCE")
else
  [[ -f "$SOURCE" ]] || { echo "image introuvable: $SOURCE" >&2; exit 1; }
  docker compose exec -T -i api sh -c "cat > '$TMP_IMAGE'" < "$SOURCE"
  SOURCE_ARGS=(--file "$TMP_IMAGE")
fi

docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  -e AURA_COVER_REVIEW_FILE="$TMP_REVIEW" \
  api python - --apply --object-id "$OBJECT_ID" "${SOURCE_ARGS[@]}" \
  < scripts/cover_candidates.py

docker compose exec -T api cat "$TMP_REVIEW" > "$HOST_OUTPUT"
valid_review "$HOST_OUTPUT"
mv "$HOST_OUTPUT" "$REVIEW_FILE"
