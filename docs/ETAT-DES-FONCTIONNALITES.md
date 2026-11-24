# État des fonctionnalités — AURA Storage

> **Date :** 2026-11-05, **révision :** 2026-11-24 (voir §10) · **Périmètre :** dépôt `main`, API FastAPI, frontend React, infrastructure Docker Compose.
> **Méthode :** lecture du code et des routes, exécution des suites de tests, vérification statique de la configuration. Aucun test sur le VPS réel n'a été exécuté pour ce document.
> **But :** distinguer clairement ce qui est **spécifié**, **implémenté** et **validé**, afin d'éviter de compter une spec comme une fonctionnalité livrée.

---

## 1. Synthèse

| Indicateur | Valeur vérifiée |
|---|---|
| Routes HTTP backend | **97** (`api/main.py`) |
| Tests backend | **444 passés, 2 skipés** (parité PostgreSQL sans `AURA_TEST_PG_DSN`) |
| Tests unitaires frontend | **47 passés** (6 fichiers) |
| Specs e2e Playwright | **41** (API mockée, pas de stockage réel) |
| Écrans frontend | **11** routes |
| Services Docker | **9** |
| Ports publiés sur l'hôte | **80/443 uniquement** (Traefik) |

**Verdict :** la plateforme est fonctionnelle de bout en bout. Les fonctions de stockage, transfert, partage, administration et sécurité applicative sont implémentées et testées hors ligne. Le pilote n'est **pas encore accepté pour des données de production** : la validation réelle backup/restore, la persistance après reboot et les preuves d'exploitation sur le VPS restent à produire.

---

## 2. Fonctionnalités backend

### 2.1 Authentification et autorisation

| Fonction | État | Détail |
|---|---|---|
| Session humaine | Implémenté | Cookie opaque `aura_session`, CSRF sur les routes mutantes, expiration fixe au login |
| Identités machine | Implémenté | Bearer `aura_<id>_<secret>`, scopes par capacité, rotation et révocation |
| Rôles et capacités | Implémenté | `user` / `operator` / `admin`, default-deny, scopes `objects:*` et `admin:*` |
| Mode maître | Implémenté | Élévation par mot de passe, 15 min, requise pour les purges groupées |
| Rate limiting | Implémenté | Login par IP et appels M2M par IP |
| Sessions / TTL | Implémenté | `AURA_SESSION_TTL` (défaut 8 h), surchargeable par `.env` |

### 2.2 Objets et catalogue

| Fonction | État | Détail |
|---|---|---|
| Upload en trois temps | Implémenté | `upload-intents` → PUT présigné → `commit`, avec `abort` et cache d'idempotence |
| Validation des transferts | Implémenté | Types autorisés, tailles, fichiers vides, quotas, garde de capacité |
| Liste et recherche | Implémenté | Pagination, filtres dossier/statut/type/taille/dates/tag, `q` et `search` |
| Métadonnées et analytics | Implémenté | Fiche objet, vues, téléchargements, partages, egress |
| Suppression et corbeille | Implémenté | Soft-delete, restauration, purge unitaire, purge groupée, vidage de corbeille |
| Déplacement et tags | Implémenté | Déplacement entre dossiers, tags normalisés (max 20) |
| Intégrité | Implémenté | SHA-256 au commit, détection de divergence, statut `suspect`, re-vérification admin |
| Chiffrement au repos | Implémenté | SSE-S3 AES256 exigé et vérifié au commit ; CLI de ré-encription |
| Antivirus | Implémenté (optionnel) | Hook `AURA_AV_SCAN_CMD` : CLEAN / INFECTED / TIMEOUT |
| Multipart | Implémenté, **désactivé par défaut** | `AURA_MULTIPART_ENABLED=0` ; reprise des parties, abandon, TTL |
| Révisions de contenu | **Partiel** | Schéma DB + repository seulement, **aucune route API** (`tests/test_revisions.py`) |
| Import jobs | **Partiel** | Création/liste/annulation ; **aucun worker** ne traite les jobs (`api/main.py:4321`) |

### 2.3 Partage, publication et médias

| Fonction | État | Détail |
|---|---|---|
| Liens publics objet | Implémenté | `/s/{token}`, durée, nombre d'usages, révocation, `attachment` forcé |
| Liens publics dossier | Implémenté | `/f/{token}`, sous-arborescence, page publique |
| URL stable publiée | Implémenté | `/m/{slug}`, remplacement de contenu sans casser l'URL |
| Packs / collections | Implémenté | CRUD, ordre des items, publication, manifest `/p/{slug}.json` |
| Aperçu inline | Implémenté | `preview-intent`, allow-list stricte de types non actifs |
| Miniatures | Implémenté | `/thumbnail`, génération et redirection |
| HLS et sous-titres | Implémenté | Packaging ffmpeg, playlist, segments, WebVTT |
| Téléchargement | Implémenté | `download-intent`, URL présignée courte, `Content-Disposition: attachment` |
| Portail public (sous-domaine) | Implémenté (tests hors-ligne) | Connexion Google OAuth + PKCE, rôle `public` sans capacité objet, catalogue HTML et lecteur `<audio>` ; voir `PUBLIC-PORTAL.md` |

### 2.4 Dossiers

| Fonction | État | Détail |
|---|---|---|
| CRUD dossiers | Implémenté | Création, renommage, déplacement, suppression si vide |
| Arborescence | Implémenté | Liste racine / par parent / complète (`all=true`), protection anti-cycle |
| Taille des dossiers | Implémenté | `size_bytes` calculé côté API |
| Partage de dossier | Implémenté | Création, liste, révocation, accès public |

### 2.5 Administration et exploitation

| Fonction | État | Détail |
|---|---|---|
| Applications / espaces / buckets | Implémenté | CRUD, bucket par défaut, isolation par `space_id` |
| Quotas | Implémenté | Stockage et egress mensuels, réservations par propriétaire |
| Identités et sites partenaires | Implémenté | Création, rotation, révocation, métadonnées partenaire |
| Réconciliation | Implémenté | Normale, terminale, inverse ; worker périodique |
| Intégrité / scrub | Implémenté | Rapport, scrub à la demande, worker périodique, re-vérification |
| Orphelins stockage | Implémenté | Détection clés orphelines et multipart périmé, nettoyage destructif encadré |
| Audit | Implémenté | Journal JSONL, recherche filtrée, rétention et purge |
| Supervision | Implémenté | Stats, usage réel, santé API/DB/stockage/disque, erreurs récentes |
| Diagnostic réseau | Implémenté | `ping`, `download`, `upload` authentifiés |

---

## 3. Fonctionnalités frontend

| Écran / fonction | État | Détail |
|---|---|---|
| Fichiers (`/`) | Implémenté | Liste, grille, filtres, tri, breadcrumb, sélection, upload, partage, corbeille |
| Transferts (`/transfers`) | Implémenté | File, progression, débit/ETA, pause/reprise/annulation, filtres URL, CSV, virtualisation |
| Tableau de bord (`/dashboard`) | Implémenté | Usage, compteurs, egress ; capacités détaillées réservées aux administrateurs |
| Partages (`/shares`) | Implémenté | Liens objet/dossier, états actif/expiré/épuisé/révoqué, révocation |
| Corbeille (`/trash`) | Implémenté | Restauration, purge, vidage encadré par le mode maître |
| Paramètres (`/settings`) | Implémenté | Thème sombre/clair, compte, déconnexion |
| Aide (`/help`) | Implémenté | Aide contextuelle import/partage/sécurité |
| Onboarding (`/onboarding`) | Implémenté | Affiché au premier login, état local |
| Diagnostic (`/diagnostic`) | Implémenté | RTT, débit descendant/remontant, historique local |
| Administration (`/admin`) | Implémenté | Espaces, quotas, identités, partenaires, intégrité, orphelins |
| Connexion (`/login`) | Implémenté | Session, erreurs, rate-limit |
| Upload simple/multipart | Implémenté | Décision côté API, reprise après reload, journal local, retry |
| Aperçu | Implémenté | Image, PDF, audio, vidéo ; 415 sinon |
| ZIP de dossier | Implémenté | Génération côté client |
| Raccourcis / a11y | Implémenté | `/`, `Suppr`, tooltips, aria-labels, régions live, focus |

> Les tests e2e couvrent ces parcours avec une **API mockée**. Ils ne prouvent pas l'intégration réelle avec S3/PostgreSQL.

---

## 4. Sécurité et intégrité

| Sujet | État |
|---|---|
| Autorisation default-deny | Implémenté et testé route par route (`tests/test_security_isolation.py`, `tests/test_m06_isolation_matrix.py`) |
| Isolation par espace | Implémenté côté API |
| Identité S3 de l'API | **Corrigé le 2026-11-05** : identité `aura-api` dédiée obligatoire (`Read`/`Write`/`List`), aucun repli sur l'identité bootstrap `Admin` |
| Session | **Corrigé** : TTL par défaut 8 h, surchargeable |
| Téléchargement | **Corrigé** : `download-intent` force `attachment`, les types actifs ne sont jamais rendus inline |
| Frontend en production | **Corrigé le 2026-11-05** : publication en répertoire de release immuable hors arbre de travail, rollback par lien `current` |
| Secrets | `.env`, `config/seaweedfs/s3.json`, clés et données ignorés par Git |
| Audit | Journal append-only avec rétention |
| Chiffrement | SSE-S3 AES256, clé `WEED_S3_SSE_KEK` hors ligne |

---

## 5. Qualité et preuves

| Preuve | Résultat |
|---|---|
| `python -m pytest tests -q` | **444 passés, 2 skip** (parité PostgreSQL, `AURA_TEST_PG_DSN` absent) |
| `npm run test:unit` | 47 tests verts |
| `npm run build` | Build TypeScript + Vite vert |
| `docker compose config --quiet` | Valide avec les variables requises |
| `bash -n` sur les scripts | Valide |
| CI | 3 workflows : validation offline, web/e2e, déploiement manuel |
| E2E réel sur le VPS | **Non exécuté** |
| Restore réel | **Non exécuté** |
| Parité PostgreSQL | **Non exécutée** (tests skipés) |
| Redémarrage de l'hôte | **Non exécuté** |

---

## 6. Spécifié mais non implémenté, ou différé

| Élément | État réel |
|---|---|
| FTPS (ISSUE-018) | **Spécification seule** — aucun code |
| Intégration OpenBooks (ISSUE-019) | **Spécification seule** — aucun code |
| Intégration Axiom (ISSUE-020) | **Spécification seule** — aucun code |
| Révisions de contenu | Schéma + repository, pas d'API |
| Import jobs | API de réservation, pas de traitement |
| Multipart en production | Code présent, flag OFF, gate SeaweedFS non close |
| Better Auth / Google OAuth | Différé (décision documentée) |
| Sauvegarde indépendante | Scripts présents, restore réel non validé |
| Fonctionnalités de transfert avancées | Reportées (décision documentée) |

---

## 7. Gates restants avant production

| Gate | État | Action |
|---|---|---|
| Backup/restore indépendant | **Bloquant** | Choisir la destination, exécuter une sauvegarde et un restore isolé, vérifier l'intégrité |
| Persistance après reboot | Non vérifié | Exécuter la procédure sur le VPS |
| E2E réel sur le VPS | Non exécuté | Démarrer API + front réels et jouer les parcours critiques |
| Parité PostgreSQL | Non exécutée | Définir `AURA_TEST_PG_DSN` et lancer la suite |
| Multipart SeaweedFS 4.48 | Bloqué | Lever les deux UNKNOWN (récupération disque après abort, completion 10 000 parties) |
| Compression / cache des assets | Ouvert | `gzip`/brotli et `Cache-Control` sur les assets hashés |
| CSP du bootstrap de thème | Ouvert | Sortir le script inline ou ajouter son hash |
| Routes inconnues | Ouvert | `/robots.txt`, `/sitemap.xml` renvoient la SPA en 200 |
| Durcissement conteneurs / logs | Partiel | Redaction des query strings, HSTS dashboard, socket-proxy |

---

## 8. Journal des remédiations d'audit

| Constat (audit 2026-10-24) | Statut 2026-11-05 |
|---|---|
| S1 — API avec identité S3 `Admin` | **Corrigé dans le code** : identité dédiée obligatoire, bootstrap génère les clés, CI mise à jour. À confirmer au prochain déploiement. |
| S2 — session de 90 jours | **Corrigé** : `AURA_SESSION_TTL` surchargeable, défaut 8 h. |
| A1 — `download-intent` inline | **Corrigé** : `Content-Disposition: attachment` forcé, test dédié. |
| D1 — `./web/dist` servi en production | **Corrigé dans le code** : release immuable sous `${AURA_RELEASES_DIR}`, montage via `AURA_WEB_DIST_DIR`, rollback documenté. À confirmer au prochain déploiement. |

> Ce tableau remplace les statuts périmés de `docs/ISSUES-AUDIT-2026-11.md`. Ce dernier contient encore des statuts contradictoires (issues détaillées « Ouvert » alors que la synthèse annonce « tout résolu ») et ne doit plus servir de source unique.

---

## 9. Maintenance de ce document

- Mettre à jour la date et le tableau de synthèse à chaque lot livré.
- Ne jamais marquer une fonctionnalité « validée » sans une preuve exécutée (test réel, log daté ou vérification sur le VPS).
- Distinguer systématiquement : **spécifié** / **implémenté** / **validé**.
- Les sources de vérité restent le code, `docs/openapi.yaml` et les logs de vérification datés.

---

## 10. Révision du 2026-11-24

Preuves détaillées : [journal de vérification](verification-log-2026-11-24-portail-perf.md) et [roadmap portail](PUBLIC-PORTAL-ROADMAP.md).

### 10.1 Chiffres actualisés

| Indicateur | Valeur au 2026-11-24 |
|---|---|
| Tests backend | **661 passés, 39 skippés** |
| Tests unitaires frontend | **75 passés** |
| Migration de catalogue | **`0027_perf_indexes`** appliquée sur le pilote |
| CI | `Quality` et `Validate storage configuration` au vert |
| Issues roadmap #293-#306 | **14/14 fermées** |

### 10.2 Nouveautés implémentées et validées

- **Transfert** : nettoyage des sessions multipart à l'expiration, CAS avant suppression dans le sweep, scrubber qui masque les objets corrompus, compteurs de débit partagés en base, grants média `/a/<token>` révocables, timeout de PUT basé sur l'inactivité, polling de vérification borné, deadlines des appels de contrôle.
- **Portail public** : lecteur accessible (dialogs natifs, VTT, `aria-valuetext`, focus trap), catalogue paginé (60 titres), recommandations réutilisant le scoring audiobook avec raisons affichées, playlists privées, statistiques auditeur, récap de série sans spoiler, recherche en langage naturel limitée aux motifs français courants.
- **Infrastructure** : HTTP/3 et `responseHeaderTimeout=120s` sur Traefik, volumeSeaweedFS 10 Gio, vacuum nocturne automatisé, index composites `objects(space_id, application_id, folder_id)` et `objects(status, intent_expires_at)`, garde-fou de capacité à 1 Tio (valeur d'endiguement).
- **Médias** : `Range` validé en réel (`206`, `Accept-Ranges: bytes`, sans `Content-Encoding`) ; pas de `buffering` sur la route S3 ; `Cache-Control: immutable` volontairement **non** appliqué aux URL mutables `/m/` et `/a/`.

### 10.3 État des gardes

| Gate | État |
|---|---|
| Capacité de stockage réelle (panneau InterServer) | **Ouvert** — valeur d'endiguement 1 Tio en place, issue #314 |
| Déploiement complet de la roadmap sur le pilote | **Partiel** — API/migrations et config rechargées ; rebuild global suivi par #315 |
| Backup local + vérification | **En cours** — script corrigé (`38f762e`), archive en cours de génération |
| Copie hors-site, restore isolé, reboot, E2E réel | **Ouverts** — issues #5, #9, #10, #11, #23 |
| Preuves multipart (reclaim après abort, 10 000 parties) | **Ouvertes** — issues #316, #317 ; plafond opérationnel 5 000 parties en mitigation |
| Tests audiobook PostgreSQL | **Ouvert** — issue #318 |
| Pool de connexions PostgreSQL | **Ouvert** — issue #325 |

### 10.4 Documents périmés

`docs/STRUCTURED_MAP.md`, `docs/API-ROUTES-AUDIT.md` et `docs/ISSUES-AUDIT-2026-11.md` datent de l'audit d'octobre et contiennent des chiffres et statuts contradictoires. Ils sont conservés à titre historique et **ne doivent pas être utilisés comme source de vérité** ; le suivi de leur réconciliation est l'issue #324.
