#!/usr/bin/env bash
# Prepare (never publish) external cover candidates inside the api container.
# Usage: scripts/cover_candidates.sh [limit] [itunes|openlibrary|all]
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

LIMIT="${1:-20}"
PROVIDER="${2:-all}"
REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-review/cover-candidates.json"
mkdir -p "$(dirname "$REVIEW_FILE")"
LOCK_FILE="$REVIEW_FILE.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "une autre operation sur les couvertures est en cours" >&2
  exit 1
fi

TMP_REVIEW="/tmp/aura-cover-candidates-$$.json"
HOST_OUTPUT="$REVIEW_FILE.tmp.$$"

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
  docker compose exec -T api rm -f "$TMP_REVIEW" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Seed the container with the existing review so bounded refreshes preserve
# applied books, operator choices and entries outside the current limit.
if [[ -f "$REVIEW_FILE" ]]; then
  valid_review "$REVIEW_FILE"
  docker compose exec -T -i api sh -c "cat > '$TMP_REVIEW'" < "$REVIEW_FILE"
else
  docker compose exec -T api rm -f "$TMP_REVIEW" >/dev/null 2>&1 || true
fi

docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  -e AURA_COVER_REVIEW_FILE="$TMP_REVIEW" \
  api python - --candidates --limit "$LIMIT" --provider "$PROVIDER" \
  < scripts/cover_candidates.py

docker compose exec -T api cat "$TMP_REVIEW" > "$HOST_OUTPUT"
valid_review "$HOST_OUTPUT"
mv "$HOST_OUTPUT" "$REVIEW_FILE"
echo "Fichier de revue: $REVIEW_FILE"
