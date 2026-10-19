#!/usr/bin/env bash
# Disaster recovery: rebuild a FRESH AURA stack from an off-site snapshot.
#
#   bash scripts/restore.sh STAMP --confirm-empty-target
#
# Target = the stack described by the local .env (deployed with `up -d`, empty
# catalogue). Steps:
#   1. download + verify the snapshot against its manifest
#   2. pg_restore the catalogue into the target database (refused if the
#      target already holds objects: this script never merges or overwrites)
#   3. copy every backed-up bucket into the target S3 (rclone copy, no deletes);
#      the target re-encrypts with ITS OWN WEED_S3_SSE_KEK
#   4. restore the audit trail into the api audit volume
# Then run scripts/restore-check.sh and a manual download through the app.
# The api must be restarted afterwards so it reloads the restored catalogue.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/backup-lib.sh
. scripts/backup-lib.sh

STAMP="${1:-}"
[[ -n "$STAMP" && "${2:-}" == "--confirm-empty-target" ]] \
  || die "usage: $0 STAMP --confirm-empty-target (see docs/BACKUP-RESTORE.md)"

load_env_file "${AURA_BACKUP_CONFIG:-config/backup.env}"
load_env_file .env S3_DOMAIN S3_ACCESS_KEY S3_SECRET_KEY POSTGRES_USER POSTGRES_DB
init_remotes
init_runners

WORK="$(mktemp -d "${AURA_BACKUP_STAGING:-/var/tmp}/aura-restore.XXXXXX")"
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT
started=$SECONDS

log "downloading snapshot $STAMP"
for f in manifest.json catalogue.dump audit.tar.gz; do
  "${RCLONE[@]}" cat "vault:snapshots/$STAMP/$f" >"$WORK/$f"
done
python3 - "$WORK" <<'PY' || die "snapshot does not match its manifest"
import hashlib, json, sys
work = sys.argv[1]
m = json.load(open(f"{work}/manifest.json"))
for part in ("catalogue", "audit"):
    digest = hashlib.sha256(open(f"{work}/{m[part]['file']}", "rb").read()).hexdigest()
    if digest != m[part]["sha256"]:
        raise SystemExit(f"{part}: sha256 mismatch")
PY

existing="$(catalogue_sql "SELECT count(*) FROM objects" 2>/dev/null || echo 0)"
[[ "$existing" == 0 ]] || die "target catalogue already holds $existing object rows; refusing to overwrite"

log "restoring catalogue"
# --clean drops the empty bootstrap tables the api created on first start.
"${PG_EXEC[@]}" pg_restore --clean --if-exists --no-owner --no-privileges \
  -U "${POSTGRES_USER:-aura}" -d "${POSTGRES_DB:-aura}" <"$WORK/catalogue.dump"

mapfile -t buckets < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["buckets"]))' "$WORK/manifest.json" | sed '/^$/d')
backed_up_dirs="$("${RCLONE[@]}" lsf vault:objects/ --dirs-only)"
for bucket in "${buckets[@]}"; do
  log "restoring bucket $bucket"
  "${RCLONE[@]}" mkdir "aura:$bucket"
  grep -qx "$bucket/" <<<"$backed_up_dirs" || continue
  "${RCLONE[@]}" copy "vault:objects/$bucket" "aura:$bucket" \
    --transfers "${BACKUP_TRANSFERS:-4}" --checkers 8 --stats-one-line --stats 60s
done

log "restoring audit trail"
gunzip -c "$WORK/audit.tar.gz" | "${API_EXEC[@]}" tar -C "${AURA_AUDIT_DIR:-/var/lib/aura/audit}" -xf -

log "restore of $STAMP done in $((SECONDS - started))s; restart the api, then run scripts/restore-check.sh"
