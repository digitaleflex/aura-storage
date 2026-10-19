#!/usr/bin/env bash
# Offline checks for scripts/backup*.sh, restore*.sh (issue #9).
# No Docker, no network, no rclone: only parsing and fail-fast guards. The real
# backup -> restore round-trip is recorded in docs/verification-log-*-backup.md.
set -Euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
pass=0
fail=0
check() { # $1=description $2=0 for pass
  if [[ "$2" == 0 ]]; then echo "PASS: $1"; pass=$((pass + 1)); else echo "FAIL: $1"; fail=$((fail + 1)); fi
}

# --- load_env_file: literal, quote-stripping, env wins, key filter ---------
cat >"$workdir/sample.env" <<'ENV'
# comment
DASHBOARD_AUTH='ops:$2y$05$abc/def'
S3_DOMAIN="s3.example.com"
POSTGRES_DB=aura
lowercase=ignored
ENV
out="$(env -i PATH="$PATH" POSTGRES_DB=override bash -c '
  . scripts/backup-lib.sh
  load_env_file "$1"
  printf "%s|%s|%s|%s" "$DASHBOARD_AUTH" "$S3_DOMAIN" "$POSTGRES_DB" "${lowercase-unset}"
' _ "$workdir/sample.env")"
check "values are read literally (no \$ expansion)" "$([[ "$out" == 'ops:$2y$05$abc/def|'* ]] && echo 0 || echo 1)"
check "surrounding quotes are stripped" "$([[ "$out" == *'|s3.example.com|'* ]] && echo 0 || echo 1)"
check "an already-set variable wins over the file" "$([[ "$out" == *'|override|'* ]] && echo 0 || echo 1)"
check "non-uppercase keys are ignored" "$([[ "$out" == *'|unset' ]] && echo 0 || echo 1)"
out="$(env -i PATH="$PATH" bash -c '. scripts/backup-lib.sh; load_env_file "$1" S3_DOMAIN; echo "${POSTGRES_DB-unset}"' _ "$workdir/sample.env")"
check "key filter loads only the named keys" "$([[ "$out" == unset ]] && echo 0 || echo 1)"

# --- fail-fast guards -------------------------------------------------------
run() { env -i PATH="$PATH" HOME="$workdir" AURA_BACKUP_CONFIG="$workdir/none.env" "$@" 2>&1; }
out="$(cd "$workdir" && run bash "$ROOT_DIR/scripts/backup.sh")"; rc=$?
check "backup.sh refuses to run without a destination" "$([[ $rc -ne 0 && "$out" == *"is not set"* ]] && echo 0 || echo 1)"

cp config/backup.env.example "$workdir/placeholder.env"
out="$(run S3_DOMAIN=s3.example.com S3_ACCESS_KEY=k S3_SECRET_KEY=s AURA_BACKUP_CONFIG="$workdir/placeholder.env" bash scripts/backup.sh)"; rc=$?
check "backup.sh refuses placeholder values" "$([[ $rc -ne 0 && "$out" == *"placeholder"* ]] && echo 0 || echo 1)"

out="$(run S3_DOMAIN=s3.example.com S3_ACCESS_KEY=k S3_SECRET_KEY=s BACKUP_REMOTE=x: \
  BACKUP_CRYPT_PASSWORD=p BACKUP_CRYPT_PASSWORD2=q BACKUP_RETENTION_DAYS=0 AURA_BACKUP_RCLONE=false \
  bash scripts/backup.sh)"; rc=$?
check "backup.sh rejects a non-positive retention" "$([[ $rc -ne 0 && "$out" == *"BACKUP_RETENTION_DAYS"* ]] && echo 0 || echo 1)"

out="$(run bash scripts/restore.sh 20260101T000000Z)"; rc=$?
check "restore.sh requires --confirm-empty-target" "$([[ $rc -ne 0 && "$out" == *"--confirm-empty-target"* ]] && echo 0 || echo 1)"

out="$(run bash scripts/restore-check.sh --sample abc)"; rc=$?
check "restore-check.sh validates --sample" "$([[ $rc -ne 0 && "$out" == *"--sample"* ]] && echo 0 || echo 1)"

echo "== $pass passed, $fail failed =="
[[ $fail -eq 0 ]]
