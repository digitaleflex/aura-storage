# Audit des routes API réelles (réconciliation docs/OpenAPI)

> **Généré le 2026-11-26** depuis `api/main.py`. La parité avec `docs/openapi.yaml` est vérifiée par `tests/test_openapi_contract.py`. La source de vérité fonctionnelle est [`ETAT-DES-FONCTIONNALITES.md`](ETAT-DES-FONCTIONNALITES.md). Issue #324.

Source : `api/main.py` — **152 routes applicatives** détectées (hors `/docs`, `/redoc`, `/openapi.json` gérés par FastAPI).


## Santé

- `GET /health/live`
- `GET /health/ready`

## Partages publics

- `GET /s/{token}`
- `GET /f/{token}`
- `GET /f/{token}/o/{oid}`

## Auth & session (app)

- `POST /api/v1/login`
- `POST /api/v1/logout`
- `GET /api/v1/me`
- `POST /api/v1/me/master-mode`
- `DELETE /api/v1/me/master-mode`

## Auth & compte (portail public)

- `GET /api/public/auth/google`
- `GET /api/public/auth/callback`
- `POST /api/public/auth/email`
- `GET /connexion/lien`
- `POST /api/public/auth/email/confirm`
- `GET /api/public/me`
- `PATCH /api/public/me`
- `DELETE /api/public/me`
- `POST /api/public/logout`

## Portail public (pages & médias)

- `GET /sw.js`
- `GET /hors-ligne`
- `GET /portal-assets/{name}`
- `GET /profil`
- `POST /profil`
- `POST /profil/supprimer`
- `GET /`
- `GET /livre/{oid}`
- `GET /extrait/{oid}`
- `GET /robots.txt`
- `GET /sitemap.xml`
- `GET /m/{slug}`
- `GET /d/{slug}`
- `GET /a/{token}`
- `GET /covers/{oid}.jpg`
- `GET /hls/{slug}.m3u8`
- `GET /hls/{slug}/{segment}`
- `GET /m/{slug}/subtitles.vtt`
- `GET /p/{slug}.json`

## Portail public (API)

- `GET /api/public/library`
- `POST /api/public/progress`
- `GET /api/public/progress`
- `GET /api/public/bookmarks`
- `POST /api/public/bookmarks`
- `DELETE /api/public/bookmarks/{bookmark_id}`
- `PUT /api/public/favorites/{oid}`
- `DELETE /api/public/favorites/{oid}`
- `POST /api/public/playlists/create`
- `POST /api/public/playlists/{pid}/delete`
- `GET /api/public/stats`
- `GET /api/public/playlists`
- `POST /api/public/playlists`
- `PATCH /api/public/playlists/{pid}`
- `DELETE /api/public/playlists/{pid}`
- `GET /api/public/playlists/{pid}/items`
- `PUT /api/public/playlists/{pid}/items/{oid}`
- `DELETE /api/public/playlists/{pid}/items/{oid}`

## Objets & transferts

- `POST /api/v1/objects/bulk-purge`
- `POST /api/v1/objects/trash/empty`
- `POST /api/v1/objects/upload-intents`
- `POST /api/v1/objects/{oid}/replace-intents`
- `GET /api/v1/objects/{oid}/multipart`
- `POST /api/v1/objects/{oid}/multipart/parts`
- `POST /api/v1/objects/{oid}/commit`
- `POST /api/v1/objects/{oid}/abort`
- `POST /api/v1/objects/{oid}/public-access`
- `DELETE /api/v1/objects/{oid}/public-access`
- `GET /api/v1/objects`
- `GET /api/v1/objects/tags`
- `GET /api/v1/objects/{oid}`
- `GET /api/v1/transfers`
- `GET /api/v1/transfers/{tid}`
- `GET /api/v1/objects/{oid}/analytics`
- `DELETE /api/v1/objects/{oid}`
- `POST /api/v1/objects/{oid}/restore`
- `PATCH /api/v1/objects/{oid}`
- `POST /api/v1/objects/{oid}/share`
- `GET /api/v1/objects/{oid}/shares`
- `DELETE /api/v1/objects/{oid}/shares/{sid}`
- `POST /api/v1/objects/{oid}/purge`
- `POST /api/v1/objects/{oid}/download-intent`
- `POST /api/v1/objects/{oid}/preview-intent`
- `GET /api/v1/objects/{oid}/thumbnail`
- `PUT /api/v1/objects/{oid}/publication`
- `POST /api/v1/objects/{oid}/replace`
- `POST /api/v1/objects/{oid}/hls`
- `GET /api/v1/objects/{oid}/hls/status`
- `GET /api/v1/objects/{oid}/hls/index.m3u8`
- `GET /api/v1/objects/{oid}/hls/{segment}`
- `PUT /api/v1/objects/{oid}/subtitle`
- `PUT /api/v1/objects/{oid}/tags`
- `GET /api/v1/objects/{oid}/revisions`
- `GET /api/v1/objects/{oid}/revisions/{rid}`
- `GET /api/v1/objects/{oid}/revisions/{rid}/download-intent`
- `DELETE /api/v1/objects/{oid}/revisions/{rid}`
- `PUT /api/v1/objects/{oid}/revisions/{rid}/keep-forever`
- `DELETE /api/v1/objects/{oid}/revisions/{rid}/keep-forever`
- `POST /api/v1/objects/{oid}/revisions/{rid}/restore`

## Collections & dossiers

- `GET /api/v1/collections`
- `POST /api/v1/collections`
- `GET /api/v1/collections/{cid}`
- `PATCH /api/v1/collections/{cid}`
- `PUT /api/v1/collections/{cid}/items`
- `DELETE /api/v1/collections/{cid}`
- `GET /api/v1/folders`
- `GET /api/v1/folders/{fid}`
- `POST /api/v1/folders`
- `PATCH /api/v1/folders/{fid}`
- `DELETE /api/v1/folders/{fid}`
- `POST /api/v1/folders/{fid}/share`
- `GET /api/v1/folders/{fid}/shares`
- `DELETE /api/v1/folders/{fid}/shares/{sid}`

## Administration

- `POST /api/v1/admin/reconcile`
- `POST /api/v1/admin/reconcile-terminal`
- `POST /api/v1/admin/reconcile-reverse`
- `GET /api/v1/admin/integrity`
- `POST /api/v1/admin/integrity/scrub`
- `POST /api/v1/admin/objects/{oid}/reverify`
- `GET /api/v1/admin/orphans`
- `GET /api/v1/admin/storage-orphans`
- `POST /api/v1/admin/storage-orphans/cleanup`
- `GET /api/v1/admin/stats`
- `GET /api/v1/admin/audit`
- `POST /api/v1/admin/audit/prune`
- `GET /api/v1/admin/portal-stats`
- `GET /api/v1/admin/usage`
- `GET /api/v1/admin/health`
- `POST /api/v1/admin/applications`
- `GET /api/v1/admin/applications`
- `GET /api/v1/admin/applications/{aid}`
- `PATCH /api/v1/admin/applications/{aid}`
- `POST /api/v1/admin/spaces`
- `GET /api/v1/admin/spaces`
- `GET /api/v1/admin/spaces/{sid}`
- `PATCH /api/v1/admin/spaces/{sid}`
- `PUT /api/v1/admin/spaces/{sid}/quotas`
- `POST /api/v1/admin/spaces/{sid}/buckets`
- `GET /api/v1/admin/buckets`
- `PATCH /api/v1/admin/buckets/{bid}`
- `POST /api/v1/admin/identities`
- `GET /api/v1/admin/identities`
- `GET /api/v1/admin/partner-sites`
- `POST /api/v1/admin/partner-sites`
- `PATCH /api/v1/admin/partner-sites/{pid}`
- `DELETE /api/v1/admin/partner-sites/{pid}`
- `POST /api/v1/admin/identities/{iid}/rotate`
- `POST /api/v1/admin/identities/{iid}/revoke`

## Import jobs

- `POST /api/v1/import-jobs`
- `GET /api/v1/import-jobs`
- `POST /api/v1/import-jobs/{jid}/cancel`

## Diagnostic réseau

- `GET /api/v1/diag/ping`
- `GET /api/v1/diag/download`
- `POST /api/v1/diag/upload`
