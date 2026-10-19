#!/usr/bin/env bash
# Non-destructive restore test of the latest (or a given) backup (issue #9).
#
#   bash scripts/restore-check.sh [STAMP] [--sample N]
#
# 1. Downloads the snapshot artefacts and checks them against the manifest.
# 2. Restores the catalogue dump into a THROWAWAY PostgreSQL container with no
#    network (never the production database).
# 3. Checks that every bucket in the manifest exists in the backup and that it
#    holds at least as many objects as the restored catalogue marks available.
# 4. Streams N random available objects back from the backup and compares their
#    SHA-256 with the checksum recorded in the restored catalogue.
#
# Exit 0 only if everything matches. Paste the output into the verification log.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/backup-lib.sh
. scripts/backup-lib.sh

STAMP=""
SAMPLE="${RESTORE_CHECK_SAMPLE:-20}"
while (($#)); do
  case "$1" in
    --sample) SAMPLE="${2:?--sample needs a number}"; shift 2 ;;
    -*) die "unknown option $1" ;;
    *) STAMP="$1"; shift ;;
  esac
done
[[ "$SAMPLE" =~ ^[0-9]+$ ]] || die "--sample must be a non-negative integer"

load_env_file "${AURA_BACKUP_CONFIG:-config/backup.env}"
load_env_file .env S3_DOMAIN S3_ACCESS_KEY S3_SECRET_KEY POSTGRES_IMAGE
init_remotes
init_runners

WORK="$(mktemp -d "${AURA_BACKUP_STAGING:-/var/tmp}/aura-restore-check.XXXXXX")"
chmod 700 "$WORK"
SCRATCH_PG=""
cleanup() {
  [[ -n "$SCRATCH_PG" ]] && docker rm -f "$SCRATCH_PG" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT
started=$SECONDS
failures=0
check() { # $1=description, $2=0|1
  if [[ "$2" == 0 ]]; then echo "PASS: $1"; else echo "FAIL: $1"; failures=$((failures + 1)); fi
}

if [[ -z "$STAMP" ]]; then
  STAMP="$("${RCLONE[@]}" lsf vault:snapshots --dirs-only | sed 's#/$##' | sort | tail -1)"
  [[ -n "$STAMP" ]] || die "no snapshot found in vault:snapshots"
fi
echo "Restore check of snapshot $STAMP (sample=$SAMPLE)"

for f in manifest.json catalogue.dump audit.tar.gz; do
  "${RCLONE[@]}" cat "vault:snapshots/$STAMP/$f" >"$WORK/$f"
done
manifest() { # $1=dotted path; lists print one item per line
  python3 - "$WORK/manifest.json" "$1" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
for part in sys.argv[2].split("."):
    value = value[part]
print("\n".join(value) if isinstance(value, list) else value)
PY
}
check "catalogue dump matches manifest sha256" "$([[ "$(sha256_of "$WORK/catalogue.dump")" == "$(manifest catalogue.sha256)" ]] && echo 0 || echo 1)"
check "audit archive matches manifest sha256" "$([[ "$(sha256_of "$WORK/audit.tar.gz")" == "$(manifest audit.sha256)" ]] && echo 0 || echo 1)"
check "audit archive is a readable tarball" "$(tar -tzf "$WORK/audit.tar.gz" >/dev/null 2>&1 && echo 0 || echo 1)"

# Throwaway catalogue. AURA_RESTORE_PG_EXEC lets tests point at an existing
# disposable server instead of starting a container.
if [[ -n "${AURA_RESTORE_PG_EXEC+x}" ]]; then
  read -ra PG_EXEC <<<"$AURA_RESTORE_PG_EXEC"
else
  require_vars POSTGRES_IMAGE
  SCRATCH_PG="aura-restore-check-$$"
  docker run -d --name "$SCRATCH_PG" --network none \
    -e POSTGRES_USER=aura -e POSTGRES_DB=aura -e POSTGRES_HOST_AUTH_METHOD=trust \
    "$POSTGRES_IMAGE" >/dev/null
  for _ in $(seq 60); do
    docker exec "$SCRATCH_PG" pg_isready -U aura -d aura >/dev/null 2>&1 && break
    sleep 1
  done
  PG_EXEC=(docker exec -i "$SCRATCH_PG")
fi
POSTGRES_USER=aura POSTGRES_DB="${AURA_RESTORE_PG_DB:-aura}"
export POSTGRES_USER POSTGRES_DB
"${PG_EXEC[@]}" pg_restore --no-owner --no-privileges -U aura -d "$POSTGRES_DB" <"$WORK/catalogue.dump"
check "catalogue restored into scratch database" 0

restored="$(catalogue_sql "SELECT count(*) FROM objects WHERE status = 'available'")"
check "restored catalogue count matches manifest ($restored)" \
  "$([[ "$restored" == "$(manifest catalogue.available_objects)" ]] && echo 0 || echo 1)"

mapfile -t buckets < <(manifest buckets | sed '/^$/d')
backed_up=0
for bucket in "${buckets[@]}"; do
  # An empty bucket leaves no directory in the backup: count it as 0.
  if "${RCLONE[@]}" lsf "vault:objects/" --dirs-only | grep -qx "$bucket/"; then
    n="$("${RCLONE[@]}" size "vault:objects/$bucket" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
  else
    n=0
  fi
  backed_up=$((backed_up + n))
done
check "backup holds >= available objects ($backed_up >= $restored)" "$((backed_up >= restored ? 0 : 1))"

sampled=0
while IFS=$'\t' read -r bucket key want; do
  [[ -n "$bucket" ]] || continue
  got="$("${RCLONE[@]}" cat "vault:objects/$bucket/$key" | sha256sum | cut -d' ' -f1)"
  check "sha256 of $bucket/$key" "$([[ "$got" == "$want" ]] && echo 0 || echo 1)"
  sampled=$((sampled + 1))
done < <(catalogue_sql "SELECT bucket, object_key, checksum_sha256 FROM objects
                       WHERE status = 'available' AND checksum_sha256 <> ''
                       ORDER BY random() LIMIT $SAMPLE")

echo "Summary: snapshot=$STAMP sampled=$sampled failures=$failures duration=$((SECONDS - started))s"
[[ $failures -eq 0 ]]
