#!/usr/bin/env bash
# Controlled refresh of the public audiobook catalogue.
#
# Deliberately DOES NOT publish new books: publication stays a manual, curated
# decision (PacksDialog / scripts/publish_audiobooks.py --apply). It only
# enriches objects that are already published but still lack a locally
# extracted cover, duration or chapter list.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Never run two refreshes at once (cron + manual run can otherwise overlap).
LOCK_FILE="${TMPDIR:-/tmp}/aura-public-refresh.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "refresh already running; skipping $(date -u +%FT%TZ)"
  exit 0
fi

LIMIT="${AURA_REFRESH_LIMIT:-20}"
CONTAINER_ROOT=/srv/api
REVIEW_FILE="${AURA_COVER_REVIEW_FILE:-${AURA_DATA_DIR:-/srv/aura-storage}/cover-review/cover-candidates.json}"
COVER_LOCK_FILE="${REVIEW_FILE}.lock"
mkdir -p "$(dirname "$COVER_LOCK_FILE")"
exec 8>"$COVER_LOCK_FILE"

echo "== public library refresh $(date -u +%FT%TZ) =="

# Covers: embedded artwork then sibling images, bounded, dry-run disabled.
# Share the external-cover lock so two writers cannot replace the same S3 key.
if flock -n 8; then
  AURA_REPO_ROOT="$CONTAINER_ROOT" docker compose exec -T \
    -e AURA_REPO_ROOT="$CONTAINER_ROOT" \
    api python - --apply --limit "$LIMIT" < scripts/generate_audiobook_covers.py
  flock -u 8
else
  echo "covers: another cover operation is running; skipping this refresh"
fi

# Duration + chapters: local ffprobe, bounded.
AURA_REPO_ROOT="$CONTAINER_ROOT" docker compose exec -T \
  -e AURA_REPO_ROOT="$CONTAINER_ROOT" \
  api python - --apply --limit "$LIMIT" < scripts/extract_audio_chapters.py

echo "== done $(date -u +%FT%TZ) =="
