# Audit des routes API réelles (réconciliation docs/OpenAPI)

Source : `api/main.py` — **63 routes applicatives** détectées (hors `/docs`, `/redoc`, `/openapi.json` et `/docs/oauth2-redirect`, fournis par FastAPI).
Régénéré le 2026-10-24. La parité avec `docs/openapi.yaml` est vérifiée automatiquement par `tests/test_openapi_contract.py` (chemins + méthodes).

## Santé & partage public

- `GET /health/live`
- `GET /health/ready`
- `GET /s/{token}`

## Auth & session

- `DELETE /api/v1/me/master-mode`
- `GET /api/v1/me`
- `POST /api/v1/login`
- `POST /api/v1/logout`
- `POST /api/v1/me/master-mode`

## Objets

- `DELETE /api/v1/objects/{oid}`
- `DELETE /api/v1/objects/{oid}/shares/{sid}`
- `GET /api/v1/objects`
- `GET /api/v1/objects/{oid}`
- `GET /api/v1/objects/{oid}/multipart`
- `GET /api/v1/objects/{oid}/shares`
- `PATCH /api/v1/objects/{oid}`
- `POST /api/v1/objects/bulk-purge`
- `POST /api/v1/objects/trash/empty`
- `POST /api/v1/objects/upload-intents`
- `POST /api/v1/objects/{oid}/abort`
- `POST /api/v1/objects/{oid}/commit`
- `POST /api/v1/objects/{oid}/download-intent`
- `POST /api/v1/objects/{oid}/multipart/parts`
- `POST /api/v1/objects/{oid}/preview-intent`
- `POST /api/v1/objects/{oid}/purge`
- `POST /api/v1/objects/{oid}/restore`
- `POST /api/v1/objects/{oid}/share`

## Dossiers

- `DELETE /api/v1/folders/{fid}`
- `GET /api/v1/folders`
- `GET /api/v1/folders/{fid}`
- `PATCH /api/v1/folders/{fid}`
- `POST /api/v1/folders`

## Diagnostic réseau

- `GET /api/v1/diag/download`
- `GET /api/v1/diag/ping`
- `POST /api/v1/diag/upload`

## Administration

- `GET /api/v1/admin/applications`
- `GET /api/v1/admin/applications/{aid}`
- `GET /api/v1/admin/audit`
- `GET /api/v1/admin/buckets`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/identities`
- `GET /api/v1/admin/integrity`
- `GET /api/v1/admin/orphans`
- `GET /api/v1/admin/spaces`
- `GET /api/v1/admin/spaces/{sid}`
- `GET /api/v1/admin/stats`
- `GET /api/v1/admin/storage-orphans`
- `GET /api/v1/admin/usage`
- `PATCH /api/v1/admin/applications/{aid}`
- `PATCH /api/v1/admin/buckets/{bid}`
- `PATCH /api/v1/admin/spaces/{sid}`
- `POST /api/v1/admin/applications`
- `POST /api/v1/admin/audit/prune`
- `POST /api/v1/admin/identities`
- `POST /api/v1/admin/identities/{iid}/revoke`
- `POST /api/v1/admin/identities/{iid}/rotate`
- `POST /api/v1/admin/integrity/scrub`
- `POST /api/v1/admin/objects/{oid}/reverify`
- `POST /api/v1/admin/reconcile`
- `POST /api/v1/admin/reconcile-reverse`
- `POST /api/v1/admin/reconcile-terminal`
- `POST /api/v1/admin/spaces`
- `POST /api/v1/admin/spaces/{sid}/buckets`
- `POST /api/v1/admin/storage-orphans/cleanup`

## Vérification

`python -m pytest tests/test_openapi_contract.py -q` doit passer : chaque route ci-dessus
est documentée, et aucune route documentée n'est absente du code.
