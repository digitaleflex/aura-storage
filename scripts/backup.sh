#!/usr/bin/env bash
# Off-site, client-side encrypted backup of AURA (issue #9).
#
# What is captured, in this order:
#   1. PostgreSQL catalogue  -> pg_dump custom format, verified with pg_restore -l
#   2. Audit trail           -> tarball of the api audit volume
#   3. Manifest              -> timestamp, sha256 of each artefact, catalogue counts
#   4. Every S3 bucket       -> rclone sync to vault:objects/<bucket>; objects that
#                               changed or vanished since the last run are moved to
#                               vault:objects-history/<stamp>/ instead of deleted
# Snapshot artefacts go to vault:snapshots/<stamp>/. Old snapshots and history
# are pruned after BACKUP_RETENTION_DAYS.
#
# The catalogue is dumped BEFORE the objects are copied: every object the dump
# references is either copied by step 4 or, if purged in between, kept in
# objects-history. Objects are read through the S3 API, i.e. as plaintext
# (SeaweedFS SSE-S3 decrypts on GET), and re-encrypted client-side by rclone
# crypt. A restore therefore does not depend on the original WEED_S3_SSE_KEK,
# but it does depend on BACKUP_CRYPT_PASSWORD{,2}: keep them offline.
#
# Configuration: .env (stack) + config/backup.env (destination). Read-only
# towards production; the only writes are to the backup destination.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/backup-lib.sh
. scripts/backup-lib.sh

load_env_file "${AURA_BACKUP_CONFIG:-config/backup.env}"
load_env_file .env S3_DOMAIN S3_ACCESS_KEY S3_SECRET_KEY POSTGRES_USER POSTGRES_DB
init_remotes
init_runners

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
[[ "$RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]] || die "BACKUP_RETENTION_DAYS must be a positive integer"
STAGING="$(mktemp -d "${AURA_BACKUP_STAGING:-/var/tmp}/aura-backup.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
chmod 700 "$STAGING"
started=$SECONDS

ping_monitor() { # optional dead-man switch (e.g. healthchecks.io); never fatal
  [[ -n "${BACKUP_MONITOR_URL:-}" ]] || return 0
  curl -fsS -m 10 --retry 3 "${BACKUP_MONITOR_URL}$1" >/dev/null || log "WARN: monitor ping failed"
}
trap 'ping_monitor /fail' ERR
ping_monitor /start

log "snapshot $STAMP: dumping catalogue"
"${PG_EXEC[@]}" pg_dump -U "${POSTGRES_USER:-aura}" -d "${POSTGRES_DB:-aura}" -Fc \
  >"$STAGING/catalogue.dump"
"${PG_EXEC[@]}" pg_restore -l <"$STAGING/catalogue.dump" >/dev/null \
  || die "pg_restore cannot read the dump just produced"

log "archiving audit trail"
"${API_EXEC[@]}" tar -C "${AURA_AUDIT_DIR:-/var/lib/aura/audit}" -cf - . | gzip -9 >"$STAGING/audit.tar.gz"

available="$(catalogue_sql "SELECT count(*) FROM objects WHERE status = 'available'")"
available_bytes="$(catalogue_sql "SELECT coalesce(sum(size_bytes), 0) FROM objects WHERE status = 'available'")"
mapfile -t buckets < <("${RCLONE[@]}" lsf aura: --dirs-only | sed 's#/$##')

python3 - "$STAGING/manifest.json" "$STAMP" "$available" "$available_bytes" \
  "$(sha256_of "$STAGING/catalogue.dump")" "$(sha256_of "$STAGING/audit.tar.gz")" \
  "${buckets[@]}" <<'PY'
import json, sys
out, stamp, count, size, dump_sha, audit_sha, *buckets = sys.argv[1:]
json.dump({
    "format": 1, "stamp": stamp,
    "catalogue": {"file": "catalogue.dump", "sha256": dump_sha,
                  "available_objects": int(count), "available_bytes": int(size)},
    "audit": {"file": "audit.tar.gz", "sha256": audit_sha},
    "buckets": buckets,
}, open(out, "w"), indent=2)
PY

log "uploading snapshot artefacts"
for f in catalogue.dump audit.tar.gz manifest.json; do
  "${RCLONE[@]}" rcat "vault:snapshots/$STAMP/$f" <"$STAGING/$f"
done

for bucket in "${buckets[@]}"; do
  log "syncing bucket $bucket"
  "${RCLONE[@]}" sync "aura:$bucket" "vault:objects/$bucket" \
    --backup-dir "vault:objects-history/$STAMP/$bucket" \
    --transfers "${BACKUP_TRANSFERS:-4}" --checkers 8 --stats-one-line --stats 60s
done

log "pruning snapshots and history older than ${RETENTION_DAYS}d"
top_dirs="$("${RCLONE[@]}" lsf vault: --dirs-only)"
for dir in snapshots objects-history; do
  # objects-history only exists once a sync has displaced something.
  grep -qx "$dir/" <<<"$top_dirs" || continue
  "${RCLONE[@]}" delete "vault:$dir" --min-age "${RETENTION_DAYS}d"
  "${RCLONE[@]}" rmdirs "vault:$dir" --leave-root
done

ping_monitor ""
log "snapshot $STAMP complete in $((SECONDS - started))s: ${#buckets[@]} bucket(s), $available available object(s)"
