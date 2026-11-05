# Restauration d'AURA Storage depuis une sauvegarde
#
# Ce document décrit la procédure de restauration complète après une sauvegarde
# effectuée avec scripts/aura-backup.sh. Elle doit être testée sur un
# environnement isolé avant toute mise en production (gate QA-01).

# Prérequis
# ---------
# - VPS Ubuntu avec Docker et Docker Compose opérationnels
# - Fichier de sauvegarde : aura-backup-YYYYMMDD-HHMMSS/ (dossier extrait)
# - Secrets restaurés séparément : .env, config/seaweedfs/s3.json, clé SSE-S3
# - Accès root ou sudo sur l'hôte

# 1. Préparation de l'hôte
# ------------------------
# a) Arrêter la stack AURA si elle tourne :
#    cd /opt/aura-storage && docker compose down
#
# b) Vérifier que PostgreSQL et SeaweedFS sont arrêtés :
#    docker ps -a | grep aura

# 2. Restauration du catalogue PostgreSQL
# ---------------------------------------
# a) Démarrer uniquement le conteneur PostgreSQL :
#    docker compose up -d postgres
#
# b) Attendre que PostgreSQL soit prêt (healthcheck "healthy") :
#    docker compose ps postgres
#
# c) Restaurer le dump :
#    cat aura-backup-*/catalogue.sql | docker exec -i aura-postgres psql --username=postgres
#
# d) Vérifier que les tables sont présentes :
#    docker exec aura-postgres psql --username=postgres -c "\dt"

# 3. Restauration des données SeaweedFS
# -------------------------------------
# a) Arrêter PostgreSQL et les autres conteneurs :
#    docker compose stop
#
# b) Extraire les données SeaweedFS dans AURA_DATA_DIR (ex: /var/lib/aura-storage) :
#    tar -xzf aura-backup-*/seaweedfs-data.tar.gz -C /var/lib/aura-storage
#
# c) Restaurer les journaux d'audit (optionnel, si présents) :
#    tar -xzf aura-backup-*/audit-logs.tar.gz -C /var/lib/aura-storage

# 4. Restauration des secrets (hors sauvegarde)
# ---------------------------------------------
# a) Recréer .env à partir de .env.example avec les valeurs réelles :
#    cp .env.example .env
#    # Éditer .env avec les vraies valeurs (AURA_API_ADMIN_PASSWORD,
#    # AURA_S3_ACCESS_KEY, AURA_S3_SECRET_KEY, WEED_S3_SSE_KEK, etc.)
#
# b) Régénérer la configuration SeaweedFS :
#    bash ./scripts/generate-config.sh
#
# c) Vérifier que la clé SSE-S3 (WEED_S3_SSE_KEK) correspond à celle
#    utilisée lors de la sauvegarde. Si elle diffère, les objets chiffrés
#    seront illisibles.

# 5. Redémarrage de la stack
# --------------------------
# a) Démarrer tous les conteneurs :
#    docker compose up -d
#
# b) Attendre que tous les conteneurs soient sains :
#    docker compose ps
#
# c) Vérifier l'API :
#    curl -s https://APP_DOMAIN/health/ready

# 6. Vérification post-restauration
# ---------------------------------
# a) Se connecter à l'API et vérifier que les objets sont visibles :
#    curl -s -b cookies.txt https://APP_DOMAIN/api/v1/objects
#
# b) Vérifier qu'un téléchargement d'objet fonctionne (S3 accessible) :
#    # Télécharger un objet via une URL présignée
#
# c) Vérifier l'intégrité des données SeaweedFS (scrub) :
#    curl -s -X POST https://APP_DOMAIN/api/v1/admin/integrity/scrub

# 7. Signes de succès
# -------------------
# - Tous les conteneurs AURA sont "healthy"
# - GET /health/ready retourne 200
# - Les objets créés avant la sauvegarde sont listés
# - Les checksums SHA-256 des objets restaurés correspondent
# - Aucun objet n'est marqué "suspect" ou "missing" dans l'intégrité

# Rollback en cas d'échec
# -----------------------
# Si la restauration échoue à mi-chemin, arrêter la stack, restaurer
# depuis une sauvegarde antérieure, et recommencer. Ne jamais mélanger
# des données partielles avec une restauration incomplète.
