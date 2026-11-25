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
REVIEW_FILE="${AURA_DATA_DIR:-/srv/aura-storage}/cover-review/cover-candidates.json"
REVIEW_HTML="${AURA_COVER_REVIEW_HTML:-${AURA_DATA_DIR:-/srv/aura-storage}/cover-review.html}"

echo "== cover review refresh $(date -u +%FT%TZ) =="
./scripts/cover_candidates.sh "$LIMIT" "$PROVIDER"
python3 scripts/render_cover_review.py "$REVIEW_FILE" --output "$REVIEW_HTML"
echo "review_html=$REVIEW_HTML"
echo "== done $(date -u +%FT%TZ) =="
