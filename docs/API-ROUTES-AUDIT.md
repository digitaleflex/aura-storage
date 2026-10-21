# Audit des routes API réelles (réconciliation docs/OpenAPI)

Source : `api/main.py` — 59 routes détectées.

## Routes réelles (méthode + chemin)

Voir `/tmp` extraction ; liste complète ci-dessous.

### Santé & partage public
- GET /health/live
- GET /health/ready
- GET /s/{token}

### Auth & session
- POST /api/v1/login
- POST /api/v1/logout
- GET /api/v1/me
- POST /api/v1/me/master-mode
- DELETE /api/v1/me/master-mode

### Objets
- POST /api/v1/objects/bulk-purge
- POST /api/v1/objects/trash/empty
- POST /api/v1/objects/upload-intents
- GET /api/v1/objects/{oid}/multipart
- POST /api/v1/objects/{oid}/multipart/parts
- POST /api/v1/objects/{oid}/commit
- POST /api/v1/objects/{oid}/abort
- GET /api/v1/objects
- GET /api/v1/objects/{oid}
- DELETE /api/v1/objects/{oid}
- POST /api/v1/objects/{oid}/restore
- PATCH /api/v1/objects/{oid}
- POST /api/v1/objects/{oid}/share
- GET /api/v1/objects/{oid}/shares
- DELETE /api/v1/objects/{oid}/shares/{sid}
- POST /api/v1/objects/{oid}/purge
- POST /api/v1/objects/{oid}/download-intent
- POST /api/v1/objects/{oid}/preview-intent

### Dossiers
- GET /api/v1/folders
- GET /api/v1/folders/{fid}
- POST /api/v1/folders
- PATCH /api/v1/folders/{fid}
- DELETE /api/v1/folders/{fid}

### Admin
- GET /api/v1/admin/applications
- GET /api/v1/admin/applications/{aid}
- GET /api/v1/admin/audit
- GET /api/v1/admin/buckets
- GET /api/v1/admin/health
- GET /api/v1/admin/identities
- GET /api/v1/admin/integrity
- GET /api/v1/admin/orphans
- GET /api/v1/admin/spaces
- GET /api/v1/admin/spaces/{sid}
- GET /api/v1/admin/stats
- GET /api/v1/admin/storage-orphans
- GET /api/v1/admin/usage
- POST /api/v1/admin/applications
- POST /api/v1/admin/buckets
- DELETE /api/v1/admin/applications/{aid}
- PATCH /api/v1/admin/spaces/{sid}
- POST /api/v1/admin/spaces
- POST /api/v1/admin/identities
- GET /api/v1/admin/identities/{iid}
- DELETE /api/v1/admin/identities/{iid}
- POST /api/v1/admin/identities/{iid}/rotate-secret
- GET /api/v1/admin/applications/{aid}/identities
- POST /api/v1/admin/applications/{aid}/identities
- GET /api/v1/admin/multipart-uploads
- POST /api/v1/admin/reconcile
- GET /api/v1/admin/reconcile/status
- POST /api/v1/admin/storage-orphans/{oid}/purge

## Action
Comparer cette liste avec `docs/openapi.yaml` et corriger les écarts. Aucun écart ne doit subsister sans mention explicite.
EOF
echo done