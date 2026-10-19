#!/usr/bin/env bash
# shellcheck disable=SC2034  # PG_EXEC/API_EXEC/RCLONE are consumed by the sourcing scripts
# Shared helpers for scripts/backup.sh and scripts/restore-check.sh.
# Sourced, never executed. See docs/BACKUP-RESTORE.md.

# Literal KEY=VALUE reader. `.env` values may contain `$` (bcrypt hashes in
# DASHBOARD_AUTH), so the files are never `source`d. Surrounding single or
# double quotes are stripped; nothing is expanded. A variable that is already
# set in the environment wins, which lets tests and operators override.
load_env_file() { # $1=file, rest=optional key filter
  local file="$1" line key value
  shift
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    if (($#)) && [[ " $* " != *" $key "* ]]; then
      continue
    fi
    [[ -n "${!key+x}" ]] && continue
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    export "$key=$value"
  done <"$file"
}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_vars() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || die "$name is not set (see docs/BACKUP-RESTORE.md)"
    [[ "${!name}" != *REPLACE* ]] || die "$name still holds a placeholder"
  done
}

# Command prefixes. Defaults run inside the Compose stack; each can be
# overridden (an empty value runs the tool directly on the host), which is how
# the offline and local end-to-end tests drive the same code paths.
init_runners() {
  read -ra PG_EXEC <<<"${AURA_BACKUP_PG_EXEC-docker compose exec -T postgres}"
  read -ra API_EXEC <<<"${AURA_BACKUP_API_EXEC-docker compose exec -T api}"
  if [[ -n "${AURA_BACKUP_RCLONE+x}" ]]; then
    read -ra RCLONE <<<"$AURA_BACKUP_RCLONE"
  else
    # rclone runs in a pinned container on the default bridge (egress to the
    # off-site destination and to the public S3 hostname). Configuration is
    # passed by environment variable name only, so values never hit `ps`.
    local -a envs=()
    local name
    while IFS= read -r name; do envs+=(-e "$name"); done < <(compgen -e | grep '^RCLONE_')
    RCLONE=(docker run --rm -i "${envs[@]}" "${RCLONE_IMAGE:?Set RCLONE_IMAGE in config/backup.env}")
  fi
}

# Remotes, defined through rclone's RCLONE_CONFIG_<NAME>_* variables:
#   aura:   the AURA S3 endpoint (source of objects, target of a restore)
#   vault:  client-side encrypted (rclone crypt) view of BACKUP_REMOTE
# The off-site backend itself is whatever BACKUP_REMOTE points at, configured
# by the operator in config/backup.env (RCLONE_CONFIG_OFFSITE_*).
init_remotes() {
  require_vars S3_DOMAIN S3_ACCESS_KEY S3_SECRET_KEY BACKUP_REMOTE BACKUP_CRYPT_PASSWORD BACKUP_CRYPT_PASSWORD2
  export RCLONE_CONFIG_AURA_TYPE=s3
  export RCLONE_CONFIG_AURA_PROVIDER=SeaweedFS
  export RCLONE_CONFIG_AURA_ENDPOINT="${AURA_BACKUP_S3_ENDPOINT:-https://$S3_DOMAIN}"
  export RCLONE_CONFIG_AURA_ACCESS_KEY_ID="$S3_ACCESS_KEY"
  export RCLONE_CONFIG_AURA_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
  export RCLONE_CONFIG_AURA_FORCE_PATH_STYLE=true
  # Objects written back by a restore are encrypted at rest by the target
  # (SeaweedFS only applies SSE-S3 when the request asks for it).
  export RCLONE_CONFIG_AURA_SERVER_SIDE_ENCRYPTION=AES256
  export RCLONE_CONFIG_VAULT_TYPE=crypt
  export RCLONE_CONFIG_VAULT_REMOTE="$BACKUP_REMOTE"
  export RCLONE_CONFIG_VAULT_PASSWORD="$BACKUP_CRYPT_PASSWORD"
  export RCLONE_CONFIG_VAULT_PASSWORD2="$BACKUP_CRYPT_PASSWORD2"
}

catalogue_sql() { # $1=SQL; prints unaligned, tuple-only rows
  "${PG_EXEC[@]}" psql -X -v ON_ERROR_STOP=1 -At -F $'\t' \
    -U "${POSTGRES_USER:-aura}" -d "${POSTGRES_DB:-aura}" -c "$1"
}

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }
