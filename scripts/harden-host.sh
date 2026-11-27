#!/usr/bin/env bash
# Idempotent host hardening for the AURA pilot (SSH, fail2ban, UFW).
#
# Applies the configuration verified in
# docs/verification-log-2026-11-26-security-hardening.md.
#
#   ./scripts/harden-host.sh                 # dry-run: report desired vs current state
#   sudo ./scripts/harden-host.sh --apply    # apply changes, then verify
#
# Optional:
#   AURA_COOLIFY_PUBKEY=/path/to/key.pub \
#     sudo ./scripts/harden-host.sh --apply  # also provision the restricted Coolify user
#
# Password authentication is NOT disabled by default. It is only disabled with
# BOTH --disable-password-auth and AURA_VERIFIED_KEY_LOGIN=1, after an out-of-band
# key-based login has been proven in a separate session.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

APPLY=0
DISABLE_PASSWORD=0
SSH_DROPIN="/etc/ssh/sshd_config.d/99-aura-hardening.conf"
F2B_DROPIN="/etc/fail2ban/jail.d/jail.local"
UFW_TAILSCALE_PORT="41641/udp"
COOLIFY_USER="coolify"
COOLIFY_IP="${AURA_COOLIFY_IP:-100.119.132.45}"

log() { printf '[harden-host] %s\n' "$*"; }
die() { printf '[harden-host] ERROR: %s\n' "$*" >&2; exit 1; }

SUDO=()
if (( EUID != 0 )); then
  command -v sudo >/dev/null 2>&1 || die "sudo is required when not running as root"
  SUDO=(sudo)
fi

usage() {
  cat <<'USAGE'
Usage: harden-host.sh [--apply] [--disable-password-auth] [--help]

  (no flags)              Dry-run: show desired state and detect drift.
  --apply                 Write configuration files, enable services, verify.
  --disable-password-auth Also add 'PasswordAuthentication no'.
                          Requires AURA_VERIFIED_KEY_LOGIN=1 and at least one
                          valid public key in the current user's authorized_keys.

Environment:
  AURA_COOLIFY_PUBKEY     Optional .pub file used to provision the restricted
                          Coolify SSH user (sudo NOPASSWD, docker group).
  AURA_COOLIFY_IP         Source IP allowed to use that key (default 100.119.132.45).
USAGE
}

while (($#)); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --disable-password-auth) DISABLE_PASSWORD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

# --- helpers -----------------------------------------------------------------

# Write a file only when its content differs. Keeps a .bak on real changes.
write_file() {
  local target="$1" content="$2" tmp backup
  tmp="$(mktemp)"
  printf '%s' "$content" >"$tmp"
  if [[ -f "$target" ]] && cmp -s "$tmp" "$target"; then
    rm -f "$tmp"
    log "unchanged: $target"
    return 0
  fi
  if (( APPLY == 0 )); then
    log "would write: $target"
    rm -f "$tmp"
    return 0
  fi
  backup="${target}.bak.$(date -u +%Y%m%d%H%M%S)"
  [[ -f "$target" ]] && "${SUDO[@]}" cp -p "$target" "$backup" || true
  "${SUDO[@]}" install -o root -g root -m 0644 "$tmp" "$target"
  rm -f "$tmp"
  log "written: $target (backup: $backup)"
}

service_active() { "${SUDO[@]}" systemctl is-active "$1" 2>/dev/null || true; }
service_enable() {
  local unit="$1"
  if (( APPLY == 0 )); then log "would enable+start: $unit"; return; fi
  "${SUDO[@]}" systemctl enable --now "$unit" >/dev/null
  log "enabled+started: $unit"
}

# --- desired configuration ----------------------------------------------------

ssh_conf='# Aura hardening - 2026-11-26
PermitRootLogin no
MaxAuthTries 3
LoginGraceTime 30
'
if (( DISABLE_PASSWORD == 1 )); then
  ssh_conf+='PasswordAuthentication no
'
fi

f2b_conf='[sshd]
enabled = true
backend = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service
maxretry = 5
findtime = 600
bantime = 3600
bantime.increment = true
bantime.factor = 2
bantime.maxtime = 604800
'

log "mode: $( (( APPLY == 1 )) && echo APPLY || echo DRY-RUN )"
log "password authentication: $( (( DISABLE_PASSWORD == 1 )) && echo will-be-disabled || echo kept-enabled )"

# --- preconditions for disabling passwords ------------------------------------

if (( DISABLE_PASSWORD == 1 )); then
  [[ "${AURA_VERIFIED_KEY_LOGIN:-0}" == "1" ]] \
    || die "set AURA_VERIFIED_KEY_LOGIN=1 after proving a key-only login in a separate session"
  auth_keys="${HOME}/.ssh/authorized_keys"
  [[ -s "$auth_keys" ]] || die "no authorized_keys found at $auth_keys"
  key_count="$(grep -cE '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+|sk-)' "$auth_keys" || true)"
  (( key_count > 0 )) || die "authorized_keys contains no valid public key"
  log "key-only gate: $key_count public key(s) present in $auth_keys"
fi

# --- SSH ---------------------------------------------------------------------

write_file "$SSH_DROPIN" "$ssh_conf"

if (( APPLY == 1 )); then
  "${SUDO[@]}" sshd -t || die "sshd -t failed; configuration was NOT reloaded"
  unit="$(service_active ssh)"
  [[ "$unit" == "active" ]] && "${SUDO[@]}" systemctl reload ssh
  log "sshd configuration validated and reloaded"
else
  log "would validate with 'sshd -t' and reload ssh"
fi

effective="$("${SUDO[@]}" sshd -T 2>/dev/null | grep -E '^(permitrootlogin|maxauthtries|logingracetime|passwordauthentication) ' | sort || true)"
if [[ -n "$effective" ]]; then
  log "effective SSH settings:"
  printf '%s\n' "$effective" | sed 's/^/    /'
else
  log "effective SSH settings unavailable (run as root to inspect with 'sshd -T')"
fi

# --- fail2ban -----------------------------------------------------------------

if ! dpkg -s fail2ban >/dev/null 2>&1; then
  if (( APPLY == 1 )); then
    DEBIAN_FRONTEND=noninteractive "${SUDO[@]}" apt-get install -y fail2ban >/dev/null
    log "installed fail2ban"
  else
    log "would install fail2ban (currently absent)"
  fi
fi

write_file "$F2B_DROPIN" "$f2b_conf"
service_enable fail2ban
if (( APPLY == 1 )); then
  "${SUDO[@]}" systemctl restart fail2ban
  log "fail2ban restarted with corrected sshd journal match"
fi

# --- UFW ----------------------------------------------------------------------

if ! command -v ufw >/dev/null 2>&1; then
  die "ufw is not installed"
fi

log "UFW desired: default deny incoming / allow outgoing; allow 22/tcp, 80/tcp, 443/tcp, $UFW_TAILSCALE_PORT"
if (( APPLY == 1 )); then
  "${SUDO[@]}" ufw default deny incoming >/dev/null
  "${SUDO[@]}" ufw default allow outgoing >/dev/null
  for rule in 22/tcp 80/tcp 443/tcp "$UFW_TAILSCALE_PORT"; do
    "${SUDO[@]}" ufw allow "$rule" >/dev/null || log "rule already present: $rule"
  done
  "${SUDO[@]}" ufw --force enable >/dev/null
  "${SUDO[@]}" ufw status verbose | sed 's/^/    /'
elif (( EUID == 0 )); then
  ufw status verbose 2>/dev/null | sed 's/^/    /'
else
  sudo -n ufw status verbose 2>/dev/null | sed 's/^/    /' || log "ufw status unavailable without a sudo password"
fi

# --- optional Coolify user ----------------------------------------------------

if [[ -n "${AURA_COOLIFY_PUBKEY:-}" ]]; then
  pubkey="$AURA_COOLIFY_PUBKEY"
  [[ -f "$pubkey" ]] || die "AURA_COOLIFY_PUBKEY is not a file: $pubkey"
  grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+|sk-)[[:space:]]+[A-Za-z0-9+/=]+' "$pubkey" \
    || die "AURA_COOLIFY_PUBKEY does not contain an OpenSSH public key"
  [[ "$COOLIFY_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "invalid AURA_COOLIFY_IP: $COOLIFY_IP"

  log "Coolify user desired: $COOLIFY_USER, SSH restricted to $COOLIFY_IP, sudo NOPASSWD, docker group"
  (( EUID == 0 )) || die "Coolify provisioning requires root: sudo ./scripts/harden-host.sh --apply"
  if (( APPLY == 1 )); then
    id "$COOLIFY_USER" >/dev/null 2>&1 || "${SUDO[@]}" useradd -m -s /bin/bash "$COOLIFY_USER"
    "${SUDO[@]}" usermod -aG docker,sudo "$COOLIFY_USER"
    "${SUDO[@]}" install -d -m 0700 -o "$COOLIFY_USER" -g "$COOLIFY_USER" "/home/$COOLIFY_USER/.ssh"
    auth_file="/home/$COOLIFY_USER/.ssh/authorized_keys"
    line="from=\"$COOLIFY_IP\" $(cat -- "$pubkey")"
    grep -qxF "$line" "$auth_file" 2>/dev/null || printf '%s\n' "$line" | "${SUDO[@]}" tee -a "$auth_file" >/dev/null
    "${SUDO[@]}" chown "$COOLIFY_USER:$COOLIFY_USER" "$auth_file"
    "${SUDO[@]}" chmod 0600 "$auth_file"
    printf '%s\n' "$COOLIFY_USER ALL=(ALL) NOPASSWD: ALL" | "${SUDO[@]}" tee /etc/sudoers.d/coolify >/dev/null
    "${SUDO[@]}" chmod 0440 /etc/sudoers.d/coolify
    "${SUDO[@]}" visudo -c >/dev/null
    log "Coolify user provisioned (visudo OK)"
  fi
fi

# --- final verification -------------------------------------------------------

log "verification summary:"
if (( APPLY == 1 )); then
  log "  fail2ban: $(service_active fail2ban)"
  log "  ssh:      $(service_active ssh)"
  if "${SUDO[@]}" command -v fail2ban-client >/dev/null 2>&1; then
    "${SUDO[@]}" fail2ban-client status sshd 2>/dev/null | sed 's/^/    /' || true
  fi
else
  log "  re-run with --apply to enforce the desired state"
fi
log "done"
