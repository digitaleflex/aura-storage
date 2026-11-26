# ADR-0004 — Contrôles automatiques des frontières de modules

- Statut: Proposé
- Date: 2026-11-26
- Issue: #331

## Objectif

Empêcher les régressions d’architecture pendant les extractions.

## Contrôles prévus

1. **Import-linter / test AST**: interdictions domaine->FastAPI/boto3/psycopg/sqlite3; http->infrastructure direct (sauf composition root).
2. **Snapshot routes/OpenAPI**: `test_openapi_contract.py` + snapshot routes baseline.
3. **Ownership tables**: test/documentation qui mappe table->domaine propriétaire.
4. **Taille/complexité**: suivi de `api/main.py` LOC et fonctions > seuil.
5. **CI**: exécuter ces checks en PR.

## Rollout

- Commencer par checks documentaires + script simple.
- Durcir progressivement après extractions.
