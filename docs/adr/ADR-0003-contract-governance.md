# ADR-0003 — Gouvernance des contrats et compatibilité

- Statut: Accepté
- Approuvé le: 2026-11-28
- Date: 2026-11-26
- Issue: #330

## Contrats couverts

- HTTP/OpenAPI (`docs/openapi.yaml`, `tests/test_openapi_contract.py`).
- Schémas Pydantic request/response.
- Jobs internes/états (import, verify, scrub, reconcile).
- Schéma DB SQLite/PostgreSQL et migrations.
- Contrats inter-domaines (interfaces de service/port).

## Règles

- **Compatibilité ascendante par défaut**. Breaking change = explicite, versionné, plan de migration.
- **Erreurs stables**: codes HTTP + format d’erreur documenté; ne pas exposer détails internes.
- **Événements/jobs**: id, type, version de schéma, occurred_at, correlation/request id, payload minimal.
- **DB**: migrations incrémentales; backfill idempotent; éviter suppression destructive sans fenêtre de compatibilité.
- **OpenAPI**: toute PR qui change routes/schémas met à jour OpenAPI et tests contrat.
- **Adaptateurs SQLite/PG**: même comportement observable; différences isolées.

## Contrôles

- CI: `tests/test_openapi_contract.py`.
- PR checklist: migration, compat, rollback, doc.
- Avant extraction: snapshot routes (#336) comparé.
