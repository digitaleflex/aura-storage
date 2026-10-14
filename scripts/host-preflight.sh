#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only host diagnostics. No configuration is changed and no secrets are read.
section() { printf '\n== %s ==\n' "$1"; }

section "Timestamp and identity"
date -Is
id
printf 'user=%s\n' "$(id -un)"
printf 'sudo_check: '
if sudo -n true 2>/dev/null; then echo "available without prompt"; else echo "not available non-interactively (this is not necessarily a failure)"; fi

section "Operating system and kernel"
cat /etc/os-release
uname -r
if [[ -e /var/run/reboot-required ]]; then echo "reboot_required=yes"; else echo "reboot_required=no-marker"; fi

section "Resources"
nproc
free -h
df -hT
df -i
lsblk -f

section "Network and listeners"
ip -brief address
ip route
if command -v ss >/dev/null 2>&1; then
  if sudo -n ss -lntup >/dev/null 2>&1; then sudo -n ss -lntup; else ss -lntu; fi
fi

section "SSH"
systemctl is-active ssh 2>/dev/null || true
systemctl is-active ssh.socket 2>/dev/null || true
systemctl status ssh.socket --no-pager --lines=3 2>/dev/null || true

section "Firewall state (inspection only)"
if command -v ufw >/dev/null 2>&1; then sudo ufw status verbose 2>/dev/null || ufw status 2>/dev/null || true; else echo "ufw not installed"; fi
if command -v nft >/dev/null 2>&1; then sudo -n nft list ruleset 2>/dev/null || echo "nft ruleset not readable without interactive sudo"; else echo "nft command not installed"; fi

section "Docker (if installed)"
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker compose version 2>/dev/null || true
  systemctl is-active docker 2>/dev/null || true
else
  echo "docker not installed"
fi

section "End"
echo "Diagnostic only: compare results with docs/REPRODUCIBLE-SETUP.md. No changes were made."
