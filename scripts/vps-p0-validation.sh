#!/usr/bin/env bash
#
# vps-p0-validation.sh — Vérification automatisée des 3 gates P0 (ISSUE-002, 003, 004)
#
# Usage: sudo bash ./scripts/vps-p0-validation.sh
#
# Ce script est en LECTURE SEULE pour les gates 2 et 3.
# Pour le gate 1, il crée un backup local (ne restaure pas).
#
# Nécessite : sudo, docker, docker compose, ss, ufw, pg_dump (via docker)
set -euo pipefail

AURA_DATA_DIR="${AURA_DATA_DIR:-/var/lib/aura-storage}"
BACKUP_DEST="${AURA_DATA_DIR}/backups"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/aura-storage}"
APP_DOMAIN="${APP_DOMAIN:-localhost}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠${NC} $1"; WARN=$((WARN+1)); }

echo "================================================"
echo "  VPS P0 Validation — Gates ISSUE-002/003/004"
echo "  $(date)"
echo "================================================"
echo ""

# ============================================================
# GATE 1 — Sauvegarde et restauration (ISSUE-002)
# ============================================================
echo "────────────────────────────────────────────"
echo " GATE 1 — Sauvegarde et restauration"
echo "────────────────────────────────────────────"

# 1.1 — Vérifier que le script de backup existe
if [ -x "${COMPOSE_DIR}/scripts/aura-backup.sh" ]; then
  pass "Script aura-backup.sh présent et exécutable"
else
  fail "Script aura-backup.sh manquant ou non exécutable"
fi

# 1.2 — Vérifier que PostgreSQL est accessible
if docker compose -f "${COMPOSE_DIR}/docker-compose.yml" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
  pass "PostgreSQL accessible via Docker"
else
  fail "PostgreSQL non accessible via Docker"
fi

# 1.3 — Créer un backup de test
echo ""
echo "Création d'un backup de test…"
if bash "${COMPOSE_DIR}/scripts/aura-backup.sh" "${BACKUP_DEST}" 1 >/dev/null 2>&1; then
  pass "Backup créé avec succès"
else
  fail "Échec de la création du backup"
fi

# 1.4 — Vérifier que le répertoire de backup contient des fichiers
if compgen -G "${BACKUP_DEST}/aura-backup-*" > /dev/null; then
  LATEST=$(ls -1d "${BACKUP_DEST}"/aura-backup-* | sort -r | head -1)
  if [ -f "${LATEST}/catalogue.sql" ] && [ -s "${LATEST}/catalogue.sql" ]; then
    pass "Dump PostgreSQL présent et non vide : ${LATEST}/catalogue.sql"
  else
    fail "Dump PostgreSQL manquant ou vide"
  fi
else
  fail "Aucun répertoire de backup trouvé dans ${BACKUP_DEST}"
fi

# 1.5 — Vérifier les secrets (avertissement seulement)
if [ -f "${COMPOSE_DIR}/.env" ]; then
  warn "Fichier .env présent — assurez-vous qu'il est sauvegardé hors du VPS"
else
  warn "Fichier .env introuvable — vérifiez son emplacement"
fi

echo ""

# ============================================================
# GATE 2 — SSH key-only + Pare-feu (ISSUE-003)
# ============================================================
echo "────────────────────────────────────────────"
echo " GATE 2 — SSH key-only + Pare-feu"
echo "────────────────────────────────────────────"

# 2.1 — Vérifier authorized_keys
if [ -f ~/.ssh/authorized_keys ]; then
  KEY_COUNT=$(wc -l < ~/.ssh/authorized_keys 2>/dev/null || echo 0)
  AK_PERMS=$(stat -c '%a' ~/.ssh/authorized_keys 2>/dev/null || echo "??")
  SSH_DIR_PERMS=$(stat -c '%a' ~/.ssh 2>/dev/null || echo "??")
  if [ "$AK_PERMS" = "600" ] && [ "$SSH_DIR_PERMS" = "700" ]; then
    pass "authorized_keys présent (${KEY_COUNT} clé(s)), permissions correctes (600/700)"
  else
    warn "authorized_keys présent mais permissions : ${AK_PERMS}/${SSH_DIR_PERMS} (attendu 600/700)"
  fi
else
  fail "~/.ssh/authorized_keys absent — login par clé non configuré"
fi

# 2.2 — Vérifier PasswordAuthentication dans sshd_config
if sudo sshd -T 2>/dev/null | grep -q "^passwordauthentication no"; then
  pass "SSH : authentification par mot de passe désactivée"
else
  fail "SSH : authentification par mot de passe peut-être activée (vérifier sshd_config)"
fi

# 2.3 — Vérifier PubkeyAuthentication
if sudo sshd -T 2>/dev/null | grep -q "^pubkeyauthentication yes"; then
  pass "SSH : authentification par clé publique activée"
else
  fail "SSH : authentification par clé publique non activée"
fi

# 2.4 — Vérifier PermitRootLogin
if sudo sshd -T 2>/dev/null | grep -q "^permitrootlogin no"; then
  pass "SSH : login root désactivé"
else
  warn "SSH : login root peut-être activé"
fi

# 2.5 — Vérifier ufw
if sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  pass "Pare-feu ufw : actif"
else
  fail "Pare-feu ufw : inactif ou non installé"
fi

# 2.6 — Vérifier que seuls 22/80/443 sont ouverts
OPEN_PORTS=$(sudo ss -tlnp 2>/dev/null | awk '{print $4}' | awk -F: '{print $NF}' | sort -un | tr '\n' ' ')
echo "  Ports ouverts : ${OPEN_PORTS:-aucun}"
for port in 22 80 443; do
  if echo " ${OPEN_PORTS} " | grep -q " ${port} "; then
    pass "Port ${port} ouvert (attendu)"
  else
    fail "Port ${port} FERMÉ (attendu ouvert)"
  fi
done

# Vérifier qu'aucun port SeaweedFS n'est publié (ex: 8080, 8888, 9333, etc.)
SEAWEED_PORTS=$(sudo ss -tlnp 2>/dev/null | awk '{print $4}' | awk -F: '{print $NF}' | sort -un | grep -E '^(4022|8080|8888|9333|7936|7937|7938|7939|7940|7941|7942|7943|7944|7945|7946|7947|7948|7949|7950)$' || true)
if [ -z "${SEAWEED_PORTS}" ]; then
  pass "Aucun port SeaweedFS publié sur l'hôte"
else
  fail "Ports SeaweedFS publiés sur l'hôte : ${SEAWEED_PORTS}"
fi

echo ""

# ============================================================
# GATE 3 — Persistance après reboot (ISSUE-004)
# ============================================================
echo "────────────────────────────────────────────"
echo " GATE 3 — Persistance après redémarrage"
echo "────────────────────────────────────────────"

# 3.1 — Vérifier les politiques de redémarrage dans docker-compose.yml
RESTART_POLICIES=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" config 2>/dev/null | grep -c "restart:" || echo 0)
if [ "${RESTART_POLICIES}" -gt 0 ]; then
  pass "Politiques de redémarrage définies dans docker-compose.yml (${RESTART_POLICIES} occurrences)"
else
  fail "Aucune politique de redémarrage trouvée dans docker-compose.yml"
fi

# 3.2 — Vérifier que les conteneurs sont actuellement running
RUNNING=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" ps --services --filter "status=running" 2>/dev/null | wc -l)
TOTAL=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" config --services 2>/dev/null | wc -l)
if [ "${RUNNING}" -eq "${TOTAL}" ] && [ "${TOTAL}" -gt 0 ]; then
  pass "Tous les conteneurs sont running (${RUNNING}/${TOTAL})"
else
  warn "Conteneurs running : ${RUNNING}/${TOTAL}"
fi

# 3.3 — Vérifier que les volumes sont montés depuis l'hôte
VOLUME_MOUNTS=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" config 2>/dev/null | grep -A2 "volumes:" | grep -c "${AURA_DATA_DIR}" || echo 0)
if [ "${VOLUME_MOUNTS}" -gt 0 ]; then
  pass "Volumes montés depuis l'hôte (${AURA_DATA_DIR})"
else
  warn "Aucun volume monté depuis ${AURA_DATA_DIR} trouvé — vérifier docker-compose.yml"
fi

# 3.4 — Vérifier l'API
if curl -sf "https://${APP_DOMAIN}/health/ready" >/dev/null 2>&1; then
  pass "API : GET /health/ready retourne 200"
else
  warn "API : GET /health/ready ne répond pas (Vérifier APP_DOMAIN=${APP_DOMAIN})"
fi

# 3.5 — Espace disque disponible
DISK_AVAIL=$(df "${BACKUP_DEST}" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
if [ "${DISK_AVAIL}" -gt 1048576 ]; then
  pass "Espace disque disponible : > 1 Go ($((${DISK_AVAIL}/1024)) Mo)"
else
  warn "Espace disque faible : $((${DISK_AVAIL}/1024)) Mo disponible sur ${BACKUP_DEST}"
fi

echo ""

# ============================================================
# RÉSUMÉ
# ============================================================
echo "================================================"
echo "  RÉSUMÉ"
echo "================================================"
echo -e "  ${GREEN}Passé : ${PASS}${NC}"
echo -e "  ${RED}Échoué : ${FAIL}${NC}"
echo -e "  ${YELLOW}Avertissements : ${WARN}${NC}"
echo ""

if [ "${FAIL}" -eq 0 ]; then
  echo -e "${GREEN}Tous les tests critiques sont passés.${NC}"
  echo "Vous pouvez considérer les gates P0 comme validés."
else
  echo -e "${RED}${FAIL} test(s) critique(s) ont échoué.${NC}"
  echo "Corrigez les problèmes avant la mise en production."
fi
echo ""

exit ${FAIL}
