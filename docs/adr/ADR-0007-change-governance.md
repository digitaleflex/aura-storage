# ADR-0007 — Gouvernance du changement et nouveaux domaines

- Statut: Proposé
- Date: 2026-11-26
- Issue: #334

## Règles pour tout nouveau domaine/capacité

- Déclarer propriétaire, invariants, tables, API, events/jobs.
- Ajouter tests contrat + non-régression.
- Documenter migration/rollback.
- Ne pas ajouter de logique métier dans `api/main.py`; créer module/routeur/service dédié.
- Vérifier compat SQLite/PG ou isoler derrière port.
- Mettre à jour OpenAPI, ETAT-DES-FONCTIONNALITES, et ADR si décision structurante.
