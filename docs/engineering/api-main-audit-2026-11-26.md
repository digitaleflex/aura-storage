# Audit structurel — `api/main.py` (#335)
> Généré le 2026-11-26 par `python scripts/audit_api_structure.py`. Aucun changement applicatif.
## Contexte prouvé
- Fichier: `api/main.py`
- Lignes: 6579
- Fonctions top-level: 265
- Classes top-level: 35
- Assignations top-level: 41
- Routes détectées (décorateurs app/router): 152
## Cartographie des routes
| Méthode | Chemin | Handler | Ligne | Async |
|---|---|---|---:|:---:|
| GET | `/health/live` | `live` | 1076 | no |
| GET | `/health/ready` | `ready` | 1089 | no |
| GET | `/api/v1/diag/ping` | `diag_ping` | 1118 | no |
| GET | `/api/v1/diag/download` | `diag_download` | 1136 | no |
| POST | `/api/v1/diag/upload` | `diag_upload` | 1154 | yes |
| GET | `/s/{token}` | `redeem_share` | 1194 | no |
| GET | `/f/{token}` | `view_folder_share` | 1348 | no |
| GET | `/f/{token}/o/{oid}` | `redeem_folder_share_object` | 1407 | no |
| POST | `/api/v1/login` | `login` | 1477 | no |
| POST | `/api/v1/logout` | `logout` | 1506 | no |
| GET | `/api/v1/me` | `me` | 1518 | no |
| GET | `/api/public/auth/google` | `public_auth_google` | 1585 | no |
| GET | `/api/public/auth/callback` | `public_auth_callback` | 1610 | no |
| POST | `/api/public/auth/email` | `public_email_link_request` | 1731 | yes |
| GET | `/connexion/lien` | `public_email_link_open` | 1764 | no |
| POST | `/api/public/auth/email/confirm` | `public_email_link_confirm` | 1779 | yes |
| GET | `/api/public/me` | `public_me` | 1827 | no |
| PATCH | `/api/public/me` | `public_me_patch` | 1851 | no |
| DELETE | `/api/public/me` | `public_me_delete` | 1859 | no |
| POST | `/api/public/logout` | `public_logout` | 1872 | no |
| GET | `/sw.js` | `portal_service_worker` | 1938 | no |
| GET | `/hors-ligne` | `portal_offline_page` | 1952 | no |
| GET | `/portal-assets/{name}` | `portal_asset` | 1967 | no |
| GET | `/profil` | `public_profile` | 1985 | no |
| POST | `/profil` | `public_profile_update` | 2004 | yes |
| POST | `/profil/supprimer` | `public_profile_delete` | 2020 | yes |
| GET | `/api/public/library` | `public_library` | 2143 | no |
| POST | `/api/public/progress` | `public_progress` | 2152 | no |
| GET | `/api/public/progress` | `public_progress_get` | 2183 | no |
| GET | `/api/public/bookmarks` | `public_bookmarks` | 2191 | no |
| POST | `/api/public/bookmarks` | `public_bookmark_add` | 2197 | no |
| DELETE | `/api/public/bookmarks/{bookmark_id}` | `public_bookmark_delete` | 2211 | no |
| PUT | `/api/public/favorites/{oid}` | `public_favorite_add` | 2233 | no |
| DELETE | `/api/public/favorites/{oid}` | `public_favorite_remove` | 2239 | no |
| POST | `/api/public/playlists/create` | `public_playlist_create_form` | 2252 | yes |
| POST | `/api/public/playlists/{pid}/delete` | `public_playlist_delete_form` | 2264 | yes |
| GET | `/api/public/stats` | `public_stats` | 2321 | no |
| GET | `/api/public/playlists` | `public_playlists` | 2327 | no |
| POST | `/api/public/playlists` | `public_playlist_create` | 2333 | no |
| PATCH | `/api/public/playlists/{pid}` | `public_playlist_rename` | 2344 | no |
| DELETE | `/api/public/playlists/{pid}` | `public_playlist_delete` | 2358 | no |
| GET | `/api/public/playlists/{pid}/items` | `public_playlist_items` | 2369 | no |
| PUT | `/api/public/playlists/{pid}/items/{oid}` | `public_playlist_add_item` | 2375 | no |
| DELETE | `/api/public/playlists/{pid}/items/{oid}` | `public_playlist_remove_item` | 2388 | no |
| GET | `/` | `public_portal` | 2400 | no |
| GET | `/livre/{oid}` | `public_book_page` | 2539 | no |
| GET | `/extrait/{oid}` | `public_preview` | 2584 | no |
| GET | `/robots.txt` | `public_robots` | 2616 | no |
| GET | `/sitemap.xml` | `public_sitemap` | 2630 | no |
| POST | `/api/v1/me/master-mode` | `master_mode_on` | 2659 | no |
| DELETE | `/api/v1/me/master-mode` | `master_mode_off` | 2682 | no |
| POST | `/api/v1/objects/bulk-purge` | `bulk_purge` | 2722 | no |
| POST | `/api/v1/objects/trash/empty` | `empty_trash` | 2731 | no |
| POST | `/api/v1/objects/upload-intents` | `upload_intent` | 2754 | no |
| POST | `/api/v1/objects/{oid}/replace-intents` | `create_replace_intent` | 2983 | no |
| GET | `/api/v1/objects/{oid}/multipart` | `multipart_status` | 3252 | no |
| POST | `/api/v1/objects/{oid}/multipart/parts` | `multipart_part_urls` | 3265 | no |
| POST | `/api/v1/objects/{oid}/commit` | `commit_object` | 3476 | no |
| POST | `/api/v1/objects/{oid}/abort` | `abort_object` | 3743 | no |
| POST | `/api/v1/objects/{oid}/public-access` | `create_public_access` | 3793 | no |
| DELETE | `/api/v1/objects/{oid}/public-access` | `revoke_public_access` | 3822 | no |
| GET | `/api/v1/objects` | `list_objects` | 3852 | no |
| GET | `/api/v1/objects/tags` | `list_object_tags` | 3901 | no |
| GET | `/api/v1/objects/{oid}` | `get_object` | 3917 | no |
| GET | `/api/v1/transfers` | `list_transfers` | 3926 | no |
| GET | `/api/v1/transfers/{tid}` | `get_transfer` | 3970 | no |
| GET | `/api/v1/objects/{oid}/analytics` | `object_analytics` | 3981 | no |
| DELETE | `/api/v1/objects/{oid}` | `soft_delete_object` | 4008 | no |
| POST | `/api/v1/objects/{oid}/restore` | `restore_object` | 4025 | no |
| PATCH | `/api/v1/objects/{oid}` | `update_object` | 4044 | no |
| POST | `/api/v1/objects/{oid}/share` | `create_object_share` | 4070 | no |
| GET | `/api/v1/objects/{oid}/shares` | `list_object_shares` | 4137 | no |
| DELETE | `/api/v1/objects/{oid}/shares/{sid}` | `revoke_object_share` | 4168 | no |
| POST | `/api/v1/objects/{oid}/purge` | `purge` | 4202 | no |
| POST | `/api/v1/objects/{oid}/download-intent` | `download_intent` | 4223 | no |
| POST | `/api/v1/objects/{oid}/preview-intent` | `preview_intent` | 4299 | no |
| GET | `/api/v1/objects/{oid}/thumbnail` | `object_thumbnail` | 4431 | no |
| PUT | `/api/v1/objects/{oid}/publication` | `set_object_publication` | 4463 | no |
| POST | `/api/v1/objects/{oid}/replace` | `replace_object_content` | 4494 | no |
| GET | `/m/{slug}` | `public_media` | 4575 | no |
| GET | `/d/{slug}` | `public_download` | 4614 | no |
| GET | `/a/{token}` | `public_granted_media` | 4659 | no |
| GET | `/covers/{oid}.jpg` | `public_cover` | 4705 | no |
| POST | `/api/v1/objects/{oid}/hls` | `prepare_hls` | 4756 | no |
| GET | `/api/v1/objects/{oid}/hls/status` | `hls_status` | 4773 | no |
| GET | `/api/v1/objects/{oid}/hls/index.m3u8` | `hls_playlist` | 4787 | no |
| GET | `/api/v1/objects/{oid}/hls/{segment}` | `hls_segment` | 4798 | no |
| PUT | `/api/v1/objects/{oid}/subtitle` | `set_subtitle` | 4813 | no |
| GET | `/hls/{slug}.m3u8` | `public_hls_playlist` | 4836 | no |
| GET | `/hls/{slug}/{segment}` | `public_hls_segment` | 4856 | no |
| GET | `/m/{slug}/subtitles.vtt` | `public_subtitle` | 4880 | no |
| PUT | `/api/v1/objects/{oid}/tags` | `set_object_tags` | 4931 | no |
| GET | `/api/v1/collections` | `list_collections` | 4948 | no |
| POST | `/api/v1/collections` | `create_collection` | 4954 | no |
| GET | `/api/v1/collections/{cid}` | `get_collection` | 4971 | no |
| PATCH | `/api/v1/collections/{cid}` | `update_collection` | 4981 | no |
| PUT | `/api/v1/collections/{cid}/items` | `set_collection_items` | 5008 | no |
| DELETE | `/api/v1/collections/{cid}` | `delete_collection` | 5029 | no |
| GET | `/p/{slug}.json` | `public_collection_manifest` | 5038 | no |
| GET | `/api/v1/folders` | `list_folders` | 5104 | no |
| GET | `/api/v1/folders/{fid}` | `get_folder` | 5138 | no |
| POST | `/api/v1/folders` | `create_folder` | 5150 | no |
| PATCH | `/api/v1/folders/{fid}` | `update_folder` | 5165 | no |
| DELETE | `/api/v1/folders/{fid}` | `delete_folder` | 5220 | no |
| POST | `/api/v1/folders/{fid}/share` | `create_folder_share` | 5247 | no |
| GET | `/api/v1/folders/{fid}/shares` | `list_folder_shares` | 5302 | no |
| DELETE | `/api/v1/folders/{fid}/shares/{sid}` | `revoke_folder_share` | 5331 | no |
| POST | `/api/v1/admin/reconcile` | `reconcile` | 5360 | no |
| POST | `/api/v1/admin/reconcile-terminal` | `reconcile_terminal_route` | 5389 | no |
| POST | `/api/v1/admin/reconcile-reverse` | `reconcile_reverse_route` | 5398 | no |
| GET | `/api/v1/admin/integrity` | `integrity_report` | 5406 | no |
| POST | `/api/v1/admin/integrity/scrub` | `integrity_scrub_now` | 5425 | no |
| POST | `/api/v1/admin/objects/{oid}/reverify` | `reverify_object` | 5434 | no |
| GET | `/api/v1/admin/orphans` | `list_orphan_candidates` | 5481 | no |
| GET | `/api/v1/admin/storage-orphans` | `storage_orphans` | 5509 | no |
| POST | `/api/v1/admin/storage-orphans/cleanup` | `storage_orphans_cleanup` | 5557 | no |
| GET | `/api/v1/admin/stats` | `admin_stats` | 5581 | no |
| GET | `/api/v1/admin/audit` | `search_audit` | 5592 | no |
| POST | `/api/v1/admin/audit/prune` | `prune_audit` | 5633 | no |
| GET | `/api/v1/admin/portal-stats` | `admin_portal_stats` | 5646 | no |
| GET | `/api/v1/admin/usage` | `admin_usage` | 5680 | no |
| GET | `/api/v1/admin/health` | `admin_health` | 5753 | no |
| POST | `/api/v1/admin/applications` | `create_application` | 5829 | no |
| GET | `/api/v1/admin/applications` | `list_applications` | 5838 | no |
| GET | `/api/v1/admin/applications/{aid}` | `get_application` | 5843 | no |
| PATCH | `/api/v1/admin/applications/{aid}` | `update_application` | 5855 | no |
| POST | `/api/v1/admin/spaces` | `create_space` | 5897 | no |
| GET | `/api/v1/admin/spaces` | `list_spaces` | 5921 | no |
| GET | `/api/v1/admin/spaces/{sid}` | `get_space` | 5926 | no |
| PATCH | `/api/v1/admin/spaces/{sid}` | `update_space` | 5934 | no |
| PUT | `/api/v1/admin/spaces/{sid}/quotas` | `set_space_quotas` | 5973 | no |
| POST | `/api/v1/admin/spaces/{sid}/buckets` | `create_space_bucket` | 5993 | no |
| GET | `/api/v1/admin/buckets` | `list_buckets` | 6014 | no |
| PATCH | `/api/v1/admin/buckets/{bid}` | `update_bucket` | 6034 | no |
| POST | `/api/v1/admin/identities` | `create_identity` | 6100 | no |
| GET | `/api/v1/admin/identities` | `list_identities` | 6107 | no |
| GET | `/api/v1/admin/partner-sites` | `list_partner_sites` | 6146 | no |
| POST | `/api/v1/admin/partner-sites` | `create_partner_site` | 6152 | no |
| PATCH | `/api/v1/admin/partner-sites/{pid}` | `update_partner_site` | 6190 | no |
| DELETE | `/api/v1/admin/partner-sites/{pid}` | `delete_partner_site` | 6229 | no |
| POST | `/api/v1/admin/identities/{iid}/rotate` | `rotate_identity` | 6253 | no |
| POST | `/api/v1/admin/identities/{iid}/revoke` | `revoke_identity` | 6265 | no |
| POST | `/api/v1/import-jobs` | `create_import_job` | 6278 | no |
| GET | `/api/v1/import-jobs` | `list_import_jobs` | 6300 | no |
| POST | `/api/v1/import-jobs/{jid}/cancel` | `cancel_import_job` | 6318 | no |
| GET | `/api/v1/objects/{oid}/revisions` | `list_object_revisions` | 6377 | no |
| GET | `/api/v1/objects/{oid}/revisions/{rid}` | `get_object_revision` | 6390 | no |
| GET | `/api/v1/objects/{oid}/revisions/{rid}/download-intent` | `download_revision_intent` | 6396 | no |
| DELETE | `/api/v1/objects/{oid}/revisions/{rid}` | `delete_object_revision` | 6433 | no |
| PUT | `/api/v1/objects/{oid}/revisions/{rid}/keep-forever` | `set_revision_keep_forever` | 6464 | no |
| DELETE | `/api/v1/objects/{oid}/revisions/{rid}/keep-forever` | `unset_revision_keep_forever` | 6487 | no |
| POST | `/api/v1/objects/{oid}/revisions/{rid}/restore` | `restore_object_revision` | 6501 | no |

## Domaines (heuristique par chemin)

| Domaine | Routes |
|---|---:|
| objects_transfers | 41 |
| admin | 35 |
| other | 28 |
| portal_public | 26 |
| folders_shares | 8 |
| collections | 6 |
| auth | 5 |
| import_jobs | 3 |

## Fonctions/classes les plus volumineuses (proxy complexité)

| Nom | Ligne | Lignes | Type |
|---|---:|---:|---|
| `commit_object` | 3476 | 264 | fn |
| `upload_intent` | 2754 | 226 | fn |
| `_finalize_replacement_commit` | 3335 | 137 | fn |
| `create_replace_intent` | 2983 | 119 | fn |
| `redeem_share` | 1194 | 85 | fn |
| `restore_object_revision` | 6501 | 79 | fn |
| `admin_health` | 5753 | 73 | fn |
| `admin_usage` | 5680 | 70 | fn |
| `public_portal` | 2400 | 68 | fn |
| `redeem_folder_share_object` | 1407 | 67 | fn |
| `create_object_share` | 4070 | 64 | fn |
| `public_auth_callback` | 1610 | 59 | fn |
| `view_folder_share` | 1348 | 56 | fn |
| `update_folder` | 5165 | 52 | fn |
| `create_folder_share` | 5247 | 52 | fn |
| `replace_object_content` | 4494 | 48 | fn |
| `list_objects` | 3852 | 46 | fn |
| `_public_listening_stats` | 2273 | 45 | fn |
| `reverify_object` | 5434 | 44 | fn |
| `_create_service_identity` | 6053 | 44 | fn |
| `public_granted_media` | 4659 | 43 | fn |
| `public_book_page` | 2539 | 42 | fn |
| `public_download` | 4614 | 42 | fn |
| `list_transfers` | 3926 | 41 | fn |
| `_complete_multipart_session` | 3193 | 39 | fn |
| `search_audit` | 5592 | 38 | fn |
| `abort_object` | 3743 | 37 | fn |
| `_library_items` | 2043 | 36 | fn |
| `public_media` | 4575 | 36 | fn |
| `update_space` | 5934 | 36 | fn |
| `PartnerSiteIn` | 961 | 33 | class |
| `PartnerSitePatchIn` | 996 | 28 | class |
| `SpacePatchIn` | 883 | 20 | class |
| `ApplicationPatchIn` | 862 | 19 | class |
| `CollectionIn` | 724 | 18 | class |
| `UploadIntentIn` | 785 | 18 | class |
| `PublicationIn` | 668 | 14 | class |
| `ImportJobOut` | 1035 | 13 | class |
| `ShareIn` | 805 | 12 | class |
| `SpaceIn` | 849 | 11 | class |
| `FolderPatchIn` | 1062 | 11 | class |
| `FolderShareIn` | 819 | 10 | class |
| `BucketIn` | 916 | 10 | class |
| `FolderIn` | 1050 | 10 | class |
| `SpaceQuotasIn` | 905 | 9 | class |

## Imports / modules

- `.`
- `.audit`
- `.auth`
- `.authz`
- `.avscan`
- `.config`
- `.identity`
- `.import_worker`
- `.lifecycle`
- `.reconciler`
- `.s3`
- `.scrubber`
- `.storage_reconcile`
- `.store`
- `.transfer`
- `.verifier`
- `concurrent.futures`
- `fastapi`
- `fastapi.exception_handlers`
- `fastapi.responses`
- `hashlib`
- `html`
- `logging`
- `os`
- `pydantic`
- `re`
- `secrets`
- `shutil`
- `starlette.exceptions`
- `subprocess`
- `threading`
- `time`
- `typing`
- `urllib.parse`

## Signaux d’effets de bord / risques (comptage heuristique)

| Signal | Occurrences |
|---|---:|
| module_globals | 33 |
| app_state | 0 |
| threads_workers | 44 |
| env_reads | 0 |
| file_io | 5 |
| subprocess | 2 |
| db_conn | 359 |
| s3 | 192 |

## Constats prouvés
- `api/main.py` concentre HTTP, auth, portail, objets, médias, dossiers, partages, admin, import et révisions.
- Des modules spécialisés existent déjà (`api/authz.py`, `api/store.py`, `api/s3.py`, `api/lifecycle.py`, `api/transfer.py`, `api/reconciler.py`, `api/verifier.py`, `api/scrubber.py`, etc.) et doivent être réutilisés avant toute réécriture.
- La surface route est large ; toute extraction doit préserver chemins, méthodes, contrats OpenAPI et tests.

## Risques
- Effets de bord à l’import et globals mutables peuvent casser les tests lors d’extractions.
- Transactions, idempotence et ordre des middlewares sont sensibles.
- Couplage implicite entre helpers de sérialisation, modèles Pydantic et routes.

## Candidats extraction (ordre recommandé)
1. Baseline tests/OpenAPI/snapshots routes (#336).
2. Frontières d’architecture et règles dépendances (#337).
3. Factory `create_app()`/composition root (#338).
4. Middlewares/cycle de vie (#339).
5. Schémas Pydantic (#340), normalisation/sérialisation (#341).
6. Routeurs domaine par domaine: auth, portail, objets/transferts, médias/collections, dossiers/partages, admin, import/revisions (#342-#348).

## Limites de l’audit
- Complexité basée sur heuristiques (taille, motifs) ; pas un graphe d’appels complet.
- Les routes déclarées hors décorateurs standards ou via include_router indirect peuvent demander une vérification manuelle.
