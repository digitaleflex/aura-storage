# AURA — Catalogue fonctionnel

**Statut :** inventaire vérifié ligne à ligne dans le code à la date du 2026-10-16
(branche de travail `feat/vault-ui-polish`), sur `api/main.py`, `api/authz.py`,
`api/identity.py`, `api/s3.py`, `api/lifecycle.py`, `api/transfer.py`,
`api/object_query.py`, `api/config.py`, puis recoupé avec `docs/AUTHORIZATION-MATRIX.md`,
`docs/API-SPECIFICATION.md` et `docs/openapi.yaml`.

Ce document distingue strictement deux états :

- **Implémenté** — présent dans le code, couvert par les tests hors-ligne de `tests/`.
  Implémenté ne veut **pas** dire validé sur le pilote : aucun essai de bout en bout
  n'a eu lieu sur le VPS réel (voir `AGENTS.md`).
- **Spécifié seulement** — décrit dans une spécification mais **absent** du code.

Les écarts constatés entre documentation et code sont listés en fin de document
(§Écarts doc-vs-code). Le document contractuel de référence pour les routes reste
`docs/AUTHORIZATION-MATRIX.md` ; le contrat machine reste `docs/openapi.yaml`.

## 1. Authentification et autorisation

### Deux types de principaux (implémenté)

| Principal | Authentification | CSRF | Capacités effectives |
|---|---|---|---|
| **user** (humain) | cookie `aura_session` (HttpOnly, `SameSite=Strict`, `Secure` si `AURA_COOKIE_SECURE=1`) | requis sur les méthodes non sûres | rôle → capacités (table ci-dessous) |
| **service** (machine) | `Authorization: Bearer aura_<id>_<secret>` — **unique** canal | non applicable | scopes explicites stockés sur l'identité |

- L'alias d'authentification machine `X-AURA-Key` a été **retiré** (M06) : seul le
  Bearer est accepté (`api/authz.py:_bearer_token`). Un service n'accepte jamais un
  cookie de session, et un humain n'est jamais authentifié par Bearer.
- Le jeton machine est `aura_<uuid>_<64 hex>` ; seul `sha256(secret)` est stocké,
  comparaison en temps constant ; jeton inconnu / révoqué / expiré → 401
  (`api/identity.py`). Le jeton en clair n'est renvoyé **qu'une fois** (création ou
  rotation) et jamais journalisé.
- L'utilisateur admin bootstrap (`AURA_API_ADMIN_USER`, défaut `admin`) est créé ou
  promu au démarrage avec le mot de passe haché (`_ensure_bootstrap_admin`).

### Rôles humains (default-deny, implémenté)

| Capacité | `user` | `operator` | `admin` |
|---|:--:|:--:|:--:|
| `objects:read` | ✅ | ✅ | ✅ |
| `objects:write` | ✅ | ✅ | ✅ |
| `objects:delete` | ✅ | ✅ | ✅ |
| `objects:purge` | ❌ | ✅ | ✅ |
| `admin:read` | ❌ | ✅ | ✅ |
| `admin:write` | ❌ | ❌ | ✅ |

### Scopes machine (implémenté)

Une identité machine ne peut détenir que des capacités **data-plane** :
`objects:read`, `objects:write`, `objects:delete`, `objects:purge`. Toute demande
d'un scope `admin:*` est refusée avec **422** à la création, et un scope admin
présent sur une ligne stockée n'est jamais *effectif* (défense en profondeur,
`api/authz.py:effective_scopes`). Provisioning, rotation et révocation passent
par la session humaine `operator`/`admin`.

### Limites anti-force-brute (implémenté)

- Login humain : échecs comptés par IP cliente, défaut 10 / 60 s
  (`AURA_LOGIN_RATE_LIMIT` / `AURA_LOGIN_RATE_WINDOW`) ; un succès remet le
  compteur à zéro. 429 avec `Retry-After`.
- Authentification machine : échecs par IP cliente, défaut 60 / 60 s
  (`AURA_M2M_RATE_LIMIT` / `AURA_M2M_RATE_WINDOW`). 429 avec `Retry-After`.
- L'IP cliente vient de `X-Forwarded-For` **seulement** si le pair immédiat est un
  proxy de confiance (`AURA_TRUSTED_PROXIES`, défaut loopback + RFC1918) ; l'entrée
  non fiable la plus à droite gagne (`api/netinfo.py`).

## 2. Plan de contrôle — objets (implémenté)

Le cycle de vie d'un objet suit l'état catalogue : `pending` → (`verifying` →) (`available` |
`failed` | `expired` | `aborted`), puis `deleted` (soft) et enfin purge (row supprimée).
Les octets ne traversent jamais l'API : le client upload/télécharge directement vers
S3 via des URLs présignées de courte durée (`api/s3.py`).

| Route | Capacité | Comportement |
|---|---|---|
| `POST /api/v1/objects/upload-intents` | `objects:write` | Politique serveur (type MIME, plafond de taille, règle vide) ; clé d'objet générée serveur ; bucket imposé par l'espace ; `Idempotency-Key` optionnel ; URL PUT présignée liant `Content-Length` signé ; refuse un espace `disabled` (403) |
| `POST /api/v1/objects/{oid}/commit` | `objects:write` | Vérifie la taille réelle, calcule SHA-256 en streaming, passe `available` ; **idempotent** ; 410 si intention expirée, 413 si trop gros, 422 si absent/tronqué. **202 `verifying`** dès `AURA_VERIFY_ASYNC_THRESHOLD_BYTES` (32 Mio) ou si le délai `AURA_COMMIT_DEADLINE_S` est dépassé : un vérificateur finit le contrôle (le fichier n'est pas téléchargeable avant `available`) ; antivirus optionnel (`AURA_AV_SCAN_CMD`) ; 504 si l'antivirus dépasse son délai (l'objet reste `pending`) |
| `POST /api/v1/objects/{oid}/abort` | `objects:write` | Annule une intention `pending` (suppression best-effort des octets partiels) ; idempotent ; refuse 409 un objet `available`/`deleted` |
| `GET /api/v1/objects` | `objects:read` | Liste paginée et filtrable : `folder_id` (`root` = non classé), `q` (sous-chaîne du nom affiché), `status`, `content_type`, `min_size`/`max_size`, `created_after`/`created_before`, `sort`/`order`. Les `deleted` sont masqués sauf `status=deleted` explicite |
| `GET /api/v1/objects/{oid}` | `objects:read` | Métadonnées seules ; 404 hors périmètre |
| `PATCH /api/v1/objects/{oid}` | `objects:write` | **humain uniquement** : classe/déclasse l'objet dans un dossier logique possédé (`folder_id`, `null` = racine) |
| `POST /api/v1/objects/{oid}/download-intent` | `objects:read` | URL GET présignée + nom, type, taille, checksum ; 409 si non `available` |
| `POST /api/v1/objects/{oid}/preview-intent` | `objects:read` | URL GET présignée `Content-Disposition: inline` pour l'aperçu intégré ; **liste blanche** : images (PNG, JPEG, GIF, WebP, AVIF), PDF, audio, vidéo (MP4, WebM, OGG) et texte (brut, CSV, TSV, Markdown, JSON) ; 415 pour tout le reste (HTML, SVG, XML, Office…) → téléchargement seul ; 409 si non `available` |
| `DELETE /api/v1/objects/{oid}` | `objects:delete` | Soft delete (`deleted`) ; 409 si non supprimable |
| `POST /api/v1/objects/{oid}/purge` | `objects:purge` | Destructif (operator/admin) : supprime les octets **puis** la ligne. Un échec de suppression S3 conserve la ligne et renvoie **502** (M06) |

Points de conception vérifiés :

- **Clé d'objet** : toujours générée serveur `aura/<space>/<actor>/<uuid>` ; les
  champs clients `object_key` / `owner_id` / `space_id` sont rejetés (422).
- **Bucket** : jamais choisi librement ; l'espace possède une liste blanche. Sans
  bucket explicite, le bucket **par défaut** de l'espace est utilisé ; un espace sans
  défaut est refusé avec 409 (pas de repli silencieux).
- **Taille signée** : `size_bytes` déclarée est liée à l'URL présignée comme
  `Content-Length` signé, ce qui empêche d'uploader plus que l'API n'a autorisé ; un
  dépassement au commit reste refusé (413) en défense en profondeur (#40).
- **Idempotence upload** : un rejeu avec la même `Idempotency-Key` et le même acteur
  renvoie la même intention (`idempotent_replay=true`) avec une URL re-signée, sans
  créer de seconde ligne. Clé opaque, jamais journalisée.
- **Politique de contenu** : type MIME normalisé et validé (RFC 6838), allow-list
  optionnelle `AURA_ALLOWED_CONTENT_TYPES` (exact ou `type/*`), objets vides refusés
  par défaut (`AURA_ALLOW_EMPTY_OBJECTS`).
- **Flux de commit sans mémoire** : `stream_sha256` hache par blocs et coupe tôt
  au-delà du plafond (`api/s3.py`), jamais l'objet entier en mémoire.

## 3. Dossiers logiques (implémenté, #61)

Entités **logiques** du catalogue, pas de répertoires hôte. Possédées par un
**utilisateur humain** (`folders.owner_id → users.id`, NOT NULL), donc toutes les
routes exigent un principal humain ; une identité service ne gère pas de dossiers.

| Route | Capacité | Comportement |
|---|---|---|
| `GET /api/v1/folders` | `objects:read` | Racine, `?parent_id=`, ou `?all=true` (arbre plat, `all` + `parent_id` = 422) |
| `GET /api/v1/folders/{fid}` | `objects:read` | 404 hors de l'arbre du propriétaire |
| `POST /api/v1/folders` | `objects:write` | Nom plat (pas de `/`, `\`, contrôle), unique par propriétaire+parent, profondeur ≤ 32 |
| `PATCH /api/v1/folders/{fid}` | `objects:write` | Renomme/déplace ; refus du cycle et du dépassement de profondeur (409) |
| `DELETE /api/v1/folders/{fid}` | `objects:delete` | 409 si enfants ou objets **vivants** ; les objets soft-deleted sont ignorés et détachés avant suppression (la ligne survit jusqu'au purge) |

Tous les accès filtrent par `owner_id` du demandeur : un dossier d'autrui est un
**404**, jamais un 403 (pas de fuite d'existence).

## 4. Registre administratif (implémenté, M04)

Applications, espaces et buckets ont un **cycle de vie doux** : on renomme /
active-désactive, on ne supprime jamais via l'API.

| Route | Capacité | Comportement |
|---|---|---|
| `POST`/`GET /api/v1/admin/applications` | `admin:write` / `admin:read` | Nom unique ; entité racine du tenant |
| `GET`/`PATCH /api/v1/admin/applications/{aid}` | `admin:read` / `admin:write` | Détail + `space_count` ; renommage et/ou `active`/`disabled` |
| `POST`/`GET /api/v1/admin/spaces` | `admin:write` / `admin:read` | Un espace exige une application **active** ; bucket par défaut dérivé (`aura-<name>-<env>`) ou fourni, validé selon les règles S3, globalement unique |
| `GET`/`PATCH /api/v1/admin/spaces/{sid}` | `admin:read` / `admin:write` | Détail + buckets + compteurs ; `application_id` **immuable** |
| `POST /api/v1/admin/spaces/{sid}/buckets` | `admin:write` | Enregistre un bucket additionnel (non défaut), nom S3 validé |
| `GET /api/v1/admin/buckets` | `admin:read` | Tous les buckets avec leur rattachement espace/application ; jamais de credential S3 |
| `PATCH /api/v1/admin/buckets/{bid}` | `admin:write` | Bascule le flag défaut (un seul défaut par espace) |
| `POST`/`GET /api/v1/admin/identities` | `admin:write` / `admin:read` | Identités M2M ; refusées pour un espace `disabled` |
| `POST /api/v1/admin/identities/{iid}/rotate` | `admin:write` | Nouveau jeton renvoyé une fois ; l'ancien secret cesse immédiatement |
| `POST /api/v1/admin/identities/{iid}/revoke` | `admin:write` | Révocation immédiate |

Règles vérifiées : désactiver un espace refuse les nouveaux uploads (403) et les
nouvelles identités (409) tout en gardant les objets lisibles ; un espace ne peut pas
changer d'application ; un bucket n'est jamais supprimé et aucun payload de bucket ne
contient de credential.

## 5. Observabilité et supervision (implémenté, M07)

Détail complet dans `docs/OBSERVABILITY.md`.

| Route | Capacité | Contenu |
|---|---|---|
| `GET /api/v1/admin/audit` | `admin:read` | Recherche du journal d'audit (append-only JSON-lines) du plus récent au plus ancien ; filtres période/acteur/action/résultat/espace/application/request_id ; `limit` borné 1..500, `offset` ; `truncated` signale un historique plus ancien |
| `POST /api/v1/admin/audit/prune` | `admin:write` | Applique `AURA_AUDIT_RETENTION_DAYS` (défaut 90) ; les lignes sans horodatage valide sont **conservées** |
| `GET /api/v1/admin/usage` | `admin:read` | Consommation réelle par espace (octets **available** vérifiés, compteurs, plafonds configurés) + `measured_at` |
| `GET /api/v1/admin/health` | `admin:read` | Instantané api/database/storage/disk + erreurs récentes ; toujours 200, `degraded` au niveau supérieur si une dépendance tombe |
| `GET /api/v1/admin/orphans` | `admin:read` | Candidats orphelins (lignes `available` absentes du stockage) — **lecture seule**, rien n'est supprimé sur ce signal |
| `POST /api/v1/admin/reconcile` | `admin:write` | Balayage borné des intentions périmées ; un échec S3 garde l'intention `pending` (compté dans `storage_failures`, jamais comme nettoyé) |
| `GET /api/v1/admin/stats` | `admin:read` | Compteurs agrégés (statuts/applications/espaces/identités) |

Toute réponse porte `X-Request-Id`. Les journaux ne contiennent jamais mots de passe,
secrets, jetons session/CSRF ni URLs (même présignées).

## 6. Santé, persistance, données et sauvegarde

- **Santé** : `GET /health/live` (public, liveness) et `GET /health/ready` (public,
  `503` si S3 injoignable, sans détail backend) — implémenté.
- **Persistance catalogue** : double backend, SQLite (dev/test) et PostgreSQL (pilote),
  derrière la même interface `repo` (`api/db.py`, `api/db_pg.py`), avec migrations
  additives (`api/migrations.py`). La parité SQLite/PostgreSQL est couverte par
  `tests/test_repository_parity.py` et `tests/test_pg_parity.py` (le second exige
  `AURA_TEST_PG_DSN`). Le backend par défaut est SQLite (`AURA_API_BACKEND`).
- **Plan de données S3** : SeaweedFS derrière Traefik : seul un bucket S3-compatible
  est exposé ; les octets ne transitent pas par l'API. Détail edge : `docs/GESTION-APIS.md`.
- **SSE-S3 (chiffrement côté objet)** : appliqué par la **passerelle SeaweedFS**, pas
  par l'API (l'API ne fait que présigner des URL). `WEED_S3_SSE_KEK` (clé d'enveloppe
  de 64 caractères hex) est passée au conteneur filer/S3. Voir avertissements §7.
- **Sauvegarde/restauration** : procédure documentée (`docs/BACKUP-RESTORE.md`), pas
  de script tant que le mécanisme de cohérence SeaweedFS n'est pas confirmé. La
  restauration indépendante réussie est un **gate** avant tout import d'originaux.

## 7. Avertissements et gates à préserver

- **Clé SSE-S3 (`WEED_S3_SSE_KEK`)** : 64 caractères hex (`openssl rand -hex 32`).
  Conserver une copie hors-ligne séparée du VPS et du dépôt. **La perte de cette clé
  peut rendre les objets SSE-S3 irrécupérables** ; sa rotation est une procédure de
  migration de données, pas une simple édition d'environnement. Ne jamais commiter,
  journaliser ou imprimer la clé. Lancer `tests/sse-s3-smoke-test.sh` après
  déploiement ; ne pas importer de données de valeur tant qu'il n'est pas vert.
- **Pas d'import d'originaux** (PDF/audio) avant que HTTPS, l'authentification,
  SSE-S3 (`ServerSideEncryption=AES256` + SHA-256 correspondant), la persistance et un
  **test de restauration de sauvegarde indépendant** soient tous validés.
- **URLs présignées et journaux** : elles portent des credentials en query string ;
  ne jamais les journaliser (l'API le garantit ; vérifier la redaction des access logs
  du bord — `config/traefik/README.md`).
- **Secrets** : jamais dans Git (`.env`, `config/seaweedfs/s3.json`, clés, certificats).

## 8. Spécifié seulement (NON implémenté)

| Élément | Source | État |
|---|---|---|
| Intégration **OpenBooks** (catalogue/droits) | `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-DIAGRAM.md`, `docs/DECISIONS.md` | futur, non implémenté |
| Intégration **Axiom** (supervision/opérations via API versionnée) | idem | futur, non implémenté ; ne doit jamais conditionner l'accès normal aux données |
| **Import jobs** (`POST/GET /api/v1/import-jobs`, `…/cancel`) | `docs/API-SPECIFICATION.md` | propositions, routes absentes |
| **Adapter FTPS** (migration/legacy) | `docs/API-SPECIFICATION.md`, `docs/FILE-TRANSFER.md` | optionnel futur, isolé |
| **Multipart upload** | `docs/MULTIPART-UPLOAD-PLAN.md` | planifié ; aujourd'hui upload en une requête, plafonné à 5 GiB (`AURA_MAX_OBJECT_BYTES`) |
| Champs `visibility`, `deletedAt`, nommage camelCase (`name`, `contentType`, `sizeBytes`) | `docs/API-SPECIFICATION.md` §Core resources | proposés ; l'API implémentée expose `display_name`/`content_type`/`size_bytes` et **pas** `visibility`/`deletedAt` |
| Recherche plein texte | `docs/API-SPECIFICATION.md` | proposée ; seul `q` (sous-chaîne du nom affiché) est implémenté |

## 9. Écarts doc-vs-code constatés

Ces écarts sont **signalés** ; aucun code hors `docs/` n'a été modifié.

1. **Statut `aborted` non filtrable (écart réel, code).** `abort_object` écrit bien
   `status="aborted"`, et les tests hors-ligne l'affirment
   (`tests/test_transfer_engine.py`). Mais `aborted` est **absent** de :
   - `ObjectStatus` dans `api/main.py` (Literal `pending|available|deleted|expired|failed`) ;
   - `OBJECT_STATUSES` dans `api/object_query.py` ;
   - l'énumération `status` de `docs/openapi.yaml` ;
   - la matrice `docs/AUTHORIZATION-MATRIX.md`.
   Conséquence : un appel `GET /api/v1/objects?status=aborted` renvoie **422**, alors
   que l'UI web propose ce filtre (`web/src/pages/ObjectsPage.tsx`) et que le listing
   par défaut **retourne** des lignes `aborted` (seuls les `deleted` sont masqués). Le
   contrat OpenAPI est cohérent avec le comportement réel de l'API (qui rejette ce
   filtre) ; c'est donc l'**UI/le vocabulaire d'états** qui diverge du contrat. À
   corriger côté code (`ObjectStatus` + `OBJECT_STATUSES` + openapi + matrice) ou
   côté UI, décision à trancher.
2. **Constante `verifying` inutilisée.** `api/transfer.py` définit `VERIFYING =
   "verifying"` mais aucune transition ne l'écrit (le commit passe directement
   `pending` → `available`). Constante morte, absente des énumérations.
3. **Ligne de matrice malformée (corrigée).** Dans
   `docs/AUTHORIZATION-MATRIX.md`, la ligne `/admin/audit/prune` était tronquée et le
   texte de rétention (« default 90 ; timestamp-less lines kept ») débordait sur la
   ligne `/admin/orphans`. Corrigé dans ce lot (docs uniquement).
4. **Champs de ressource divergents.** `docs/API-SPECIFICATION.md` (§Core resources)
   liste `visibility`, `deletedAt` et un nommage camelCase que l'API implémentée
   n'expose pas (§8 ci-dessus). C'est une spec-proposal, laissée telle quelle.
5. **Aucune divergence de routes.** `docs/openapi.yaml` et `api/main.py` ont un
   ensemble de chemins/méthodes identique, vérifié par
   `tests/test_openapi_contract.py`. Les énumérations d'états ne sont **pas** couvertes
   par ce test (d'où l'écart #1 non détecté).

## 10. Tests hors-ligne pertinents

`pytest tests/` couvre : `test_security_isolation.py`, `test_m06_isolation_matrix.py`,
`test_admin_management.py`, `test_transfer_engine.py`, `test_commit_streaming.py`,
`test_folders.py`, `test_folders_list_all.py`, `test_objects_move.py`,
`test_objects_search_filter.py`, `test_objects_folder_filter.py`,
`test_s3_bucket_names.py`, `test_upload_default_bucket.py`, `test_m07_observability.py`,
`test_openapi_contract.py`, `test_repository_parity.py`, `test_ids.py`,
`test_client_ip.py`, `test_migrations.py`, `test_db_concurrency.py`,
`test_pg_parity.py` (exige `AURA_TEST_PG_DSN`).

Non exécutables hors-ligne (raison) : `tests/s3-smoke-test.sh`,
`tests/sse-s3-smoke-test.sh`, `tests/test-s3-smoke-validation.sh` (exigent un endpoint
S3 réel et AWS CLI), `tests/test-landing-routing.sh` (routage Traefik réel).

## Références

- Matrice d'autorisation : `docs/AUTHORIZATION-MATRIX.md`
- Contrat machine : `docs/openapi.yaml`
- Transfert : `docs/FILE-TRANSFER.md`, `docs/TRANSFER-ENGINE.md`
- Observabilité : `docs/OBSERVABILITY.md`
- Sécurité / SSE-S3 : `docs/SECURITY.md`
- Sauvegarde : `docs/BACKUP-RESTORE.md`
- Gestion des APIs (edge) : `docs/GESTION-APIS.md`
