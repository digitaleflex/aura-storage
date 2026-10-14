#!/usr/bin/env bash
# Install one administrator SSH public key safely (preparation for issue #4).
#
# - Appends ONLY the given .pub file; never overwrites or deletes existing keys.
# - Refuses private keys, empty files, and insecure input paths.
# - Enforces 0700 ~/.ssh and 0600 authorized_keys ownership by the target user.
# - Prints the key fingerprint for out-of-band verification.
# - DRY-RUN default: pass --apply to modify. Without --apply, only reports.
#
# Run as the target user (or root with TARGET_USER set). Review before use.
set -Eeuo pipefail

DRY_RUN=1
PUBKEY=""
TARGET_USER="${TARGET_USER:-$(id -un)}"
# Overridable ONLY for isolated testing (must be an existing empty-or-test dir).
TARGET_HOME="${TARGET_HOME:-$(eval echo "~$TARGET_USER")}"
if [[ -n "${TARGET_HOME_OVERRIDE_ACTIVE:-}" || "$TARGET_HOME" != "$(eval echo "~$TARGET_USER")" ]]; then
  [[ "${ALLOW_HOME_OVERRIDE:-0}" == "1" ]] || { echo "ERROR: refusing to operate outside the target user's real home without ALLOW_HOME_OVERRIDE=1 (test mode)." >&2; exit 1; }
fi

usage() {
  cat <<'USAGE'
Usage: install-admin-key.sh [--apply] <public-key-file>

  --apply   actually modify ~/.ssh/authorized_keys (default is dry-run report)
  <public-key-file>  an OpenSSH PUBLIC key (.pub); private keys are refused
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) DRY_RUN=0; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
    *) [[ -z "$PUBKEY" ]] || { echo "ERROR: only one key file accepted" >&2; exit 1; }; PUBKEY="$1"; shift ;;
  esac
done

[[ -n "$PUBKEY" ]] || { echo "ERROR: missing public key file." >&2; usage >&2; exit 1; }
[[ -f "$PUBKEY" ]] || { echo "ERROR: not a regular file: $PUBKEY" >&2; exit 1; }
[[ "$PUBKEY" != *.pub ]] && { echo "ERROR: refusing non-.pub file (private keys must never be transferred)." >&2; exit 1; }
grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+|sk-ssh-ed25519|sk-ecdsa-sha2-nistp256)[[:space:]]+[A-Za-z0-9+/=]+( .*)?$' "$PUBKEY" \
  || { echo "ERROR: file does not look like a single OpenSSH public key." >&2; exit 1; }
command -v ssh-keygen >/dev/null 2>&1 || { echo "ERROR: ssh-keygen is required." >&2; exit 1; }

SSH_DIR="$TARGET_HOME/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"
FPRINT="$(ssh-keygen -lf "$PUBKEY" 2>/dev/null | awk '{print $2, $4}')"
echo "Key fingerprint: $FPRINT"

if [[ -f "$AUTH_KEYS" ]] && grep -qxF "$(cat -- "$PUBKEY")" "$AUTH_KEYS" 2>/dev/null; then
  echo "Key already present in $AUTH_KEYS; nothing to do."
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY-RUN: would create $SSH_DIR (0700), append key to $AUTH_KEYS (0600), owned by $TARGET_USER."
  echo "Re-run with --apply to modify."
  exit 0
fi

install -d -m 700 -o "$TARGET_USER" -g "$TARGET_USER" "$SSH_DIR"
touch "$AUTH_KEYS"
cat -- "$PUBKEY" >> "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"
chown "$TARGET_USER:$TARGET_USER" "$AUTH_KEYS"
echo "Installed. Verify in a SECOND independent session before changing any SSH policy:"
echo "  ssh <user>@<host>  # then: whoami && sudo -v"
