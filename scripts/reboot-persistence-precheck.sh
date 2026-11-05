#!/usr/bin/env bash
#
# reboot-persistence-precheck.sh — Vérification read-only avant un test de
# redémarrage de l'hôte AURA Storage.
#
# Vérifie que :
# - Tous les conteneurs ont une politique de redémarrage (restart policy)
# - Les volumes sont montés depuis l'hôte (persistance des données)
# - Tous les conteneurs sont actuellement sains
#
# Nécessite : docker, docker compose.
set -euo pipefail

echo "===== Pré-vérification de persistance AURA ====="
echo ""

# --- 1. Politiques de redémarrage ---
echo "[1/3] Politiques de redémarrage des conteneurs :"
docker compose config 2>/dev/null | grep -B 1 -A 1 "restart:" || {
  echo "  ATTENTION : impossible de lire docker compose config"
}
echo ""

# --- 2. Montages de volumes ---
echo "[2/3] Volumes montés depuis l'hôte :"
docker compose config 2>/dev/null | grep -A 3 "volumes:" || {
  echo "  ATTENTION : impossible de lire les volumes"
}
echo ""

# --- 3. État actuel des conteneurs ---
echo "[3/3] État des conteneurs :"
docker compose ps 2>/dev/null || {
  echo "  ERREUR : docker compose ps a échoué"
  exit 1
}
echo ""

echo "===== Pré-vérification terminée ====="
echo "Si toutes les politiques de redémarrage sont définies et les volumes"
echo "montés depuis l'hôte, le test de redémarrage peut être lancé."
