# Checklist de validation VPS — Gates P0 (avant import de données originales)

Ce document recense les **3 gates de production** qui doivent être validés manuellement sur le VPS pilote avant tout import de fichiers de valeur (PDF, audio, etc.).

> ⚠️  Ces opérations nécessitent un accès **sudo interactif** sur le VPS. Elles ne peuvent pas être automatisées depuis ce dépôt.

---

## Gate 1 — Sauvegarde et restauration indépendante (ISSUE-002)

**Pourquoi :** une restauration indépendante réussie est un gate obligatoire avant tout import de données originales (`docs/BACKUP-RESTORE.md`, `docs/QA-01-CHECKLIST.md`).

### Procédure

1. **Créer une sauvegarde complète (en local sur le VPS pour l'instant) :**
   ```bash
   cd /opt/aura-storage
   bash ./scripts/aura-backup.sh /var/lib/aura-storage/backups 7
   ```
   Le second argument (`7`) est le nombre de backups à garder (rotation automatique).

   > ⚠️  Ce backup est stocké **en local sur le VPS** en attendant un serveur de secours.
   > Dès qu'un serveur externe est disponible, copiez les archives vers celui-ci
   > (rsync/scp/sftp). Ne laissez pas les backups uniquement sur le VPS de production.

2. **Vérifier l'intégrité de l'archive :**
   ```bash
   bash ./scripts/aura-backup-verify.sh /var/lib/aura-storage/backups/aura-backup-*
   ```

3. **Restaurer sur un environnement isolé** (pas le VPS de production) :
   - Voir `docs/RESTORE-PROCEDURE.md` (étapes 1 à 6)

4. **Vérifier que les objets restaurés sont intacts** (checksums SHA-256 correspondants)

### Critères d'acceptation

- [ ] `aura-backup.sh` s'exécute sans erreur
- [ ] `aura-backup-verify.sh` valide l'archive (dump PostgreSQL + archive SeaweedFS)
- [ ] Restauration sur environnement isolé réussie
- [ ] Objets restaurés : checksums SHA-256 OK, téléchargeables
- [ ] Procédure documentée et reproductible

---

## Gate 2 — SSH key-only + Pare-feu host (ISSUE-003)

**Pourquoi :** seuls les ports 80/443 doivent être publiés (Traefik). Le login SSH par mot de passe doit être désactivé. La console de secours doit être confirmée.

### Procédure

Sur le VPS (sudo interactif requis) :

1. **Installer la clé SSH d'administration** (depuis votre poste de travail) :
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519_aura_admin.pub aura-admin@<VPS_IP>
   ```

2. **Tester le login par clé en 2e session** (garder la première session ouverte comme secours) :
   ```bash
   ssh -i ~/.ssh/id_ed25519_aura_admin aura-admin@<VPS_IP>
   ```

3. **Durcir SSH** (`/etc/ssh/sshd_config`) :
   ```
   PasswordAuthentication no
   ChallengeResponseAuthentication no
   PubkeyAuthentication yes
   PermitRootLogin no
   MaxAuthTries 3
   ```
   Puis : `sudo systemctl reload ssh`

4. **Configurer le pare-feu (ufw)** — seuls 22/80/443 publiés :
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

5. **Vérifier que les ports SeaweedFS ne sont pas publiés** :
   ```bash
   sudo ss -tlnp | grep -E ':80|:443|:22'
   docker compose ps
   ```

6. **Confirmer la console de secours** (panel InterServer ou équivalent)

### Critères d'acceptation

- [ ] `~/.ssh/authorized_keys` présent (0600), `~/.ssh` (0700)
- [ ] Login SSH par clé fonctionne en 2e session
- [ ] `sudo sshd -T` : `passwordauthentication no`
- [ ] `sudo ufw status verbose` : seuls 22, 80, 443 ouverts
- [ ] Aucun port SeaweedFS publié sur l'hôte
- [ ] Console de secours confirmée et testable

---

## Gate 3 — Persistance après redémarrage du host (ISSUE-004)

**Pourquoi :** prouver que la stack AURA redémarre automatiquement après un reboot de l'hôte et que les données sont intactes.

### Procédure

1. **Pré-vérification (read-only) :**
   ```bash
   bash ./scripts/reboot-persistence-precheck.sh
   ```

2. **Prendre un état de référence avant reboot** :
   - Créer un objet de test via l'API, noter son checksum SHA-256
   - Noter la liste des objets, espaces, applications
   - Vérifier que tous les conteneurs sont "healthy" : `docker compose ps`
   - Noter l'espace disque : `du -sh /var/lib/aura-storage`

3. **Redémarrer l'hôte :**
   ```bash
   sudo reboot
   ```

4. **Après le reboot, vérifier le redémarrage automatique :**
   - Attendre que Docker démarre les conteneurs AURA
   - `docker compose ps` : tous "running" et "healthy" sans intervention manuelle

5. **Vérifier l'intégrité des données après reboot :**
   ```bash
   curl -s https://APP_DOMAIN/health/ready   # doit retourner 200
   curl -s -b cookies.txt https://APP_DOMAIN/api/v1/objects
   ```
   - L'objet de test créé avant le reboot doit être téléchargeable avec le bon checksum SHA-256

6. **Test upload/download après reboot :**
   - Uploader un nouveau fichier de test
   - Vérifier qu'il apparaît dans le listing et est téléchargeable

### Critères d'acceptation

- [ ] Tous les conteneurs ont une politique de redémarrage (`restart: unless-stopped` ou `always`)
- [ ] Les volumes sont montés depuis l'hôte (`AURA_DATA_DIR`)
- [ ] Après reboot : tous les conteneurs "healthy" automatiquement
- [ ] `GET /health/ready` retourne 200
- [ ] Objets créés avant le reboot : intacts, checksums OK
- [ ] Nouvel upload/download après reboot : fonctionne

---

## Sign-off

Une fois les 3 gates validés :

- [ ] Gate 1 (Backup/Restauration) — validé le : ___________
- [ ] Gate 2 (SSH/Pare-feu) — validé le : ___________
- [ ] Gate 3 (Persistance reboot) — validé le : ___________

Le pilote AURA est alors **accepté pour l'import de données originales**.
