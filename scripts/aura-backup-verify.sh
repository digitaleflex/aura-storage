#!/usr/bin/env bash
#
# aura-backup-verify.sh — Vérifie l'intégrité d'une archive de sauvegarde AURA.
#
# Usage: ./scripts/aura-backup-verify.sh <backup_dir>
#
# Vérifie que :
# - Le dump PostgreSQL est valide (pg_restore --list)
# - L'archive SeaweedFS est lisible (tar -tzf)
# - Les fichiers attendus sont présents

set -euo pipefail

BACKUP_DIR="${1:?Usage: $0 <backup_dir>}"

if [ ! -d "${BACKUP_DIR}" ]; then
  echo "ERREUR : répertoire de sauvegarde introuvable : ${BACKUP_DIR}" >&2
  exit 1
fi

echo "[verify] Vérification de ${BACKUP_DIR}"

# Fichiers attendus
EXPECTED=(catalogue.sql)
for f in "${EXPECTED[@]}"; do
  if [ ! -f "${BACKUP_DIR}/${f}" ]; then
    echo "ERREUR : fichier manquant : ${f}" >&2
    exit 1
  fi
done

# Vérifier le dump SQL
if command -v pg_restore >/dev/null 2>&1; then
  echo "[verify] Vérification du dump PostgreSQL…"
  pg_restore --list "${BACKUP_DIR}/catalogue.sql" >/dev/null 2>&1 || {
    echo "ERREUR : dump PostgreSQL invalide" >&2
    exit 1
  }
  echo "[verify] Dump PostgreSQL valide."
else
  echo "[verify] pg_restore non disponible, vérification ignorée."
fi

# Vérifier l'archive SeaweedFS si présente
if [ -f "${BACKUP_DIR}/seaweedfs-data.tar.gz" ]; then
  echo "[verify] Vérification de l'archive SeaweedFS…"
  tar -tzf "${BACKUP_DIR}/seaweedfs-data.tar.gz" >/dev/null 2>&1 || {
    echo "ERREUR : archive SeaweedFS invalide" >&2
    exit 1
  }
  echo "[verify] Archive SeaweedFS valide."
fi

echo "[verify] Sauvegarde vérifiée avec succès."
