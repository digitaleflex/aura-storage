# ADR-0002 — Architecture cible évolutive du monolithe modulaire AURA

- Statut: Accepté
- Approuvé le: 2026-11-28
- Date: 2026-11-26
- Issue: #329

## Décision

AURA reste un **monolithe modulaire** déployé simplement. La complexité est absorbée par des domaines propriétaires, des cas d’usage applicatifs, et des ports/adaptateurs aux frontières I/O.

## Structure cible

```text
api/
  app_factory.py          # composition root / create_app
  http/                   # routeurs FastAPI minces
  application/            # cas d'usage, transactions, orchestration
  domain/                 # règles/invariants, sans I/O
  infrastructure/         # postgres/sqlite, s3, fs, clock, queues
  contracts/              # schémas partagés versionnés si nécessaire
```

## Règles

- Routeur HTTP: parse, authz, appelle un cas d’usage, mappe erreurs.
- Cas d’usage: orchestre, contrôle transaction/idempotence.
- Domaine: pur, testable sans FastAPI/DB/S3.
- Infrastructure: implémente ports; pas de règle métier.
- `api.main:app` reste le point d’entrée compatible.

## Migration

1. Baseline OpenAPI/tests (#336).
2. `create_app()` (#338).
3. Extraire routeurs par domaine sans changer les contrats (#342-348).
4. Déplacer la logique applicative derrière services/use-cases (#349).
5. Ajouter garde-fous de dépendances et typage (#331, #350).

## Non-objectifs

- Pas de microservices par défaut.
- Pas de big bang.
- Pas de changement de contrat HTTP sans versionnement/dépréciation.
