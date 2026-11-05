# Durcissement SSH et pare-feu — AURA Storage (pilote VPS)
#
# Ce document décrit la procédure pour passer le pilote VPS en production :
# login SSH par clé uniquement, pare-feu restrictif (seuls 80/443 publiés),
# et console de secours confirmée.
#
# ⚠️  Toutes les commandes ci-dessous nécessitent un accès sudo interactif sur
# l'hôte VPS. Elles ne peuvent pas être exécutées depuis ce dépôt.

# ---------------------------------------------------------------------------
# Étape 1 — Installer la clé SSH d'administration
# ---------------------------------------------------------------------------
# Depuis votre poste de travail (pas sur le VPS) :
#   ssh-copy-id -i ~/.ssh/id_ed25519_aura_admin.pub aura-admin@<VPS_IP>
#
# Sur le VPS, vérifier que ~/.ssh/authorized_keys contient la clé :
#   ls -la ~/.ssh/authorized_keys   # doit être 0600
#   ls -la ~/.ssh/                  # doit être 0700

# ---------------------------------------------------------------------------
# Étape 2 — Tester le login par clé en 2e session (AVANT de fermer la 1ère)
# ---------------------------------------------------------------------------
# Ouvrir un NOUVEAU terminal et tenter :
#   ssh -i ~/.ssh/id_ed25519_aura_admin aura-admin@<VPS_IP>
#
# Si cela fonctionne, garder la première session ouverte comme secours.
# Sinon, utiliser la première session pour corriger ~/.ssh/authorized_keys.

# ---------------------------------------------------------------------------
# Étape 3 — Désactiver l'authentification par mot de passe SSH
# ---------------------------------------------------------------------------
# Sur le VPS (sudo interactif requis) :
#   sudo nano /etc/ssh/sshd_config
#
# Modifier ou ajouter :
#   PasswordAuthentication no
#   ChallengeResponseAuthentication no
#   UsePAM yes
#   PubkeyAuthentication yes
#   PermitRootLogin no
#   MaxAuthTries 3
#
# Puis recharger SSH :
#   sudo systemctl reload ssh
#   # ou : sudo systemctl reload ssh.socket

# ---------------------------------------------------------------------------
# Étape 4 — Configurer le pare-feu (ufw) — seuls 80/443 publiés
# ---------------------------------------------------------------------------
# Sur le VPS (sudo interactif requis) :
#
#   sudo ufw default deny incoming
#   sudo ufw default allow outgoing
#   sudo ufw allow 22/tcp          # SSH (garder l'accès admin)
#   sudo ufw allow 80/tcp          # HTTP (Traefik, HTTP-01 challenge)
#   sudo ufw allow 443/tcp         # HTTPS (Traefik)
#   sudo ufw enable
#
# Vérifier :
#   sudo ufw status verbose
#
# Résultat attendu : seuls 22, 80, 443 sont ouverts. Rien d'autre.

# ---------------------------------------------------------------------------
# Étape 5 — Confirmer que les ports internes SeaweedFS ne sont PAS publiés
# ---------------------------------------------------------------------------
# Seul Traefik publie 80/443. Les ports SeaweedFS (master, volume, filer,
# S3 gateway, metrics) doivent rester sur le réseau Docker interne, non
# publiés sur l'hôte. Vérifier avec :
#
#   sudo ss -tlnp | grep -E ':80|:443|:22'
#   docker compose ps
#
# Aucun port SeaweedFS ne doit apparaître sur l'hôte.

# ---------------------------------------------------------------------------
# Étape 6 — Confirmer la console de secours
# ---------------------------------------------------------------------------
# Vérifier que le panel InterServer (ou équivalent) propose une console de
# secours (KVM / série) accessible en cas de lock-out SSH. Tester l'accès
# à la console avant de durcir définitivement SSH.

# ---------------------------------------------------------------------------
# Étape 7 — Validation finale
# ---------------------------------------------------------------------------
#   sudo sshd -T                 # config SSH effective (doit montrer PasswordAuthentication no)
#   sudo ufw status verbose      # pare-feu (seuls 22/80/443)
#   ssh -i clé aura-admin@VPS    # login par clé fonctionnel
#
# Une fois validé, le gate P0 "SSH key-only + pare-feu" est levé.
