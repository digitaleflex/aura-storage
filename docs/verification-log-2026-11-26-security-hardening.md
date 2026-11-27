# Journal de vérification — Audit de sécurité et durcissement (2026-11-26)

## Statut

| Champ | Valeur |
|---|---|
| Date | 2026-11-26 |
| Hôte audité | `vps3718250.trouble-free.net` (pilote Aura) |
| Système | Ubuntu 26.04.1 LTS, noyau 7.0.0-38-generic |
| IP publique | `153.75.248.230` |
| IP Tailscale | `100.76.146.65` |
| Périmètre | Accès SSH, pare-feu hôte, fail2ban, exposition Traefik, journaux applicatifs |
| Méthode | Audit en lecture seule, puis durcissement appliqué et revérifié |
| Conclusion | Aucune compromission détectée. Brute-force SSH continu et massif, désormais filtré. |

> Ce journal complète [SECURITY.md](SECURITY.md), [HOST-BOOTSTRAP-CHECKLIST.md](HOST-BOOTSTRAP-CHECKLIST.md) et [AUDIT-COMPLET-2026-10-24.md](AUDIT-COMPLET-2026-10-24.md). Il apporte une preuve datée pour les points « SSH key-only login » et « host firewall » qui restaient ouverts dans le [README](../README.md).

---

## 1. Synthèse exécutive

Le serveur pilote est soumis à un **brute-force SSH permanent** depuis plusieurs réseaux. Plus de **20 000 mots de passe erronés** et **8 941 tentatives sur utilisateurs inexistants** ont été relevés sur les journaux conservés, dont **94 tentatives dans l'heure précédant l'audit**. Les attaques ciblent principalement le compte `root` avec des noms d'utilisateurs et des mots de passe génériques : il s'agit de scans Internet automatisés, **pas d'une fuite du mot de passe**.

Aucune connexion réussie n'a été observée depuis une IP attaquante. Toutes les authentifications réussies proviennent d'adresses connues de l'exploitant.

Trois faiblesses structurelles ont été confirmées avant intervention :

1. pare-feu hôte **inactif** ;
2. fail2ban **absent** ;
3. `PermitRootLogin yes` et `PasswordAuthentication yes`.

Elles sont désormais traitées : UFW actif, fail2ban opérationnel avec un filtre adapté à Ubuntu 26.04, et connexion root interdite. L'authentification par mot de passe reste volontairement activée (décision de l'exploitant, voir §6).

---

## 2. Méthode et sources

Aucune modification n'a été faite avant la collecte des preuves. Les sources consultées :

| Source | Usage |
|---|---|
| `/var/log/auth.log`, `/var/log/auth.log.1` | Tentatives SSH (montés en lecture seule dans un conteneur) |
| `journalctl -u ssh` | Détection du nom de processus réel (`sshd-session`) |
| `journalctl -u fail2ban` | Validation des bannissements |
| `docker logs aura-001-traefik` | Requêtes HTTP, codes de statut, IP sources |
| `aura-audit.jsonl` | Événements applicatifs (login, upload, admin…) |
| `sudo ufw status verbose`, `sshd -T` | État effectif du pare-feu et de SSH |

Note : sur Ubuntu 26.04, les sessions SSH sont journalisées sous `_COMM=sshd-session`. Le jail fail2ban fourni par défaut ne surveillait que `_COMM=sshd` et aurait ignoré la majorité des échecs. Ce point est la raison du correctif appliqué en §4.2.

---

## 3. Constats

### 3.1 Tentatives SSH

Période couverte : contenus de `auth.log` et `auth.log.1` (≈ deux semaines).

| Indicateur | Valeur |
|---|---:|
| `Failed password` | 20 022 |
| `Invalid user` | 8 941 |
| `Accepted password` (hors lignes `sudo` parasite) | 21 |
| `Accepted publickey` | 6 |
| Échecs sur la dernière heure d'audit | 94 |

**IP les plus actives :**

| IP | Échecs |
|---|---:|
| `77.239.124.43` | 1 595 |
| `77.239.124.69` | 1 571 |
| `77.239.124.158` | 1 286 |
| `77.239.124.153` | 1 286 |
| `77.239.124.80` | 500 |
| `77.239.124.31` | 500 |
| `49.72.213.251` | 427 |
| `77.239.124.67` | 400 |
| `146.70.218.122` | 314 |
| `114.245.195.82` | 246 |

**Noms d'utilisateurs testés :** `ubuntu` (707), `admin` (582), `user` (461), `test` (188), `debian` (182), `deploy` (143), `Tronlong` (132), `ftpuser` (91), `oracle` (87), `pi` (77), `postgres` (51), `openclaw` (50)… et un très grand nombre de tentatives directes sur `root`.

**Analyse des succès :**

| IP | Succès | Échecs | Interprétation |
|---|---:|---:|---|
| `154.72.113.52` | 17 | 0 | IP connue de l'exploitant |
| `154.72.112.76` | 4 | 0 | IP connue de l'exploitant |
| `197.234.219.141` | 1 | 0 | IP connue de l'exploitant |
| `134.33.70.253` | 1 (clé) | 0 | IP connue, clé `ED25519 SHA256:YUP4ZlD1dCMTuTRkg51E61fimbxWU4HI2K2Blj8PcOE` |
| `77.239.124.*`, `49.72.213.251`, `146.70.218.122` | **0** | ≥ 4 000 | Aucune réussite |

**Conclusion :** aucune authentification réussie depuis une IP d'attaque. La fuite du mot de passe est exclue par les journaux ; le risque reste la devinette, pas l'exposition.

### 3.2 Requêtes HTTP / Traefik

4 755 lignes d'accès analysées.

| Statut | Nombre | Lecture |
|---|---:|---|
| 200 | 1 645 | Trafic normal |
| 404 | 1 895 | Scans de chemins inexistants |
| 403 | 615 | Accès refusés correctement appliqués |
| 302 | 180 | Redirections |
| 401 | 30 | Authentification requise (utilisateur légitime) |
| 500 | 11 | Erreurs applicatives `aura-app` depuis l'IP exploitant |

Les 403 se répartissent sur :

- `aura-s3@docker` : 333 (dont 327 depuis `34.156.242.77`) ;
- `aura-swagger@docker` : 274 (depuis `34.176.187.68`) ;
- `aura-swagger-api@docker` : 6.

Les floods de 404 proviennent notamment de `35.240.21.102` (331), `34.79.200.121` (330), `34.52.136.252` (330), `37.66.235.62` (530 requêtes au total). Aucune requête n'a abouti à un accès non autorisé : les contrôles d'accès ont renvoyé 401/403 comme attendu.

Le journal d'accès Traefik est activé (`--accesslog=true`) mais les chemins sont volontairement supprimés (`--accesslog.fields.names.RequestPath=drop`). L'analyse ne peut donc pas identifier les URL exactes testées ; seule l'origine et le statut sont disponibles.

### 3.3 Journal applicatif Aura

`aura-audit.jsonl` : 5 208 événements.

| Action | Résultat | Nombre |
|---|---|---:|
| `login` | success | 1 276 |
| `login` | failure | 139 |
| `login` | rate_limited | 10 |
| `upload-intent` | — | 135 |
| `admin.*` | — | ≥ 460 |

Les échecs de login sont concentrés sur octobre 2026 (période de développement) et le limiteur de débit a bien été déclenché à 10 reprises. Aucune élévation de privilège ni création d'identité suspecte n'a été relevée.

### 3.4 Configuration initiale

| Contrôle | Avant | Après |
|---|---|---|
| `ufw status` | `inactive` | `active` |
| fail2ban | absent | actif, jail `sshd` chargé |
| `PermitRootLogin` | `yes` | `no` |
| `PasswordAuthentication` | `yes` | `yes` (conservé) |
| `MaxAuthTries` | défaut (6) | 3 |
| `LoginGraceTime` | défaut (120 s) | 30 s |
| Lecture des journaux par l'exploitant | non | groupe `systemd-journal` |

---

## 4. Actions appliquées

### 4.1 Accès et clé de travail

Une paire de clés dédiée a été créée pour le serveur distant `vmi3782410` (`100.119.132.45`, VPS Contabo séparé) afin de permettre l'audit depuis une machine distincte :

```text
~/.ssh/id_ed25519_lesaint_aura_storage_20261125
~/.ssh/id_ed25519_lesaint_aura_storage_20261125.pub
```

Clé publique déployée sur ce serveur :

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB+m7tvX54sshSeGYbhROUxtdIBdxvuUuJPIJpdEotHQ lesaint@100.119.132.45-aura-storage-20261125
```

Un alias `vmi` a été ajouté dans `~/.ssh/config` (HostName `100.119.132.45`, User `lesaint`, IdentitiesOnly `yes`). Tailscale 1.104.7 a été installé sur le pilote et connecté au tailnet ; la latence mesurée vers le serveur distant est de 82 ms avec un débit d'environ 13 Mo/s.

La clé publique de travail locale a été ajoutée à `~/.ssh/authorized_keys` du pilote pour rendre possible une authentification sans mot de passe :

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIO+KxYDkwGDGbldo5p/RsbfO7kb2z09GBtFb0vrpbG5J deploy@aura-storage
```

Test : `ssh aura-admin@127.0.0.1` avec `BatchMode=yes` → `CLE_OK`.

### 4.2 fail2ban avec filtre corrigé

Installation :

```bash
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
```

Le fichier `/etc/fail2ban/jail.d/defaults-debian.conf` active le jail `sshd` mais avec `journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd`. Sur Ubuntu 26.04, 419 entrées sur 439 utilisent `_COMM=sshd-session` : le jail par défaut aurait laissé passer l'essentiel des attaques.

Fichier ajouté : `/etc/fail2ban/jail.d/jail.local`

```ini
[sshd]
enabled = true
backend = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service
maxretry = 5
findtime = 600
bantime = 3600
bantime.increment = true
bantime.factor = 2
bantime.maxtime = 604800
```

Redémarrage : `sudo systemctl restart fail2ban`.

Vérification effective :

```text
Status for the jail: sshd
|- Filter
|  |- Currently failed:  3
|  |- Total failed:      13
|  `- Journal matches:   _SYSTEMD_UNIT=ssh.service
`- Actions
   |- Currently banned:  1
   |- Total banned:      1
   `- Banned IP list:    163.7.5.228
```

### 4.3 Durcissement SSH

Fichier ajouté : `/etc/ssh/sshd_config.d/99-aura-hardening.conf`

```text
# Aura hardening - 2026-11-26
PermitRootLogin no
MaxAuthTries 3
LoginGraceTime 30
```

La directive `Include /etc/ssh/sshd_config.d/*.conf` se trouve en ligne 24 de `/etc/ssh/sshd_config` ; la première valeur gagnant, ce fichier prend bien le pas sur la configuration principale.

Contrôles :

```bash
sudo sshd -t          # → aucune erreur
sudo systemctl reload ssh
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|logingracetime) '
```

Valeurs effectives après rechargement :

```text
logingracetime 30
maxauthtries 3
passwordauthentication yes
permitrootlogin no
pubkeyauthentication yes
```

Tests : connexion par clé réussie ; tentative `root@127.0.0.1` → `Permission denied (publickey,password)`.

### 4.4 Pare-feu hôte

Règles appliquées puis activation :

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 41641/udp
sudo ufw --force enable
```

État final :

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)

To         Action      From
--         ------      ----
22/tcp     ALLOW IN    Anywhere
80/tcp     ALLOW IN    Anywhere
443/tcp    ALLOW IN    Anywhere
41641/udp  ALLOW IN    Anywhere
(identiques en IPv6)
```

Le port `41641/udp` est nécessaire aux connexions directes Tailscale. Les ports internes (8000, 8080, 9000, 9333, 8888…) restent non publiés sur l'hôte, conformément à l'architecture documentée.

---

### 4.5 Intégration comme serveur Coolify

Le serveur Coolify `vmi3782410` (`100.119.132.45`) a été autorisé à piloter le VPS Aura via Tailscale :

- clé Ed25519 dédiée générée sur `vmi3782410` :
  `SHA256:8txqa4K+cb/oJ240LvE0yr5G2BMpnl6q6zRa19o72tc` ;
- cette clé est installée sur le pilote pour l'utilisateur `coolify` (créé à cet effet), avec la restriction
  `from="100.119.132.45"` dans `authorized_keys` ;
- l'utilisateur appartient aux groupes `docker` et `sudo`, avec `NOPASSWD: ALL` via
  `/etc/sudoers.d/coolify` (contrôlé par `visudo -c`) ;
- le serveur a été ajouté dans Coolify via l'API `POST /api/v1/servers` avec
  `proxy_type=none` (aucun conflit avec `aura-001-traefik` sur 80/443), `server_role=both` et validation immédiate ;
- identifiants : clé privée Coolify `rognyvwhmhficqy8lmxtigkl`, serveur `vbtoocyjbkeaqx96rqmb7thc` ;
- empreinte de l'hôte enregistrée manuellement :
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP21NIM6Ld/WzfQP8DlVh5Gx+nrztdnk9j7AyJo8+A9s root@vps3718250.trouble-free.net` ;
- jeton API Coolify dédié `opencode-aura-link`, utilisé uniquement pour cette opération puis révoqué (`1` jeton supprimé) et effacé des fichiers temporaires.

Vérification après validation : `is_reachable=true`, `is_usable=true`, `unreachable_count=0`, Docker `29.9.0` et Compose `5.6.0` détectés. Aucun proxy Coolify n'a été installé localement ; la liste des conteneurs Aura est inchangée.

> Ce lien donne à Coolify un contrôle effectif (équivalent root) sur le pilote. Il doit être traité comme un accès administratif à part entière : clé limitée à une IP, empreinte hôte épinglée, jeton révocable depuis l'interface Coolify.

## 5. Vérification post-intervention

| Contrôle | Résultat |
|---|---|
| `sudo ufw status verbose` | actif, 4 règles d'entrée |
| `ssh aura-admin@127.0.0.1` (clé, `BatchMode`) | `SSH_OK` |
| `ssh root@127.0.0.1` | refusé |
| Ports 22 / 80 / 443 depuis `153.75.248.230` | ouverts |
| Ports 22 / 80 / 443 depuis `100.76.146.65` (Tailscale) | ouverts |
| `fail2ban-client status sshd` | jail actif, journal match corrigé, 1 IP bannie |
| `sshd -t` | valide |
| Coolify `GET /servers/{uuid}` | `is_reachable=true`, `is_usable=true`, proxy `NONE` |
| `docker ps` local | conteneurs Aura inchangés, aucun proxy Coolify ajouté |

---

## 6. Limites et risques résiduels

1. **Authentification par mot de passe conservée.** Décision explicite de l'exploitant. Le brute-force reste possible mais est désormais limité par `MaxAuthTries=3` et fail2ban. Le passage en `PasswordAuthentication no` est différé jusqu'à la fourniture de la clé publique de la machine de travail de l'exploitant.
2. **UFW autorise 22/tcp depuis Internet.** Un durcissement ultérieur peut limiter SSH à `100.64.0.0/10` (Tailscale) et à l'IP fixe connue, à condition de vérifier d'abord l'accès depuis chaque poste utilisé.
3. **Swagger reste exposé publiquement.** 274 requêtes avec réponse 403 ont été observées sur `aura-swagger@docker`. Recommandation : router ce service derrière BasicAuth ou le limiter au tailnet.
4. **Détails des URL d'attaque indisponibles.** Les chemins sont supprimés du journal Traefik (`RequestPath=drop`). Si une analyse forence plus fine est nécessaire, activer temporairement ce champ tout en évitant d'y journaliser des jetons ou des données sensibles.
5. **Mise à jour du noyau en attente.** Le noyau courant est 7.0.0-38 alors que 7.0.0-44 est installé ; un redémarrage est nécessaire. La persistance après reboot reste un gate ouvert du projet.
6. **Sauvegarde indépendante toujours absente** (issue #9). Le dernier backup de 59 Go réside sur le VPS pilote. Le serveur Contabo distant ne dispose que de 86 Go libres : il peut accueillir les petits artefacts (catalogue, audit, scripts), pas l'archive objet complète avec rétention. Aucune modification de la stratégie de sauvegarde n'a été faite dans cet audit.
7. **Aucune rotation de mot de passe effectuée.** Rien n'indique une fuite ; la rotation reste recommandée par précaution si le mot de passe est réutilisé ailleurs.
8. **Nouveau surface d'administration : Coolify.** L'utilisateur `coolify` a un sudo sans mot de passe sur le pilote. Toute compromission de `vmi3782410` donnerait un contrôle équivalent root ici. La restriction `from="100.119.132.45"` et l'épinglage de l'empreinte SSH limitent ce risque, mais ne le suppriment pas.

---

## 7. Prochaines étapes prioritaires

| Priorité | Action | Condition |
|---|---|---|
| P1 | Fournir la clé publique de travail puis passer `PasswordAuthentication no` | Utilisateur |
| P1 | Redémarrer pour charger le noyau 7.0.0-44, puis rejouer les vérifications de persistance | Fenêtre de maintenance |
| P2 | Restreindre `aura-swagger` au tailnet ou derrière BasicAuth | Validation des accès légitimes |
| P2 | Limiter 22/tcp aux sources connues dans UFW | Inventaire des postes d'accès |
| P2 | Mettre en place la copie hors-site (issue #9) et un test de restauration isolé | Destination ≥ 3× le volume de données |
| P3 | Superviser fail2ban et la fraîcheur des backups avec un dead-man switch | — |
| P3 | Mettre à jour `README.md` et `HOST-BOOTSTRAP-CHECKLIST.md` avec ces preuves | Après revue du présent journal |

---

## 8. Commandes de référence

La configuration appliquée est reproductible via `scripts/harden-host.sh` :

```bash
# Sans modification : compare l'état réel à l'état attendu et détecte la dérive
./scripts/harden-host.sh

# Application idempotente (les fichiers ne sont réécrits que s'ils diffèrent)
sudo ./scripts/harden-host.sh --apply

# Passage en clé-seulement, uniquement après un login par clé vérifié dans une autre session
AURA_VERIFIED_KEY_LOGIN=1 sudo ./scripts/harden-host.sh --apply --disable-password-auth
```

Le script conserve une sauvegarde `.bak.<timestamp>` de chaque fichier modifié, valide `sshd -t` avant de recharger SSH, et ne désactive jamais le mot de passe sans la double condition explicite ci-dessus.

Commandes de contrôle ponctuel :

```bash
# État du pare-feu
sudo ufw status verbose

# Jail SSH et IP bannies
sudo fail2ban-client status sshd

# Dernières tentatives SSH
sudo journalctl -u ssh --since '1 hour ago' | grep -E 'Failed password|Invalid user'

# Configuration SSH effective
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|logingracetime) '

# Validation de la configuration avant rechargement
sudo sshd -t && sudo systemctl reload ssh

# Journaux d'accès Traefik
docker logs aura-001-traefik 2>&1 | grep '" 403 ' | awk '{print $1}' | sort | uniq -c | sort -rn | head
```

---

## 9. Sources

- `docs/SECURITY.md`
- `docs/HOST-BOOTSTRAP-CHECKLIST.md`
- `docs/AUDIT-COMPLET-2026-10-24.md`
- `docs/verification-log-2026-11-24-portail-perf.md` (backup local de 59 Go, limite hors-site)
- `docs/BACKUP-RESTORE.md`, `docs/DECISION-BACKUP-DEFERRED.md`
- Journaux système locaux : `auth.log`, `journalctl -u ssh`, `journalctl -u fail2ban`
- Journaux Docker : `aura-001-traefik`
- Journaux applicatifs : `aura-audit.jsonl`
