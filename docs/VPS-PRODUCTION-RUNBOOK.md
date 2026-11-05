# Runbook — Validation des 3 gates P0 avant production (VPS AURA)

> **Quand :** Avant tout import de données originales sur le pilote VPS.
> **Qui :** Vous (accès `sudo` requis sur le VPS).
> **Durée estimée :** 45–60 minutes.
> **Risque :** Aucun sur les données existantes — toutes les commandes sont en lecture seule sauf le test de reboot.

---

## Table des matières

1. [Prérequis](#1-prérequis)
2. [Gate 1 — Sauvegarde et restauration indépendante (ISSUE-002)](#gate-1)
3. [Gate 2 — SSH key-only + Pare-feu host (ISSUE-003)](#gate-2)
4. [Gate 3 — Persistance après redémarrage (ISSUE-004)](#gate-3)
5. [Sign-off final](#sign-off-final)

---

<a id="1-prérequis"></a>
## 1. Prérequis

Vérifiez avant de commencer :

| Élément | Comment vérifier |
|---------|------------------|
| Accès SSH au VPS | `ssh aura-admin@<VPS_IP>` fonctionne |
| Droits sudo | `sudo -n true` ou `sudo true` demande un mot de passe |
| Docker installé | `docker --version` et `docker compose version` répondent |
| Stack AURA démarrée | `cd /opt/aura-storage && docker compose ps` montre les conteneurs |
| Accès à l'API | `curl -s https://APP_DOMAIN/health/ready` retourne 200 |

> **AURA_DATA_DIR** : par défaut `/var/lib/aura-storage`. Adaptez si votre déploiement utilise un autre chemin.

---

<a id="gate-1"></a>
## Gate 1 — Sauvegarde et restauration indépendante (ISSUE-002)

**Objectif :** Prouver qu'on peut sauvegarder et restaurer le catalogue + les données SeaweedFS sans perdre quoi que ce soit.

### Étape 1.1 — Créer une sauvegarde complète

Sur le VPS :

```bash
cd /opt/aura-storage
bash ./scripts/aura-backup.sh /var/lib/aura-storage/backups 7
```

**Ce qui est sauvegardé :**
- `catalogue.sql` — dump complet de PostgreSQL
- `seaweedfs-data.tar.gz` — données objets (volumes SeaweedFS)
- `audit-logs.tar.gz` — journaux d'audit
- `scripts.tar.gz` — scripts de déploiement

**Ce qui n'est PAS sauvegardé (à faire séparément) :**
- `.env` (mots de passe, clés S3, SSE-S3)
- `config/seaweedfs/s3.json` (credentials S3)
- Clé SSE-S3 (`WEED_S3_SSE_KEK`)

```bash
# Vérifier que le backup a été créé
ls -lh /var/lib/aura-storage/backups/
```

### Étape 1.2 — Vérifier l'intégrité de l'archive

```bash
bash ./scripts/aura-backup-verify.sh /var/lib/aura-storage/backups/aura-backup-*
```

Doit afficher : `Sauvegarde vérifiée avec succès.`

### Étape 1.3 — Tester la restauration sur un environnement isolé

> ⚠️  Ne restaurez PAS sur le VPS de production. Utilisez une VM de test ou un autre VPS vide.

Sur l'environnement de test :

```bash
# 1. Installer Docker et Docker Compose
# 2. Cloner le dépôt
git clone https://github.com/digitaleflex/aura-storage.git
cd aura-storage

# 3. Restaurer les secrets (.env, s3.json, clé SSE-S3) depuis votre copie hors-ligne
cp .env.example .env
# Éditer .env avec les vraies valeurs

# 4. Démarrer PostgreSQL seul
docker compose up -d postgres

# 5. Attendre que PostgreSQL soit prêt
docker compose ps postgres

# 6. Restaurer le catalogue
cat /chemin/vers/aura-backup-*/catalogue.sql | docker exec -i aura-postgres psql --username=postgres

# 7. Restaurer les données SeaweedFS
docker compose stop
tar -xzf /chemin/vers/aura-backup-*/seaweedfs-data.tar.gz -C /var/lib/aura-storage

# 8. Redémarrer tout
docker compose up -d

# 9. Vérifier
curl -s https://APP_DOMAIN/health/ready
```

### Critères d'acceptation Gate 1

- [ ] `aura-backup.sh` s'exécute sans erreur
- [ ] `aura-backup-verify.sh` valide l'archive
- [ ] Restauration sur environnement isolé réussie
- [ ] Objets restaurés : checksums SHA-256 correspondent
- [ ] Objets restaurés : téléchargeables via l'API

---

<a id="gate-2"></a>
## Gate 2 — SSH key-only + Pare-feu host (ISSUE-003)

**Objectif :** Sécuriser l'accès au VPS — seuls les ports 22/80/443 publiés, login par clé uniquement.

### Étape 2.1 — Installer votre clé SSH (depuis VOTRE machine, pas le VPS)

```bash
# Depuis votre ordinateur local
ssh-copy-id -i ~/.ssh/id_ed25519_aura_admin.pub aura-admin@<VPS_IP>
```

### Étape 2.2 — Tester le login par clé (2e session)

**OUVREZ UN NOUVEAU TERMINAL** et tentez :

```bash
ssh -i ~/.ssh/id_ed25519_aura_admin aura-admin@<VPS_IP>
```

> ⚠️  Gardez la première session SSH ouverte comme secours tant que le test n'est pas concluant.

### Étape 2.3 — Désactiver l'authentification par mot de passe SSH

Sur le VPS (sudo requis) :

```bash
sudo nano /etc/ssh/sshd_config
```

Modifier ou ajouter ces lignes :

```
PasswordAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
PubkeyAuthentication yes
PermitRootLogin no
MaxAuthTries 3
```

Puis recharger SSH :

```bash
sudo systemctl reload ssh
# ou sur Ubuntu 26.04 :
sudo systemctl reload ssh.socket
```

### Étape 2.4 — Configurer le pare-feu (ufw)

Sur le VPS (sudo requis) :

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP (Traefik, HTTP-01 challenge)
sudo ufw allow 443/tcp     # HTTPS (Traefik)
sudo ufw enable
```

### Étape 2.5 — Vérifier que les ports SeaweedFS ne sont pas publiés

```bash
# Seuls 22, 80, 443 doivent apparaître
sudo ss -tlnp | grep -E ':22|:80|:443'

# Aucun port SeaweedFS (master, volume, filer, S3, metrics) ne doit apparaître sur l'hôte
docker compose ps
```

### Étape 2.6 — Confirmer la console de secours

Vérifiez que votre panel VPS (InterServer ou autre) propose une console de secours (KVM / série) accessible en cas de lock-out SSH.

### Critères d'acceptation Gate 2

- [ ] `~/.ssh/authorized_keys` présent (0600), `~/.ssh` (0700)
- [ ] Login SSH par clé fonctionne en 2e session
- [ ] `sudo sshd -T` montre `passwordauthentication no`
- [ ] `sudo ufw status verbose` : seuls 22, 80, 443 ouverts
- [ ] Aucun port SeaweedFS publié sur l'hôte
- [ ] Console de secours confirmée

---

<a id="gate-3"></a>
## Gate 3 — Persistance après redémarrage (ISSUE-004)

**Objectif :** Prouver que la stack AURA redémarre automatiquement après un reboot de l'hôte et que les données sont intactes.

### Étape 3.1 — Pré-vérification (read-only)

```bash
cd /opt/aura-storage
bash ./scripts/reboot-persistence-precheck.sh
```

Vérifiez que :
- Tous les conteneurs ont une politique `restart: unless-stopped` ou `always`
- Les volumes sont montés depuis l'hôte (`AURA_DATA_DIR`)
- Tous les conteneurs sont actuellement "healthy"

### Étape 3.2 — État de référence avant reboot

```bash
# Créer un objet de test
curl -s -X POST https://APP_DOMAIN/api/v1/objects/upload-intents \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: <csrf>" \
  -b cookies.txt \
  -d '{"size_bytes": 1024, "content_type": "text/plain"}' | jq .

# Noter l'ID de l'objet et le checksum attendu
# Noter l'espace disque : du -sh /var/lib/aura-storage
```

### Étape 3.3 — Redémarrer l'hôte

```bash
sudo reboot
```

Attendez que l'hôte revienne en ligne (SSH accessible à nouveau).

### Étape 3.4 — Vérifier le redémarrage automatique

```bash
docker compose ps
```

Tous les conteneurs AURA doivent être "running" et "healthy" **sans intervention manuelle**.

Si un conteneur est arrêté :

```bash
docker logs <nom-conteneur>
```

### Étape 3.5 — Vérifier l'intégrité des données après reboot

```bash
# L'API doit répondre
curl -s https://APP_DOMAIN/health/ready
# Doit retourner 200

# Les objets doivent être présents
curl -s -b cookies.txt https://APP_DOMAIN/api/v1/objects | jq .
```

L'objet de test créé avant le reboot doit apparaître avec le bon checksum SHA-256.

### Étape 3.6 — Test upload/download après reboot

```bash
# Uploader un nouveau fichier
# Vérifier qu'il apparaît dans le listing
# Le télécharger et vérifier le checksum
```

### Critères d'acceptation Gate 3

- [ ] Tous les conteneurs ont une politique de redémarrage définie
- [ ] Les volumes sont montés depuis l'hôte (pas dans la couche writable des conteneurs)
- [ ] Après reboot : tous les conteneurs "healthy" automatiquement
- [ ] `GET /health/ready` retourne 200
- [ ] Objets créés avant le reboot : intacts, checksums OK
- [ ] Nouvel upload/download après reboot : fonctionne

---

<a id="sign-off-final"></a>
## Sign-off final

Une fois les 3 gates validés :

| Gate | Validé le | Signature |
|------|-----------|-----------|
| Gate 1 — Backup/Restauration | ___________ | ___________ |
| Gate 2 — SSH/Pare-feu | ___________ | ___________ |
| Gate 3 — Persistance reboot | ___________ | ___________ |

**Le pilote AURA est alors accepté pour l'import de données originales.**

---

## Commandes de secours (en cas de problème)

| Problème | Commande |
|----------|----------|
| Vérifier l'état des conteneurs | `docker compose ps` |
| Voir les logs d'un conteneur | `docker logs <nom>` |
| Vérifier les ports publiés | `sudo ss -tlnp` |
| Vérifier le pare-feu | `sudo ufw status verbose` |
| Vérifier la config SSH | `sudo sshd -T \| grep password` |
| Redémarrer la stack | `docker compose restart` |
