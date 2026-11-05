#!/usr/bin/env bash
#
# aura-backup.sh — Sauvegarde complète d'AURA Storage (catalogue PostgreSQL +
# données SeaweedFS + configuration).
#
# Usage: ./scripts/aura-backup.sh [destination_dir] [retention_count]
#
# Ce script est destiné à être exécuté sur l'hôte VPS (pas dans un conteneur).
# Il nécessite : pg_dump (client PostgreSQL), docker, tar, gzip, date.
#
# ⚠️  AVERTISSEMENT : Par défaut, les backups sont écrits en LOCAL sur le VPS.
#   C'est une solution TEMPORAIRE en attendant un serveur de secours externe.
#   Les archives doivent être copiées sur un autre serveur dès que possible
#   (règle 3-2-1 : 3 copies, 2 supports, 1 hors site).
#
# Aucun secret n'est écrit dans l'archive : .env et s3.json sont exclus.
# Ils doivent être sauvegardés séparément, hors du dépôt Git.
set -euo pipefail

# --- Répertoires par défaut (adaptez à votre déploiement) ----------------
AURA_DATA_DIR="${AURA_DATA_DIR:-/var/lib/aura-storage}"
BACKUP_DEST="${1:-${AURA_DATA_DIR}/backups}"
RETENTION="${2:-7}"           # Nombre de backups à garder (défaut: 7)
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_DEST}/aura-backup-${TIMESTAMP}"
CONTAINER_NAME="${AURA_API_CONTAINER:-aura-api}"
PG_CONTAINER="${AURA_PG_CONTAINER:-aura-postgres}"

# --- Vérification de l'espace disque avant de commencer --------------------
AVAILABLE_KB=$(df "${BACKUP_DEST}" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
if [ "${AVAILABLE_KB}" -lt 1048576 ]; then  # moins de 1 Go disponible
  echo "[aura-backup] ERREUR : Espace disque insuffisant (< 1 Go) sur ${BACKUP_DEST}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

echo "[aura-backup] Démarrage de la sauvegarde : ${BACKUP_DIR}"
echo "[aura-backup] Rétention : ${RETENTION} backup(s) maximum"

# --- 1. Sauvegarde du catalogue PostgreSQL --------------------------------
echo "[aura-backup] Sauvegarde PostgreSQL…"
docker exec "${PG_CONTAINER}" pg_dumpall --clean --if-exists --username=postgres \
  > "${BACKUP_DIR}/catalogue.sql" 2>/dev/null || {
    echo "[aura-backup] ERREUR : pg_dumpall a échoué" >&2
    exit 1
  }

# --- 2. Sauvegarde des données SeaweedFS (volumes) ------------------------
echo "[aura-backup] Sauvegarde des données SeaweedFS…"
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

# --- 5. Rotation : supprimer les backups les plus anciens -----------------
echo "[aura-backup] Rotation des backups (garde les ${RETENTION} plus récents)…"
# Lister les répertoires de backup, trier par date (plus récent d'abord),
# supprimer ceux au-delà de la rétention.
ls -1d "${BACKUP_DEST}"/aura-backup-* 2>/dev/null | sort -r | \
  tail -n +$((RETENTION + 1)) | \
  while read -r old_backup; do
    echo "[aura-backup] Suppression de l'ancien backup : ${old_backup}"
    rm -rf "${old_backup}"
  done

# --- 6. Résumé ------------------------------------------------------------
echo "[aura-backup] Sauvegarde terminée : ${BACKUP_DIR}"
echo "[aura-backup] Contenu :"
ls -lh "${BACKUP_DIR}"
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" 2>/dev/null | awk '{print $1}' || echo "inconnu")
echo "[aura-backup] Taille totale : ${TOTAL_SIZE}"

echo ""
echo "[aura-backup] ⚠️  RAPPEL : Ce backup est stocké en LOCAL sur ce VPS."
echo "[aura-backup]     Dès qu'un serveur de secours est disponible, copiez"
echo "[aura-backup]     les archives vers celui-ci (rsync/scp/sftp)."
echo "[aura-backup]     Les secrets (.env, config/seaweedfs/s3.json, clés SSE-S3)"
echo "[aura-backup]     ne sont PAS inclus. Sauvegardez-les séparément."

exit 0
