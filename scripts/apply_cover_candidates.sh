#!/usr/bin/env bash
# Publish covers explicitly selected in an exported review JSON.
# Usage: scripts/apply_cover_candidates.sh SELECTIONS.json [--dry-run] [--selected-limit N]
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

SELECTIONS="${1:?Usage: apply_cover_candidates.sh SELECTIONS.json [--dry-run]}"
shift
[[ -f "$SELECTIONS" ]] || { echo "fichier de sélection introuvable: $SELECTIONS" >&2; exit 1; }

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

REVIEW_FILE="${AURA_COVER_REVIEW_FILE:-${AURA_DATA_DIR:-/srv/aura-storage}/cover-review/cover-candidates.json}"
mkdir -p "$(dirname "$REVIEW_FILE")"
LOCK_FILE="$REVIEW_FILE.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "une autre operation sur les couvertures est en cours" >&2
  exit 1
fi

TMP_INPUT="/tmp/aura-cover-input-$$.json"
TMP_OUTPUT="/tmp/aura-cover-output-$$.json"
HOST_SELECTION="$REVIEW_FILE.selection-$$.json"
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
  rm -f "$HOST_SELECTION" "$HOST_OUTPUT"
  docker compose exec -T api rm -f "$TMP_INPUT" "$TMP_OUTPUT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Merge into the current canonical review instead of trusting a possibly old
# or partial export. The canonical file itself is not modified by a dry-run.
python3 scripts/merge_cover_selections.py "$REVIEW_FILE" "$SELECTIONS" "$HOST_SELECTION"
valid_review "$HOST_SELECTION"
docker compose exec -T -i api sh -c "cat > '$TMP_INPUT'" < "$HOST_SELECTION"
docker compose exec -T api rm -f "$TMP_OUTPUT" >/dev/null 2>&1 || true

# Keep processing status even when some covers fail; the trap/exit path below
# still publishes any valid partial progress written by Python.
set +e
docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  -e AURA_COVER_REVIEW_FILE="$TMP_OUTPUT" \
  api python - --apply-selected --review-input "$TMP_INPUT" "$@" \
  < scripts/cover_candidates.py
STATUS=$?
set -e

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Simulation terminee; fichier de revue inchange: $REVIEW_FILE"
elif docker compose exec -T api test -f "$TMP_OUTPUT" >/dev/null 2>&1; then
  docker compose exec -T api cat "$TMP_OUTPUT" > "$HOST_OUTPUT"
  valid_review "$HOST_OUTPUT"
  mv "$HOST_OUTPUT" "$REVIEW_FILE"
  echo "Fichier de revue mis a jour: $REVIEW_FILE"
else
  echo "Aucune modification du fichier de revue: $REVIEW_FILE"
fi

exit "$STATUS"
