#!/usr/bin/env bash
#
# ssh-firewall-check.sh — Vérification read-only de l'état SSH et pare-feu
# sur l'hôte VPS AURA.
#
# Ce script ne MODIFIE rien. Il rapporte l'état actuel pour aider à valider
# le gate P0 "SSH key-only + pare-feu".
#
# Nécessite : sudo (pour sshd -T et ufw status), ss, docker.
set -euo pipefail

echo "===== Vérification SSH et pare-feu AURA ====="
echo ""

# --- SSH ---
echo "[1/4] État du service SSH :"
if systemctl is-enabled ssh >/dev/null 2>&1; then
  echo "  ssh.service : enabled"
else
  echo "  ssh.service : disabled (socket activation possible)"
fi
if systemctl is-active ssh >/dev/null 2>&1 || systemctl is-active ssh.socket >/dev/null 2>&1; then
  echo "  ssh : actif"
else
  echo "  ssh : INACTIF"
fi
echo ""

echo "[2/4] Clés autorisées :"
if [ -f ~/.ssh/authorized_keys ]; then
  echo "  ~/.ssh/authorized_keys : présent ($(wc -l < ~/.ssh/authorized_keys) entrée(s))"
  ls -l ~/.ssh/authorized_keys | awk '{print "  permissions : " $1}'
else
  echo "  ~/.ssh/authorized_keys : ABSENT — login par clé non configuré"
fi
echo ""

# --- Pare-feu ---
echo "[3/4] Pare-feu (ufw) :"
if sudo ufw status >/dev/null 2>&1; then
  sudo ufw status verbose
else
  echo "  ufw non disponible ou non actif"
fi
echo ""

echo "[4/4] Ports en écoute sur l'hôte :"
sudo ss -tlnp 2>/dev/null || ss -tln 2>/dev/null || echo "  (ss non disponible)"

echo ""
echo "===== Fin de la vérification ====="
