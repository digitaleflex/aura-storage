# Test de persistance après redémarrage — AURA Storage (pilote VPS)
#
# Cette procédure vérifie que la stack AURA redémarre correctement après un
# reboot de l'hôte et que les données (catalogue PostgreSQL + SeaweedFS) sont
# intactes.
#
# ⚠️  Cette procédure nécessite un redémarrage réel de l'hôte VPS. Elle ne peut
# pas être exécutée depuis ce dépôt sans accès sudo.

# ---------------------------------------------------------------------------
# Étape 0 — Vérification préalable (read-only)
# ---------------------------------------------------------------------------
# Vérifier que tous les conteneurs ont une politique de redémarrage :
#   docker compose config | grep -A 2 "restart:"
# Chaque service doit avoir restart: unless-stopped ou restart: always.
#
# Vérifier que les volumes Docker sont montés depuis AURA_DATA_DIR (pas dans
# le couche writable des conteneurs) :
#   docker compose config | grep -A 5 "volumes:"
# Les données doivent persister sur l'hôte.

# ---------------------------------------------------------------------------
# Étape 1 — Prendre un "état de référence" avant reboot
# ---------------------------------------------------------------------------
# a) Créer un objet de test sur l'API (upload simple) et noter son checksum.
# b) Noter la liste des objets, espaces, applications.
# c) Vérifier que tous les conteneurs sont "healthy" :
#    docker compose ps
# d) Noter l'espace disque utilisé par AURA_DATA_DIR :
#    du -sh /var/lib/aura-storage

# ---------------------------------------------------------------------------
# Étape 2 — Redémarrer l'hôte
# ---------------------------------------------------------------------------
#   sudo reboot
#
# Attendre que l'hôte revienne en ligne (SSH, puis Docker).

# ---------------------------------------------------------------------------
# Étape 3 — Vérifier le redémarrage automatique des conteneurs
# ---------------------------------------------------------------------------
# Après le reboot, attendre que Docker démarre les conteneurs AURA :
#   docker compose ps
#
# Tous les conteneurs doivent être "running" et "healthy" sans intervention
# manuelle. Si un conteneur est arrêté, l'investiguer :
#   docker logs <conteneur>

# ---------------------------------------------------------------------------
# Étape 4 — Vérifier l'intégrité des données après reboot
# ---------------------------------------------------------------------------
# a) L'API doit répondre :
#    curl -s https://APP_DOMAIN/health/ready   # doit retourner 200
# b) Les objets doivent être présents :
#    curl -s -b cookies.txt https://APP_DOMAIN/api/v1/objects
# c) L'objet de test créé avant le reboot doit être téléchargeable :
#    # Télécharger via l'URL présignée et vérifier le checksum SHA-256
# d) L'espace disque doit être cohérent avec l'état avant reboot.

# ---------------------------------------------------------------------------
# Étape 5 — Upload/download de test après reboot
# ---------------------------------------------------------------------------
# a) Uploader un nouveau fichier de test.
# b) Vérifier qu'il apparaît dans le listing.
# c) Le télécharger et vérifier le checksum.
#
# Si toutes les étapes réussissent, le gate P0 "Persistance après reboot" est
# levé.
