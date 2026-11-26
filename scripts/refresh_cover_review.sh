#!/usr/bin/env bash
# Refresh external cover candidates and render the operator review page.
# This NEVER publishes/applies a cover: selections remain manual and are applied
# only through scripts/apply_cover_candidates.sh with an explicit selection file.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOCK_FILE="${TMPDIR:-/tmp}/aura-cover-review-refresh.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "cover review refresh already running; skipping $(date -u +%FT%TZ)"
  exit 0
fi

LIMIT="${AURA_COVER_CANDIDATE_LIMIT:-20}"
PROVIDER="${AURA_COVER_CANDIDATE_PROVIDER:-all}"
REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-candidates.json"
REVIEW_HTML="${AURA_COVER_REVIEW_HTML:-${AURA_DATA_DIR:-/srv/aura-storage}/cover-review.html}"

AUTO_SELECT="${AURA_COVER_AUTO_SELECT:-1}"
AUTO_SELECT_LIMIT="${AURA_COVER_AUTO_SELECT_LIMIT:-0}"
AUDIT_DIR="${AURA_AUDIT_DIR:-${AURA_DATA_DIR:-/srv/aura-storage}/audit}"

echo "== cover review refresh $(date -u +%FT%TZ) =="
./scripts/cover_candidates.sh "$LIMIT" "$PROVIDER"

if [[ "$AUTO_SELECT" == "1" ]]; then
  mkdir -p "$AUDIT_DIR"
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  SELECTIONS="/tmp/aura-auto-cover-selections-${TS}-$$.json"
  REPORT="$AUDIT_DIR/cover-auto-select-${TS}.json"
  python3 scripts/auto_select_covers.py "$REVIEW_FILE" \
    --output "$SELECTIONS" --report "$REPORT" --limit "$AUTO_SELECT_LIMIT"
  if python3 - "$SELECTIONS" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
raise SystemExit(0 if d.get('books') else 1)
PY
  then
    MERGED="/tmp/aura-auto-cover-merged-${TS}-$$.json"
    python3 scripts/merge_cover_selections.py "$REVIEW_FILE" "$SELECTIONS" "$MERGED"
    mv "$MERGED" "$REVIEW_FILE"
    echo "auto_selected=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["books"]))' "$SELECTIONS") report=$REPORT"
  else
    echo "auto_selected=0 report=$REPORT"
  fi
  rm -f "$SELECTIONS"
fi

python3 scripts/render_cover_review.py "$REVIEW_FILE" --output "$REVIEW_HTML"
echo "review_html=$REVIEW_HTML"
echo "== done $(date -u +%FT%TZ) =="
