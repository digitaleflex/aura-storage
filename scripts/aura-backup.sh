#!/usr/bin/env bash
#
# aura-backup.sh — Sauvegarde complète d'AURA Storage (catalogue PostgreSQL +
# données SeaweedFS + configuration).
#
# Usage: ./scripts/aura-backup.sh [destination_dir]
#
# Ce script est destiné à être exécuté sur l'hôte VPS (pas dans un conteneur).
# Il nécessite : pg_dump (client PostgreSQL), docker, tar, gzip, date.
#
# Aucun secret n'est écrit dans l'archive : .env et s3.json sont exclus.
# Ils doivent être sauvegardés séparément, hors du dépôt Git.
set -euo pipefail

# --- Répertoires par défaut (adaptez à votre déploiement) ----------------
AURA_DATA_DIR="${AURA_DATA_DIR:-/var/lib/aura-storage}"
BACKUP_DEST="${1:-${AURA_DATA_DIR}/backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_DEST}/aura-backup-${TIMESTAMP}"
CONTAINER_NAME="${AURA_API_CONTAINER:-aura-api}"
PG_CONTAINER="${AURA_PG_CONTAINER:-aura-postgres}"

mkdir -p "${BACKUP_DIR}"

echo "[aura-backup] Démarrage de la sauvegarde : ${BACKUP_DIR}"

# --- 1. Sauvegarde du catalogue PostgreSQL --------------------------------
echo "[aura-backup] Sauvegarde PostgreSQL…"
docker exec "${PG_CONTAINER}" pg_dumpall --clean --if-exists --username=postgres \
  > "${BACKUP_DIR}/catalogue.sql" 2>/dev/null || {
    echo "[aura-backup] ERREUR : pg_dumpall a échoué" >&2
    exit 1
  }

# --- 2. Sauvegarde des données SeaweedFS (volumes) ------------------------
echo "[aura-backup] Sauvegarde des données SeaweedFS…"
# Les volumes SeaweedFS sont montés sous AURA_DATA_DIR/seaweedfs
if [ -d "${AURA_DATA_DIR}/seaweedfs" ]; then
  tar -czf "${BACKUP_DIR}/seaweedfs-data.tar.gz" -C "${AURA_DATA_DIR}" seaweedfs
else
  echo "[aura-backup] ATTENTION : répertoire SeaweedFS introuvable, ignoré."
fi

# --- 3. Sauvegarde des journaux d'audit -----------------------------------
if [ -d "${AURA_DATA_DIR}/audit" ]; then
  tar -czf "${BACKUP_DIR}/audit-logs.tar.gz" -C "${AURA_DATA_DIR}" audit
fi

# --- 4. Sauvegarde des scripts et configuration (sans secrets) ------------
echo "[aura-backup] Sauvegarde des scripts…"
tar -czf "${BACKUP_DIR}/scripts.tar.gz" -C "${AURA_DATA_DIR}/.." scripts/ 2>/dev/null || true

# --- 5. Résumé ------------------------------------------------------------
echo "[aura-backup] Sauvegarde terminée : ${BACKUP_DIR}"
echo "[aura-backup] Contenu :"
ls -lh "${BACKUP_DIR}"

echo ""
echo "[aura-backup] IMPORTANT : Les secrets (.env, config/seaweedfs/s3.json,"
echo "clés SSE-S3) ne sont PAS inclus dans cette archive. Sauvegardez-les"
echo "séparément, hors du VPS et du dépôt Git."

exit 0
