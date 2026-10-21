# Dossier d'exploitation — AURA Storage (pilote)

> Référence d'exploitation de la branche `feat/api-management`, préparée pour l'issue #11.
> Chaque fait porte une marque de preuve : **VÉRIFIÉ** (lu dans le dépôt sur cette branche),
> **OBSERVÉ** (rapporté avec date/source dans un document du dépôt), **SUPPOSÉ** (hypothèse de
> travail, à confirmer), **BLOQUÉ** (action impossible en l'état), **NON TESTÉ** (jamais exécuté
> contre le VPS réel).
> Ce document ne contient aucun secret : formes et procédures uniquement, jamais de valeurs.

## 1. Périmètre et statut

- **VÉRIFIÉ** — Stack exploitée : Traefik (ports 80/443, ACME HTTP-01) + SeaweedFS
  master / volume / filer-S3 (S3 interne port 8333), réseaux `aura-edge` et
  `aura-storage-internal` (interne) — `docker-compose.yml:1-131`.
- **VÉRIFIÉ** — Non implémenté sur cette branche : l'API de gestion et le catalogue PostgreSQL
  sont spécifiés uniquement (`docs/API-SPECIFICATION.md`, `docs/DATA-MODEL.md`,
  `docs/openapi.yaml`) et ne font pas partie du Compose déployable. Ne pas les présenter
  comme disponibles.
- **OBSERVÉ** — Hôte pilote : InterServer VPS 3718250 (`vps3718250.trouble-free.net`,
  153.75.248.230), 2 CPU, 5,3 Gio RAM, racine 2,9 Tio (~2,8 Tio libres au dernier contrôle),
  Ubuntu 26.04 LTS, noyau 7.0.0-38-generic vérifié live le 2026-10-14 — `docs/SERVER-PROFILE.md`.
- **BLOQUÉ** — Décision Go/No-Go (issue #11) : le statut reste **NO-GO** tant que les portes
  chiffrement, persistance, contrôle d'accès et **restauration indépendante testée** ne sont
  pas démontrées. Un conteneur qui tourne ou un `docker compose config` vert ne vaut pas
  certification de production.

Documents compagnons : `docs/DEPLOYMENT.md` (déploiement initial détaillé),
`docs/OPERATIONS-PLAYBOOK.md` (aide-mémoire), `docs/BACKUP-RESTORE.md` (exigences de
sauvegarde), `docs/SERVER-PROFILE.md` (faits hôte), `docs/verification-log-template.md`
(carnet de preuves à remplir sans secrets).

## 2. Prérequis avant toute opération

1. Session SSH `aura-admin` fonctionnelle + console/secours fournisseur accessible.
   **OBSERVÉ** — `sudo` et élévation OK pour `aura-admin` ; login par clé **NON TESTÉ**,
   second session de validation **en attente** — `docs/SERVER-PROFILE.md §4`, checklist
   d'accès non cochée.
2. Ne jamais fermer la seule session active avant d'avoir testé la nouvelle dans une
   **seconde session** — `docs/operations/SSH-ROOT-ACCESS-INCIDENT-2026-10-14.md §6`.
3. `.env` local présent, permissions `600`, sans placeholder (`scripts/bootstrap.sh`
   refuse `REPLACE_WITH_*`, exige `WEED_S3_SSE_KEK` = 64 caractères hexadécimaux,
   `S3_ACCESS_KEY` ≥ 16 car., `S3_SECRET_KEY` ≥ 32 car.) — **VÉRIFIÉ** (`scripts/bootstrap.sh`).
4. `config/seaweedfs/s3.json` généré localement (`bash ./scripts/generate-config.sh`),
   `600`, ignoré par Git — **VÉRIFIÉ** (`docs/ENVIRONMENT-CONFIGURATION.md`, `.gitignore`
   à confirmer par `git check-ignore .env config/seaweedfs/s3.json`).
5. `docker compose config --quiet` vert **et** revue humaine : seuls 80/443 publiés,
   aucun port SeaweedFS mappé sur l'hôte, règle Traefik = `S3_DOMAIN`, images épinglées
   relues — **VÉRIFIÉ** (procédure `docs/DEPLOYMENT.md §4`).

## 3. Démarrage, arrêt, redémarrage

Démarrage initial (après revue §2) — **VÉRIFIÉ** (`scripts/deploy.sh`, `docs/DEPLOYMENT.md §5`) :

```bash
bash ./scripts/bootstrap.sh
bash ./scripts/deploy.sh
docker compose ps
docker compose logs --tail=150 traefik seaweed-master seaweed-volume seaweed-filer
```

Contrôles post-démarrage : Traefik démarré, certificat valide pour `S3_DOMAIN`,
services SeaweedFS sains, aucun port inattendu public, répertoire données sur le bon
filesystem, survie à un redémarrage contrôlé des conteneurs.

Arrêt / redémarrage contrôlé :

```bash
docker compose ps                       # état avant
docker compose stop                     # arrêt propre (les données persistent via volumes hôte)
docker compose up -d                    # redémarrage
docker compose logs --since=30m traefik seaweed-master seaweed-volume seaweed-filer
```

- **NON TESTÉ** — persistance après recréation des conteneurs et après reboot hôte sur le
  VPS réel (portes d'acceptation `docs/DEPLOYMENT.md §6`, cases non cochées).
- Ne jamais supprimer les répertoires de données ni les volumes Docker comme raccourci de
  dépannage — **VÉRIFIÉ** (`docs/DEPLOYMENT.md §7`, `docs/REPRODUCIBLE-SETUP.md §12`).

## 4. Mise à jour et retour arrière

Mise à jour d'image (Traefik / SeaweedFS) :

1. Lire les notes de version officielles de la release exacte ; vérifier le support de
   `WEED_S3_SSE_KEK`, la syntaxe des policies S3 et les flags — **VÉRIFIÉ**
   (`docs/SECURITY.md`, `docs/ENVIRONMENT-CONFIGURATION.md §SSE-S3`).
2. Noter les tags d'images actuels et la config avant changement
   (`git rev-parse HEAD`, contenu `.env.example` vs `.env` local — sans copier les secrets).
3. Sauvegarder données + métadonnées selon la procédure de cohérence documentée pour la
   release concernée ; ne pas supposer qu'une copie à chaud du répertoire est cohérente —
   **VÉRIFIÉ** (`docs/BACKUP-RESTORE.md`).
4. Tester avec des données représentatives dans un environnement isolé — **VÉRIFIÉ**
   (`docs/OPERATIONS-PLAYBOOK.md §Upgrade and rollback`).
5. Déployer via la procédure revue (`scripts/deploy.sh`), puis exécuter
   `bash tests/sse-s3-smoke-test.sh` (attendu : `ServerSideEncryption=AES256` + SHA-256
   concordant) — **VÉRIFIÉ** (procédure, `docs/DEPLOYMENT.md §SSE-S3`) / **NON TESTÉ**
   (exécution réelle sur cette branche).

Retour arrière :

- **VÉRIFIÉ** — Ne pas supposer la compatibilité descendante des métadonnées de stockage
  (`docs/OPERATIONS-PLAYBOOK.md`). Tout downgrade SeaweedFS sans procédure de la release
  est interdit sans sauvegarde restaurable préalable.
- En cas d'échec TLS post-mise à jour : inspecter DNS, pare-feu, joignabilité du port 80
  et logs ACME Traefik avant tout redémarrage global. En cas d'échec S3 : isoler
  DNS/TLS/routage/auth/santé SeaweedFS/disque avant de tout redémarrer — **VÉRIFIÉ**
  (`docs/DEPLOYMENT.md §7`).
- Garder les originaux locaux jusqu'à restauration indépendante réussie
  (porte critique, `docs/SECURITY.md`, `docs/BACKUP-RESTORE.md`).

### Finding pilote — Traefik ≥ 3.7 requis pour Docker Engine 29

- **VÉRIFIÉ** — La branche `fix/traefik-3.7-docker29` (commit `c578bb7`, **NON FUSIONNÉ**
  dans `feat/api-management` — vérifié par `git merge-base --is-ancestor`) établit que
  Traefik < 3.7 requête l'API Docker 1.24, rejetée par Docker Engine 29+ (minimum 1.40),
  et épingle `traefik:v3.7.14`.
- **VÉRIFIÉ** — Sur cette branche, `.env.example` épingle encore `traefik:v3.4.3`.
  **Ne pas déployer avec Docker Engine 29+ sans appliquer ce correctif** (mettre à jour
  `TRAEFIK_IMAGE` vers une release ≥ 3.7 relue, après lecture des notes de version).
- **BLOQUÉ** — La version réelle de Docker sur le VPS est inconnue (Docker **NON TESTÉ** /
  non installé au dernier état constaté — `docs/SERVER-PROFILE.md §6`). Vérifier
  `docker --version` sur l'hôte avant de figer le tag Traefik.

## 5. Rotation des secrets

Règle générale : jamais de secret dans Git, tickets, journaux ou chat ; `chmod 600` sur
`.env` et `s3.json` ; `git check-ignore` après toute régénération — **VÉRIFIÉ**
(`docs/SECURITY.md`, `docs/ENVIRONMENT-CONFIGURATION.md §Safety`).

### 5.1 Identifiants S3 (`S3_ACCESS_KEY` / `S3_SECRET_KEY`)

1. Générer un nouveau couple (clé d'accès ≥ 16 car. alphanumériques, secret long aléatoire).
2. Mettre à jour le `.env` local, régénérer (`bash ./scripts/generate-config.sh`), valider
   (`docker compose config --quiet`), redéployer, puis mettre à jour **chaque client**
   consommant ces identifiants — **VÉRIFIÉ** (`docs/ENVIRONMENT-CONFIGURATION.md` :
   la rotation exige la mise à jour de la config générée et des clients).
3. L'identité bootstrap est administrative : usage de test contrôlé uniquement ; créer des
   identités least-privilege par application avant usage multi-utilisateur — **VÉRIFIÉ**
   (`docs/SECURITY.md`, `docs/DEPLOYMENT.md §SSE-S3`).

### 5.2 Clé SSE-S3 (`WEED_S3_SSE_KEK`)

> **AVERTISSEMENT — perte = irrécupérable.** La perte de cette clé peut rendre les objets
> chiffrés SSE-S3 **irrécupérables**. Conserver une copie hors-ligne protégée, hors VPS et
> hors dépôt. La rotation est une **migration de données**, pas une simple édition
> d'environnement — **VÉRIFIÉ** (`docs/SECURITY.md`, `AGENTS.md`, `docs/ENVIRONMENT-CONFIGURATION.md`).

1. **SUPPOSÉ à proscrire par défaut** — Ne pas « tourner » la clé sur un jeu de données
   existant sans plan de migration + restauration testé. Les objets écrits sous l'ancienne
   clé deviennent illisibles sans elle.
2. Procédure admise uniquement : provisionner un nouveau jeu (nouvelle clé, nouveau
   chemin/bucket), recopier les objets en clair via une passerelle disposant de l'ancienne
   clé, vérifier hash par hash, basculer les clients, conserver l'ancienne clé scellée
   jusqu'à fin de rétention — synthèse d'exploitation (marques : procédure **SUPPOSÉE**,
   à valider contre la release SeaweedFS exacte avant exécution).
3. Après tout changement : `bash tests/sse-s3-smoke-test.sh` doit rester vert
   (`ServerSideEncryption=AES256`, octets vérifiés) — **VÉRIFIÉ** (exigence),
   **NON TESTÉ** (exécution réelle).

### 5.3 Dashboard Traefik (BasicAuth)

- **VÉRIFIÉ** — Sur cette branche, le dashboard est activé en interne (`--api.dashboard=true`,
  `--api.insecure=false`) **sans routeur public** (`docker-compose.yml:9-10,42` : pas de
  route publique). Ne pas exposer sans authentification + restriction réseau
  (`docs/SECURITY.md`, `config/traefik/README.md`).
- **VÉRIFIÉ** — La branche `feat/traefik-dashboard-auth` (commit `4096a62`,
  **NON FUSIONNÉ** — vérifié par `git merge-base --is-ancestor`) propose un routeur HTTPS
  dédié (`DASHBOARD_DOMAIN`) protégé par BasicAuth bcrypt (`DASHBOARD_AUTH`). Tant qu'il
  n'est pas fusionné et relu, toute exposition du dashboard est interdite.
- Rotation : régénérer le hash bcrypt hors-ligne, mettre à jour `DASHBOARD_AUTH` dans le
  `.env` local, redéployer, vérifier 401 sans identifiants / 200 avec — procédure
  **SUPPOSÉE** (fonctionnalité non présente sur cette branche, commandes à valider lors
  de la fusion).

## 6. Capacité — seuils et conduite

Seuils — **VÉRIFIÉ** (`docs/OPERATIONS.md`) : **enquêter à 70 % d'occupation** du
filesystem, **remédiation planifiée avant 80 %**. Adapter selon croissance et délai
d'expansion ; réserver de la marge pour logs, métadonnées et uploads temporaires.

Repères pilote — **OBSERVÉ** (`docs/SERVER-PROFILE.md`, avant déploiement de la stack) :
racine ~2,9 Tio (~2,8 Tio libres — capacité à réconcilier avec le panneau fournisseur,
avertissement explicite du profil), RAM 5,3 Gio (4,7 Gio disponibles), swap 1 Gio,
`/boot` 974 Mio (643 Mio libres). **SUPPOSÉ** — consommation réelle de la stack
(master/volume/filer + logs + ACME) inconnue tant que le déploiement n'a pas eu lieu ;
à mesurer puis consigner ici.

Conduite sous pression disque — **VÉRIFIÉ** (`docs/OPERATIONS-PLAYBOOK.md §Disk pressure`) :

1. Stopper les imports en masse au seuil d'alerte.
2. Inspection en lecture seule (`df -h`, `df -i`, outils RO).
3. Confirmer sauvegardes indépendantes récentes + voie d'expansion.
4. Ne jamais supprimer manuellement les fichiers de volumes ni les volumes Docker.
5. Reprendre uniquement après contrôles de capacité et d'intégrité.

Surveillance : quota de transfert mensuel fournisseur (**NON TESTÉ** — valeur du plan à
relever dans le panneau avant décision), usage disque/inodes, messages d'émission et de
renouvellement des certificats, fraîcheur des sauvegardes — **VÉRIFIÉ**
(`docs/OPERATIONS-PLAYBOOK.md §Routine operation` ; `docs/OPERATIONS.md`).

## 7. TLS — renouvellement à surveiller

- **VÉRIFIÉ** — ACME Let's Encrypt HTTP-01 via Traefik, état dans le volume nommé
  `traefik-acme` (sauvegarder son état, ne pas le publier — `config/traefik/README.md`).
  Émission exige : DNS correct, port 80 joignable, aucun proxy interceptant le challenge
  (`docs/DEPLOYMENT.md §2`).
- **OBSERVÉ** — DNS pilote `aura-storage.eurinhash.com` rapporté comme résolvant vers le
  VPS le 2026-10-14 (`docs/DEPLOYMENT.md §2`) ; **non re-vérifié dans ce dossier**
  (recontrôler depuis un client externe avant déploiement).
- **NON TESTÉ** — Première émission et tout renouvellement : surveiller les logs Traefik
  (`certificate issuance/renewal messages`) et valider le certificat depuis un client
  externe ; prévoir une alerte d'expiration (risque résiduel §9).

## 8. Ports et exposition — findings pilote

- **VÉRIFIÉ** — Compose : seuls Traefik publie `80:80` et `443:443`
  (`docker-compose.yml:27-29`) ; aucun port SeaweedFS (master/volume/filer-admin/métriques)
  mappé sur l'hôte ; réseau `storage` interne (`docker-compose.yml:123-128`).
- **OBSERVÉ** — SSH sur TCP/22 lors de l'inspection initiale ; politique pare-feu
  **non confirmée** (`docs/SERVER-PROFILE.md §4`). Cible : 22/80/443 seuls, 22 restreint
  aux sources d'administration quand possible, refus par défaut en entrée
  (`docs/HOST-BOOTSTRAP-CHECKLIST.md §Phase 2`).
- **NON TESTÉ** — Vérification depuis un client indépendant que les ports internes
  SeaweedFS ne sont pas joignables publiquement (porte d'acceptation `docs/DEPLOYMENT.md §6`).
- Socket Docker monté en lecture seule : ne retire pas la sensibilité d'accès à l'API
  Docker ; accès hôte/Docker strictement contrôlé, appartenance au groupe `docker` =
  équivalent root, à décider délibérément — **VÉRIFIÉ** (`config/traefik/README.md`,
  `docs/REPRODUCIBLE-SETUP.md`).

## 9. Limites connues et risques résiduels

| # | Risque / limite | Marque | Détail |
|---|---|---|---|
| R1 | Aucune sauvegarde indépendante, aucune restauration testée | **NON TESTÉ** (état dépôt) ; absence de décision contraire vérifiable | Cases non cochées `docs/SERVER-PROFILE.md §6`, portes `docs/BACKUP-RESTORE.md`, `docs/DEPLOYMENT.md §6`. **SUPPOSÉ** (rapporté par le donneur d'ordre, non vérifiable dans le dépôt) : l'absence de backup indépendant relève d'une décision d'opérateur pour le pilote. Un snapshot ou second répertoire sur le même VPS ne constitue pas une sauvegarde indépendante. |
| R2 | Accès SSH non durci : 2e session de validation en attente, clés non confirmées, root/password encore permis | **OBSERVÉ / NON TESTÉ** | `sshd -T` effectif : `permitrootlogin yes`, `passwordauthentication yes` (`docs/operations/SSH-ROOT-ACCESS-INCIDENT-2026-10-14.md §3`) ; checklist `docs/SERVER-PROFILE.md §4` non cochée ; incident du 2026-10-14 clos sur déclaration opérateur, **sans validation technique auditée**. |
| R3 | Renouvellement TLS jamais observé | **NON TESTÉ** | Première émission + renouvellements à surveiller (§7). |
| R4 | Correctif Traefik ≥ 3.7 non fusionné sur cette branche (`.env.example` = v3.4.3) | **VÉRIFIÉ** | Risque d'incompatibilité API Docker 29+ au premier `up` (§4). |
| R5 | Version Docker réelle de l'hôte inconnue | **BLOQUÉ** | Docker non installé au dernier état constaté ; figer les tags après `docker --version` sur l'hôte. |
| R6 | Capacité réelle 2,9 Tio non réconciliée avec le plan fournisseur | **OBSERVÉ** | Avertissement `docs/SERVER-PROFILE.md §2` ; confirmer avant toute décision de capacité. |
| R7 | VPS unique = point unique de défaillance ; S3-compatible ≠ redondance | **VÉRIFIÉ** | `README.md`, `docs/ARCHITECTURE.md`, ADR-002. |
| R8 | Import des PDF/audio originaux interdit jusqu'aux portes | **VÉRIFIÉ** | HTTPS + auth + SSE-S3 (`AES256` + SHA-256 concordant) + persistance + restauration indépendante (`docs/SECURITY.md`, `AGENTS.md`). Originaux conservés localement jusque-là. |
| R9 | Dashboard : toute exposition actuelle serait sans protection | **VÉRIFIÉ** | Pas de routeur public sur cette branche (§5.3) ; la variante BasicAuth est sur branche séparée non fusionnée. |

## 10. Points non vérifiables restants (à compléter par l'opérateur)

1. Décision d'opérateur sur l'absence de backup indépendant : ni son contenu ni sa date ne
   figurent dans le dépôt — joindre la référence (ticket, message, procès-verbal) ou
   infirmer l'hypothèse R1. (**SUPPOSÉ**)
2. Résolution exacte de l'incident SSH du 2026-10-14 et preuve de connexion finale.
   (**OBSERVÉ** comme « déclaré », non audité)
3. Versions Docker/Compose réellement installées sur l'hôte. (**BLOQUÉ**)
4. Émission/renouvellement TLS, smoke tests S3/SSE-S3, persistance, injoignabilité des
   ports internes, quota de transfert. (**NON TESTÉ**)
5. Réconciliation allocation disque 2,9 Tio avec le panneau InterServer. (**OBSERVÉ**,
   à confirmer)

Consigner chaque preuve datée (sans secrets) dans `docs/verification-log-template.md`
avant de demander le passage à GO.

## 11. Balayage de réconciliation automatique (#144)

Le balayage de réconciliation (expiration des intents périmés, fin des purges
interrompues) ne dépend plus d'un appel humain : il tourne dans un thread
démon du processus API, comme le vérificateur et le scrubber.

| Réglage | Défaut | Rôle |
|---|---|---|
| `AURA_RECONCILE_ENABLED` | `1` | `0` désactive le balayage automatique (la route admin reste). |
| `AURA_RECONCILE_INTERVAL_SECONDS` | `300` | Période entre deux balayages (refus au boot si < 30). |
| `AURA_RECONCILE_LIMIT` | `500` | Nombre maximal d'intents traités par passage. |
| `AURA_RECONCILE_EXTRA_GRACE_SECONDS` | `3600` | Marge ajoutée à la durée de vie d'un intent : le balayage automatique n'expire un intent **que** bien après sa fenêtre de grâce, pour qu'un upload lent en cours ne perde pas ses octets. |

Points d'exploitation :

- Le balayage est **borné** et **jamais optimiste** : un octet non supprimé du
  stockage laisse l'intent `pending` et compte dans `storage_failures` ; le
  passage suivant réessaie. Aucun état « expiré » n'est posé sur une suppression
  échouée.
- Le balayage automatique est **global** (tous les espaces), comme la route
  `POST /api/v1/admin/reconcile` : il n'est pas borné à un espace.
- **Contrôle** : `GET /api/v1/admin/health` expose
  `components.reconcile.last_sweep` (date, compteurs, durée) — la preuve que le
  balayage tourne sans lire les journaux.
- Une panne du stockage n'arrête pas la boucle : l'échec est journalisé et le
  passage suivant réessaie.

