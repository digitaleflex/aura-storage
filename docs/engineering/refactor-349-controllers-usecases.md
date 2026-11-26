# #349 — Séparer contrôleurs HTTP, cas d'usage et logique domaine

## État
Tranches déjà extraites: schemas (#340), normalizers (#341), middlewares (#339), routes (348,342,347,345,344,346). `api/main.py` reste un point d'assemblage important.

## Cible par tranche
1. **Contrôleurs HTTP**: validation I/O, authz, mapping HTTP, pas de SQL/S3 direct.
2. **Use-cases**: orchestration métier (`create_share`, `commit_object`, `restore_revision`...), dépendances injectées.
3. **Domaine/services**: invariants, transitions, politiques.
4. **Infra**: repo DB, S3, audit, config.

## Ordre proposé
- Shares/transferts/intents (déjà extraits en routes) -> use-cases.
- Objets/multipart lifecycle.
- Admin/reconcile.
- Public portal.

## Critères
- Pas de SQL/S3 direct dans handlers.
- Dépendances injectables pour tests.
- Contrat OpenAPI inchangé.
