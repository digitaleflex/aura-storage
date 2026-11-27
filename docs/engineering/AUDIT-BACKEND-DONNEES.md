# Audit structurel de l'API — données (généré)

> Généré par `python3 scripts/audit_backend.py`. Ne pas modifier à la main : relancer le script.
> Commit analysé : `f6c94f1`.

## 1. Chiffres de `api/main.py`

| Mesure | Valeur |
|---|---:|
| Lignes | 6619 |
| Taille (octets) | 284943 |
| Routes HTTP | 152 |
| Modèles Pydantic | 35 (328 lignes) |
| Fonctions de premier niveau hors routes | 115 (1474 lignes) |
| Lignes des fonctions de route | 3727 |
| Autres classes | 0 |
| Gestionnaires (on_event, middleware, exception) | 8 |
| Routes (méthode, chemin) dupliquées | 0 |
| Routes `/api/v1` absentes d'`openapi.yaml` | 0 |
| Routes hors `/api/v1` (hors contrat OpenAPI) | 51 |

## 2. Routes par domaine (classement par chemin)

| Domaine | Routes | Lignes de routes | Modèles utilisés | Helpers privés (lignes) | Helpers partagés | États globaux touchés | Complexité max |
|---|---:|---:|---:|---:|---:|---:|---:|
| portail public | 38 | 572 | 4 | 28 (274) | 5 | 1 | 21 |
| administration | 37 | 738 | 12 | 7 (101) | 12 | 0 | 16 |
| objets (catalogue, médias, corbeille) | 24 | 589 | 7 | 5 (63) | 19 | 0 | 22 |
| import et révisions | 10 | 233 | 2 | 3 (31) | 2 | 0 | 15 |
| dossiers | 8 | 224 | 3 | 4 (39) | 2 | 0 | 22 |
| partages (objets et dossiers) | 7 | 353 | 1 | 4 (60) | 8 | 0 | 15 |
| transferts | 7 | 608 | 2 | 9 (270) | 11 | 2 | 48 |
| médias publics (/m /d /a /hls /covers) | 7 | 211 | 0 | 1 (28) | 7 | 0 | 9 |
| collections | 6 | 72 | 3 | 2 (15) | 2 | 0 | 11 |
| santé et diagnostic | 5 | 58 | 0 | 1 (7) | 0 | 2 | 5 |
| authentification console | 3 | 69 | 1 | 0 (0) | 4 | 0 | 6 |

*Helpers privés* : fonctions de `main.py` appelées (directement ou non) par les routes d'un seul domaine : elles peuvent partir avec lui. *Helpers partagés* : appelées depuis plusieurs domaines : elles doivent d'abord trouver un propriétaire commun.

## 3. États globaux et effets de bord

### Variables mutables de module

| Variable | Ligne | Construction |
|---|---:|---|
| `_RESP_CACHE` | 105 | `{}` |
| `_RESP_CACHE_LOCK` | 110 | `threading.Lock()` |
| `_QUOTA` | 113 | `{}` |
| `_QUOTA_LOCK` | 115 | `threading.Lock()` |
| `_LOGIN_ATTEMPTS` | 357 | `{}` |
| `_PUBLIC_LOGIN_ATTEMPTS` | 360 | `{}` |
| `_PUBLIC_RATE_LIMITS` | 440 | `{'media': 120, 'cover': 600, 'progress': 120, 'preview': 30,` |
| `_READY_CACHE` | 1123 | `{'at': 0.0, 'ready': False}` |
| `_READY_LOCK` | 1125 | `threading.Lock()` |
| `_THUMBNAIL_LOCKS` | 4380 | `{}` |
| `_THUMBNAIL_LOCKS_LOCK` | 4381 | `threading.Lock()` |

Instructions `global` : aucune.

### Threads, tâches et gestionnaires

- `@app.on_event('startup')` → `_start_media_worker` (ligne 231)
- `@app.on_event('startup')` → `_enforce_session_ttl` (ligne 236)
- `@app.on_event('startup')` → `_warn_on_unbounded_multipart` (ligne 255)
- `@app.on_event('startup')` → `_warn_on_process_local_rate_limits` (ligne 272)
- `@app.on_event('startup')` → `_start_verifier` (ligne 286)
- `@app.middleware('http')` → `security_headers` (ligne 307)
- `@app.middleware('http')` → `request_context` (ligne 334)
- `@app.exception_handler(StarletteHTTPException)` → `_portal_html_not_found` (ligne 1963)

### Imports différés dans `main.py` (souvent des casse-cycles)

- `from .auth import hash_password` ×2
- `from .lifecycle import PurgeBlockedError, StorageDeleteError` ×2
- `from .transfer import NON_COMPRESSIBLE_TYPES` ×2
- `from .verifier import start_background` ×1
- `from .scrubber import start_background as start_scrubber` ×1
- `from .reconciler import start_background as start_reconciler` ×1
- `from .import_worker import start_background as start_import_worker` ×1
- `from . import portal_search` ×1
- `from . import portal_recommendations` ×1
- `from .lifecycle import resume_purges` ×1
- `from .scrubber import scrub_run` ×1
- `from .storage_reconcile import scan_bucket, scan_multipart` ×1
- `from .storage_reconcile import remove_orphans` ×1
- `from .reconciler import last_sweep` ×1

## 4. Graphe d'imports entre modules de `api/`

| Module | Lignes | Importe (au chargement) | Importe (différé) | Importé par |
|---|---:|---|---|---|
| `audit` | 287 | — | config | main |
| `auth` | 59 | — | — | db, db_pg, main |
| `authz` | 302 | config, identity, netinfo, store | audit | main |
| `avscan` | 54 | — | — | main, verifier |
| `config` | 363 | — | — | authz, cover_enrichment, google_oauth, main, media_worker, netinfo, reencrypt, store |
| `cover_enrichment` | 286 | config, s3, store | — | — |
| `db` | 2329 | auth, dblock, ids, migrations, object_query, transfer | — | — |
| `db_pg` | 2032 | auth, dblock, ids, migrations, object_query, transfer | — | — |
| `dblock` | 38 | — | — | db, db_pg |
| `folder_shares` | 277 | — | — | main |
| `google_oauth` | 128 | config | — | main |
| `identity` | 69 | ids | — | authz, main |
| `ids` | 53 | — | — | db, db_pg, identity, main, media_worker, migrations |
| `import_worker` | 156 | — | — | — |
| `lifecycle` | 475 | s3, transfer | config | main, reconciler |
| `magic_link` | 67 | — | — | main |
| `main` | 6619 | audit, auth, authz, avscan, config, folder_shares, google_oauth, identity, ids, lifecycle, magic_link, media_worker, netinfo, public_book, public_ui, s3, shares, store, transfer | auth, import_worker, lifecycle, portal_recommendations, portal_search, reconciler, scrubber, storage_reconcile, transfer, verifier | — |
| `media_worker` | 110 | config, ids, s3, store | — | main |
| `migrations` | 813 | ids | — | db, db_pg |
| `netinfo` | 105 | config | — | authz, main |
| `object_query` | 189 | — | — | db, db_pg |
| `portal_recommendations` | 90 | public_ui | — | — |
| `portal_search` | 120 | — | — | — |
| `public_book` | 253 | public_ui | — | main |
| `public_ui` | 833 | — | — | main, portal_recommendations, public_book |
| `reconciler` | 132 | lifecycle | lifecycle | — |
| `reencrypt` | 75 | config, s3 | — | — |
| `s3` | 298 | — | — | cover_enrichment, lifecycle, main, media_worker, reencrypt, scrubber, verifier |
| `scrubber` | 131 | s3, transfer, verifier | — | — |
| `shares` | 97 | — | — | main |
| `storage_reconcile` | 165 | — | — | — |
| `store` | 15 | config | db, db_pg | authz, cover_enrichment, main, media_worker |
| `transfer` | 177 | — | — | db, db_pg, lifecycle, main, scrubber |
| `verifier` | 210 | avscan, s3 | audit, config, lifecycle, s3, store | scrubber |

Cycles d'imports au chargement : **0**.

## 5. Modules existants réutilisables

| Fichier | Lignes | Rôle (docstring) |
|---|---:|---|
| `audit.py` | 287 | Append-only JSON-lines audit log (#22 hardening, M07 observability). |
| `auth.py` | 59 | Password hashing (argon2) and opaque session tokens (server-side store). |
| `authz.py` | 302 | Server-side authentication and authorization (#35, #36, #38). |
| `avscan.py` | 54 | Optional antivirus hook (D4), shared by the synchronous commit and the |
| `config.py` | 363 | Environment-driven settings. No secrets are hard-coded; all secrets come from env. |
| `cover_enrichment.py` | 286 | Cover enrichment helpers for published audiobooks. |
| `db.py` | 2329 | SQLite catalogue behind a small Repository interface (#18; PostgreSQL in #19). |
| `db_pg.py` | 2032 | PostgreSQL catalogue implementing the same Repository interface as db.py (#19). |
| `dblock.py` | 38 | Serialize catalogue access on the single shared connection. |
| `folder_shares.py` | 277 | Public folder share links: subtree helpers and the HTML listing page. |
| `google_oauth.py` | 128 | Minimal Google OAuth 2.0 support for the public portal. |
| `identity.py` | 69 | Machine-to-machine service identities (#38). |
| `ids.py` | 53 | Canonical identifiers: every AURA id is a UUID v4 in canonical text form. |
| `import_worker.py` | 156 | Background worker for bulk import jobs (Lot 3). |
| `lifecycle.py` | 475 | Lifecycle: reconcile stale pending uploads, soft-delete, purge (#19 follow-up). |
| `magic_link.py` | 67 | E-mail sign-in link ("magic link") helpers for the public portal. |
| `main.py` | 6619 | AURA Management API (#18; authz #35/#36, M2M #38, streaming commit #37). |
| `media_worker.py` | 110 | Bounded in-process HLS worker. |
| `migrations.py` | 813 | Additive schema migrations shared by the SQLite (dev/test) and PostgreSQL |
| `netinfo.py` | 105 | Client-address resolution behind the trusted proxy chain (#35/#38). |
| `object_query.py` | 189 | Shared filter/sort grammar for the object catalogue list (M02). |
| `portal_recommendations.py` | 90 | Bridge the public portal's shelves to the audiobook scoring engine. |
| `portal_search.py` | 120 | Interprétation locale d'une recherche en langage naturel pour le portail. |
| `public_book.py` | 253 | HTML of the browsable (signed-out) part of the public portal. |
| `public_ui.py` | 833 | HTML for the public portal. |
| `reconciler.py` | 132 | Automatic reconciliation sweep (#144). |
| `reencrypt.py` | 75 | Re-encrypt objects stored before uploads requested SSE-S3. |
| `s3.py` | 298 | S3 data-plane access. Keys stay server-side; browsers only get presigned URLs. |
| `scrubber.py` | 131 | Periodic integrity scrub: re-hash stored objects to catch silent corruption. |
| `shares.py` | 97 | Public object share links. |
| `storage_reconcile.py` | 165 | Storage ↔ catalogue reconciliation: bytes the catalogue does not account for. |
| `store.py` | 15 | Single catalogue repository instance shared by the API and the auth layer. |
| `transfer.py` | 177 | Transfer policy: content-type allow-list, size/empty rules, status vocabulary. |
| `verifier.py` | 210 | Asynchronous integrity verification (N5). |

## 6. Couplage des tests avec `api.main`

Noms lus ou modifiés par les tests sous la forme `main.<nom>` ou `from api.main import <nom>`. Déplacer un nom hors de `main` casse ces tests tant qu'ils ne sont pas adaptés ou qu'un alias est conservé.

- Noms distincts : **29** (privés `_x` : 11, publics : 18), dans **49** fichiers de test.

| Nom | Utilisations | Fichiers |
|---|---:|---:|
| `repo` | 348 | 43 |
| `app` | 205 | 46 |
| `settings` | 189 | 22 |
| `reset_login_attempts` | 79 | 40 |
| `is_previewable` | 8 | 1 |
| `s3ops` | 7 | 3 |
| `public_ui` | 6 | 1 |
| `_PUBLIC_RATE_LIMITS` | 5 | 2 |
| `time` | 3 | 2 |
| `_cache_key` | 3 | 1 |
| `s3` | 2 | 1 |
| `DIAG_DEFAULT_DOWNLOAD` | 2 | 1 |
| `DIAG_MAX_BYTES` | 2 | 1 |
| `audit_path` | 2 | 2 |
| `py` | 2 | 2 |
| `__file__` | 2 | 2 |
| `_QUOTA` | 2 | 1 |
| `_RESP_CACHE` | 2 | 1 |
| `MAX_FOLDER_DEPTH` | 1 | 1 |
| `_usage_period` | 1 | 1 |
| `ObjectStatus` | 1 | 1 |
| `public_book` | 1 | 1 |
| `_portal_csp` | 1 | 1 |
| `_charge_quota` | 1 | 1 |
| `HTTPException` | 1 | 1 |

## 7. Fonctions les plus longues et les plus complexes

| Fonction | Ligne | Lignes | Complexité | Type |
|---|---:|---:|---:|---|
| `commit_object` | 3516 | 264 | 48 | route POST /api/v1/objects/{oid}/commit |
| `upload_intent` | 2794 | 226 | 40 | route POST /api/v1/objects/upload-intents |
| `_finalize_replacement_commit` | 3375 | 137 | 52 | helper |
| `create_replace_intent` | 3023 | 119 | 22 | route POST /api/v1/objects/{oid}/replace-intents |
| `redeem_share` | 1234 | 85 | 12 | route GET /s/{token} |
| `restore_object_revision` | 6541 | 79 | 15 | route POST /api/v1/objects/{oid}/revisions/{rid}/restore |
| `admin_health` | 5793 | 73 | 7 | route GET /api/v1/admin/health |
| `admin_usage` | 5720 | 70 | 7 | route GET /api/v1/admin/usage |
| `public_portal` | 2440 | 68 | 17 | route GET / |
| `redeem_folder_share_object` | 1447 | 67 | 15 | route GET /f/{token}/o/{oid} |
| `create_object_share` | 4110 | 64 | 8 | route POST /api/v1/objects/{oid}/share |
| `public_auth_callback` | 1650 | 59 | 19 | route GET /api/public/auth/callback |
| `view_folder_share` | 1388 | 56 | 10 | route GET /f/{token} |
| `update_folder` | 5205 | 52 | 22 | route PATCH /api/v1/folders/{fid} |
| `create_folder_share` | 5287 | 52 | 6 | route POST /api/v1/folders/{fid}/share |

| Fonction | Ligne | Complexité | Lignes |
|---|---:|---:|---:|
| `_finalize_replacement_commit` | 3375 | 52 | 137 |
| `commit_object` | 3516 | 48 | 264 |
| `upload_intent` | 2794 | 40 | 226 |
| `create_replace_intent` | 3023 | 22 | 119 |
| `update_folder` | 5205 | 22 | 52 |
| `public_book_page` | 2579 | 21 | 42 |
| `_public_listening_stats` | 2313 | 21 | 45 |
| `public_auth_callback` | 1650 | 19 | 59 |
| `_filter_collections` | 2148 | 18 | 23 |
| `public_portal` | 2440 | 17 | 68 |
| `update_space` | 5974 | 16 | 36 |
| `redeem_folder_share_object` | 1447 | 15 | 67 |
| `update_partner_site` | 6230 | 15 | 36 |
| `restore_object_revision` | 6541 | 15 | 79 |
| `public_email_link_confirm` | 1819 | 13 | 35 |

Fonctions de plus de 80 lignes : **5** sur 267.

## 8. Inventaire des routes

| Méthode | Chemin | Fonction | Ligne | Lignes | Domaine | Règle d'accès (Depends) |
|---|---|---|---:|---:|---|---|
| GET | `/health/live` | `live` | 1116 | 2 | santé et diagnostic | `**aucune dépendance déclarée**` |
| GET | `/health/ready` | `ready` | 1129 | 13 | santé et diagnostic | `**aucune dépendance déclarée**` |
| GET | `/api/v1/diag/ping` | `diag_ping` | 1158 | 6 | santé et diagnostic | `Depends(authorize(None))` |
| GET | `/api/v1/diag/download` | `diag_download` | 1176 | 15 | santé et diagnostic | `Depends(authorize(None))` |
| POST | `/api/v1/diag/upload` | `diag_upload` | 1194 | 22 | santé et diagnostic | `Depends(authorize(None))` |
| GET | `/s/{token}` | `redeem_share` | 1234 | 85 | partages (objets et dossiers) | `**aucune dépendance déclarée**` |
| GET | `/f/{token}` | `view_folder_share` | 1388 | 56 | partages (objets et dossiers) | `**aucune dépendance déclarée**` |
| GET | `/f/{token}/o/{oid}` | `redeem_folder_share_object` | 1447 | 67 | partages (objets et dossiers) | `**aucune dépendance déclarée**` |
| POST | `/api/v1/login` | `login` | 1517 | 26 | authentification console | `**aucune dépendance déclarée**` |
| POST | `/api/v1/logout` | `logout` | 1546 | 9 | authentification console | `Depends(authorize(human=True))` |
| GET | `/api/v1/me` | `me` | 1558 | 34 | authentification console | `Depends(authorize())` |
| GET | `/api/public/auth/google` | `public_auth_google` | 1625 | 22 | portail public | `**aucune dépendance déclarée**` |
| GET | `/api/public/auth/callback` | `public_auth_callback` | 1650 | 59 | portail public | `**aucune dépendance déclarée**` |
| POST | `/api/public/auth/email` | `public_email_link_request` | 1771 | 30 | portail public | `**aucune dépendance déclarée**` |
| GET | `/connexion/lien` | `public_email_link_open` | 1804 | 12 | portail public | `**aucune dépendance déclarée**` |
| POST | `/api/public/auth/email/confirm` | `public_email_link_confirm` | 1819 | 35 | portail public | `**aucune dépendance déclarée**` |
| GET | `/api/public/me` | `public_me` | 1867 | 21 | portail public | `Depends(require_public)` |
| PATCH | `/api/public/me` | `public_me_patch` | 1891 | 5 | portail public | `Depends(require_public)` |
| DELETE | `/api/public/me` | `public_me_delete` | 1899 | 10 | portail public | `Depends(require_public)` |
| POST | `/api/public/logout` | `public_logout` | 1912 | 9 | portail public | `Depends(require_public)` |
| GET | `/sw.js` | `portal_service_worker` | 1978 | 11 | portail public | `**aucune dépendance déclarée**` |
| GET | `/hors-ligne` | `portal_offline_page` | 1992 | 12 | portail public | `**aucune dépendance déclarée**` |
| GET | `/portal-assets/{name}` | `portal_asset` | 2007 | 15 | portail public | `**aucune dépendance déclarée**` |
| GET | `/profil` | `public_profile` | 2025 | 16 | portail public | `**aucune dépendance déclarée**` |
| POST | `/profil` | `public_profile_update` | 2044 | 13 | portail public | `Depends(require_public)` |
| POST | `/profil/supprimer` | `public_profile_delete` | 2060 | 12 | portail public | `Depends(require_public)` |
| GET | `/api/public/library` | `public_library` | 2183 | 6 | portail public | `Depends(require_public)` |
| POST | `/api/public/progress` | `public_progress` | 2192 | 16 | portail public | `Depends(require_public)` |
| GET | `/api/public/progress` | `public_progress_get` | 2223 | 5 | portail public | `Depends(require_public)` |
| GET | `/api/public/bookmarks` | `public_bookmarks` | 2231 | 3 | portail public | `Depends(require_public)` |
| POST | `/api/public/bookmarks` | `public_bookmark_add` | 2237 | 11 | portail public | `Depends(require_public)` |
| DELETE | `/api/public/bookmarks/{bookmark_id}` | `public_bookmark_delete` | 2251 | 8 | portail public | `Depends(require_public)` |
| PUT | `/api/public/favorites/{oid}` | `public_favorite_add` | 2273 | 3 | portail public | `Depends(require_public)` |
| DELETE | `/api/public/favorites/{oid}` | `public_favorite_remove` | 2279 | 2 | portail public | `Depends(require_public)` |
| POST | `/api/public/playlists/create` | `public_playlist_create_form` | 2292 | 9 | portail public | `Depends(require_public)` |
| POST | `/api/public/playlists/{pid}/delete` | `public_playlist_delete_form` | 2304 | 7 | portail public | `Depends(require_public)` |
| GET | `/api/public/stats` | `public_stats` | 2361 | 3 | portail public | `Depends(require_public)` |
| GET | `/api/public/playlists` | `public_playlists` | 2367 | 3 | portail public | `Depends(require_public)` |
| POST | `/api/public/playlists` | `public_playlist_create` | 2373 | 8 | portail public | `Depends(require_public)` |
| PATCH | `/api/public/playlists/{pid}` | `public_playlist_rename` | 2384 | 11 | portail public | `Depends(require_public)` |
| DELETE | `/api/public/playlists/{pid}` | `public_playlist_delete` | 2398 | 8 | portail public | `Depends(require_public)` |
| GET | `/api/public/playlists/{pid}/items` | `public_playlist_items` | 2409 | 3 | portail public | `Depends(require_public)` |
| PUT | `/api/public/playlists/{pid}/items/{oid}` | `public_playlist_add_item` | 2415 | 10 | portail public | `Depends(require_public)` |
| DELETE | `/api/public/playlists/{pid}/items/{oid}` | `public_playlist_remove_item` | 2428 | 9 | portail public | `Depends(require_public)` |
| GET | `/` | `public_portal` | 2440 | 68 | portail public | `**aucune dépendance déclarée**` |
| GET | `/livre/{oid}` | `public_book_page` | 2579 | 42 | portail public | `**aucune dépendance déclarée**` |
| GET | `/extrait/{oid}` | `public_preview` | 2624 | 29 | portail public | `**aucune dépendance déclarée**` |
| GET | `/robots.txt` | `public_robots` | 2656 | 11 | portail public | `**aucune dépendance déclarée**` |
| GET | `/sitemap.xml` | `public_sitemap` | 2670 | 15 | portail public | `**aucune dépendance déclarée**` |
| POST | `/api/v1/me/master-mode` | `master_mode_on` | 2699 | 20 | administration | `Depends(authorize(OBJECTS_PURGE, human=True))` |
| DELETE | `/api/v1/me/master-mode` | `master_mode_off` | 2722 | 4 | administration | `Depends(authorize(human=True))` |
| POST | `/api/v1/objects/bulk-purge` | `bulk_purge` | 2762 | 6 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_PURGE, human=True))` |
| POST | `/api/v1/objects/trash/empty` | `empty_trash` | 2771 | 14 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_PURGE, human=True))` |
| POST | `/api/v1/objects/upload-intents` | `upload_intent` | 2794 | 226 | transferts | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/replace-intents` | `create_replace_intent` | 3023 | 119 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE))` |
| GET | `/api/v1/objects/{oid}/multipart` | `multipart_status` | 3292 | 10 | transferts | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/multipart/parts` | `multipart_part_urls` | 3305 | 22 | transferts | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/commit` | `commit_object` | 3516 | 264 | transferts | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/abort` | `abort_object` | 3783 | 37 | transferts | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/public-access` | `create_public_access` | 3833 | 26 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE))` |
| DELETE | `/api/v1/objects/{oid}/public-access` | `revoke_public_access` | 3862 | 13 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE))` |
| GET | `/api/v1/objects` | `list_objects` | 3892 | 46 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/tags` | `list_object_tags` | 3941 | 13 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}` | `get_object` | 3957 | 6 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/transfers` | `list_transfers` | 3966 | 41 | transferts | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/transfers/{tid}` | `get_transfer` | 4010 | 8 | transferts | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/analytics` | `object_analytics` | 4021 | 24 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| DELETE | `/api/v1/objects/{oid}` | `soft_delete_object` | 4048 | 14 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_DELETE))` |
| POST | `/api/v1/objects/{oid}/restore` | `restore_object` | 4065 | 16 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_DELETE))` |
| PATCH | `/api/v1/objects/{oid}` | `update_object` | 4084 | 23 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| POST | `/api/v1/objects/{oid}/share` | `create_object_share` | 4110 | 64 | partages (objets et dossiers) | `Depends(authorize(OBJECTS_READ, human=True))` |
| GET | `/api/v1/objects/{oid}/shares` | `list_object_shares` | 4177 | 28 | partages (objets et dossiers) | `Depends(authorize(OBJECTS_READ))` |
| DELETE | `/api/v1/objects/{oid}/shares/{sid}` | `revoke_object_share` | 4208 | 31 | partages (objets et dossiers) | `Depends(authorize(OBJECTS_READ, human=True))` |
| POST | `/api/v1/objects/{oid}/purge` | `purge` | 4242 | 18 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_PURGE))` |
| POST | `/api/v1/objects/{oid}/download-intent` | `download_intent` | 4263 | 32 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| POST | `/api/v1/objects/{oid}/preview-intent` | `preview_intent` | 4339 | 35 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/thumbnail` | `object_thumbnail` | 4471 | 29 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| PUT | `/api/v1/objects/{oid}/publication` | `set_object_publication` | 4503 | 28 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| POST | `/api/v1/objects/{oid}/replace` | `replace_object_content` | 4534 | 48 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/m/{slug}` | `public_media` | 4615 | 36 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| GET | `/d/{slug}` | `public_download` | 4654 | 42 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| GET | `/a/{token}` | `public_granted_media` | 4699 | 43 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| GET | `/covers/{oid}.jpg` | `public_cover` | 4745 | 26 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| POST | `/api/v1/objects/{oid}/hls` | `prepare_hls` | 4796 | 14 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/api/v1/objects/{oid}/hls/status` | `hls_status` | 4813 | 11 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/hls/index.m3u8` | `hls_playlist` | 4827 | 8 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/hls/{segment}` | `hls_segment` | 4838 | 12 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_READ))` |
| PUT | `/api/v1/objects/{oid}/subtitle` | `set_subtitle` | 4853 | 20 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/hls/{slug}.m3u8` | `public_hls_playlist` | 4876 | 17 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| GET | `/hls/{slug}/{segment}` | `public_hls_segment` | 4896 | 21 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| GET | `/m/{slug}/subtitles.vtt` | `public_subtitle` | 4920 | 26 | médias publics (/m /d /a /hls /covers) | `**aucune dépendance déclarée**` |
| PUT | `/api/v1/objects/{oid}/tags` | `set_object_tags` | 4971 | 14 | objets (catalogue, médias, corbeille) | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/api/v1/collections` | `list_collections` | 4988 | 3 | collections | `Depends(authorize(OBJECTS_READ, human=True))` |
| POST | `/api/v1/collections` | `create_collection` | 4994 | 14 | collections | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/api/v1/collections/{cid}` | `get_collection` | 5011 | 7 | collections | `Depends(authorize(OBJECTS_READ, human=True))` |
| PATCH | `/api/v1/collections/{cid}` | `update_collection` | 5021 | 24 | collections | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| PUT | `/api/v1/collections/{cid}/items` | `set_collection_items` | 5048 | 18 | collections | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| DELETE | `/api/v1/collections/{cid}` | `delete_collection` | 5069 | 6 | collections | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| GET | `/p/{slug}.json` | `public_collection_manifest` | 5078 | 22 | partages (objets et dossiers) | `**aucune dépendance déclarée**` |
| GET | `/api/v1/folders` | `list_folders` | 5144 | 31 | dossiers | `Depends(authorize(OBJECTS_READ, human=True))` |
| GET | `/api/v1/folders/{fid}` | `get_folder` | 5178 | 9 | dossiers | `Depends(authorize(OBJECTS_READ, human=True))` |
| POST | `/api/v1/folders` | `create_folder` | 5190 | 12 | dossiers | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| PATCH | `/api/v1/folders/{fid}` | `update_folder` | 5205 | 52 | dossiers | `Depends(authorize(OBJECTS_WRITE, human=True))` |
| DELETE | `/api/v1/folders/{fid}` | `delete_folder` | 5260 | 19 | dossiers | `Depends(authorize(OBJECTS_DELETE, human=True))` |
| POST | `/api/v1/folders/{fid}/share` | `create_folder_share` | 5287 | 52 | dossiers | `Depends(authorize(OBJECTS_READ, human=True))` |
| GET | `/api/v1/folders/{fid}/shares` | `list_folder_shares` | 5342 | 26 | dossiers | `Depends(authorize(OBJECTS_READ, human=True))` |
| DELETE | `/api/v1/folders/{fid}/shares/{sid}` | `revoke_folder_share` | 5371 | 23 | dossiers | `Depends(authorize(OBJECTS_READ, human=True))` |
| POST | `/api/v1/admin/reconcile` | `reconcile` | 5400 | 26 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/reconcile-terminal` | `reconcile_terminal_route` | 5429 | 6 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/reconcile-reverse` | `reconcile_reverse_route` | 5438 | 5 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/integrity` | `integrity_report` | 5446 | 16 | administration | `Depends(authorize(ADMIN_READ))` |
| POST | `/api/v1/admin/integrity/scrub` | `integrity_scrub_now` | 5465 | 6 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/objects/{oid}/reverify` | `reverify_object` | 5474 | 44 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/orphans` | `list_orphan_candidates` | 5521 | 25 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/storage-orphans` | `storage_orphans` | 5549 | 32 | administration | `Depends(authorize(ADMIN_READ))` |
| POST | `/api/v1/admin/storage-orphans/cleanup` | `storage_orphans_cleanup` | 5597 | 21 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/stats` | `admin_stats` | 5621 | 2 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/audit` | `search_audit` | 5632 | 38 | administration | `Depends(authorize(ADMIN_READ))` |
| POST | `/api/v1/admin/audit/prune` | `prune_audit` | 5673 | 10 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/portal-stats` | `admin_portal_stats` | 5686 | 31 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/usage` | `admin_usage` | 5720 | 70 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/health` | `admin_health` | 5793 | 73 | administration | `Depends(authorize(ADMIN_READ))` |
| POST | `/api/v1/admin/applications` | `create_application` | 5869 | 6 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/applications` | `list_applications` | 5878 | 2 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/applications/{aid}` | `get_application` | 5883 | 9 | administration | `Depends(authorize(ADMIN_READ))` |
| PATCH | `/api/v1/admin/applications/{aid}` | `update_application` | 5895 | 28 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/spaces` | `create_space` | 5937 | 21 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/spaces` | `list_spaces` | 5961 | 2 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/spaces/{sid}` | `get_space` | 5966 | 5 | administration | `Depends(authorize(ADMIN_READ))` |
| PATCH | `/api/v1/admin/spaces/{sid}` | `update_space` | 5974 | 36 | administration | `Depends(authorize(ADMIN_WRITE))` |
| PUT | `/api/v1/admin/spaces/{sid}/quotas` | `set_space_quotas` | 6013 | 17 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/spaces/{sid}/buckets` | `create_space_bucket` | 6033 | 18 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/buckets` | `list_buckets` | 6054 | 17 | administration | `Depends(authorize(ADMIN_READ))` |
| PATCH | `/api/v1/admin/buckets/{bid}` | `update_bucket` | 6074 | 17 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/identities` | `create_identity` | 6140 | 4 | administration | `Depends(authorize(ADMIN_WRITE))` |
| GET | `/api/v1/admin/identities` | `list_identities` | 6147 | 15 | administration | `Depends(authorize(ADMIN_READ))` |
| GET | `/api/v1/admin/partner-sites` | `list_partner_sites` | 6186 | 3 | administration | `Depends(authorize(ADMIN_READ))` |
| POST | `/api/v1/admin/partner-sites` | `create_partner_site` | 6192 | 35 | administration | `Depends(authorize(ADMIN_WRITE))` |
| PATCH | `/api/v1/admin/partner-sites/{pid}` | `update_partner_site` | 6230 | 36 | administration | `Depends(authorize(ADMIN_WRITE))` |
| DELETE | `/api/v1/admin/partner-sites/{pid}` | `delete_partner_site` | 6269 | 21 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/identities/{iid}/rotate` | `rotate_identity` | 6293 | 9 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/admin/identities/{iid}/revoke` | `revoke_identity` | 6305 | 8 | administration | `Depends(authorize(ADMIN_WRITE))` |
| POST | `/api/v1/import-jobs` | `create_import_job` | 6318 | 19 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |
| GET | `/api/v1/import-jobs` | `list_import_jobs` | 6340 | 15 | import et révisions | `Depends(authorize(OBJECTS_READ))` |
| POST | `/api/v1/import-jobs/{jid}/cancel` | `cancel_import_job` | 6358 | 14 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |
| GET | `/api/v1/objects/{oid}/revisions` | `list_object_revisions` | 6417 | 10 | import et révisions | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/revisions/{rid}` | `get_object_revision` | 6430 | 3 | import et révisions | `Depends(authorize(OBJECTS_READ))` |
| GET | `/api/v1/objects/{oid}/revisions/{rid}/download-intent` | `download_revision_intent` | 6436 | 34 | import et révisions | `Depends(authorize(OBJECTS_READ))` |
| DELETE | `/api/v1/objects/{oid}/revisions/{rid}` | `delete_object_revision` | 6473 | 28 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |
| PUT | `/api/v1/objects/{oid}/revisions/{rid}/keep-forever` | `set_revision_keep_forever` | 6504 | 20 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |
| DELETE | `/api/v1/objects/{oid}/revisions/{rid}/keep-forever` | `unset_revision_keep_forever` | 6527 | 11 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |
| POST | `/api/v1/objects/{oid}/revisions/{rid}/restore` | `restore_object_revision` | 6541 | 79 | import et révisions | `Depends(authorize(OBJECTS_WRITE))` |

## 9. Modèles Pydantic

| Modèle | Ligne | Lignes |
|---|---:|---:|
| `PublicationIn` | 708 | 14 |
| `ReplaceObjectIn` | 724 | 3 |
| `TagsIn` | 749 | 8 |
| `SubtitleIn` | 759 | 3 |
| `CollectionIn` | 764 | 18 |
| `CollectionPatchIn` | 784 | 5 |
| `CollectionItemsIn` | 791 | 3 |
| `ProgressIn` | 796 | 5 |
| `BookmarkIn` | 803 | 6 |
| `PlaylistIn` | 811 | 4 |
| `LoginIn` | 817 | 6 |
| `UploadIntentIn` | 825 | 18 |
| `ShareIn` | 845 | 12 |
| `FolderShareIn` | 859 | 10 |
| `ObjectPatchIn` | 871 | 6 |
| `ApplicationIn` | 879 | 8 |
| `SpaceIn` | 889 | 11 |
| `ApplicationPatchIn` | 902 | 19 |
| `SpacePatchIn` | 923 | 20 |
| `SpaceQuotasIn` | 945 | 9 |
| `BucketIn` | 956 | 10 |
| `BucketPatchIn` | 968 | 3 |
| `IdentityIn` | 973 | 6 |
| `PartnerSiteIn` | 1001 | 33 |
| `PartnerSitePatchIn` | 1036 | 28 |
| `ImportJobIn` | 1068 | 5 |
| `ImportJobOut` | 1075 | 13 |
| `FolderIn` | 1090 | 10 |
| `FolderPatchIn` | 1102 | 11 |
| `PublicProfilePatch` | 1856 | 3 |
| `MasterModeIn` | 2693 | 3 |
| `BulkIdsIn` | 2733 | 3 |
| `PartUrlsIn` | 3286 | 3 |
| `OrphanUploadIn` | 5583 | 4 |
| `OrphanCleanupIn` | 5589 | 5 |

