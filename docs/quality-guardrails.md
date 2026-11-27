# Garde-fous qualité (#350)

## État
- Baseline tests: voir `docs/engineering/refactor-baseline-2026-11-26.md`.
- OpenAPI contract: `tests/test_openapi_contract.py`.
- Ruff: exécuter `ruff check .` et réduire progressivement; promouvoir règle par règle quand la dette est à zéro.

## Contrôles à ajouter/renforcer
- Mypy par domaine (commencer par modules extraits), pas de bascule brutale.
- Tests PostgreSQL en CI pour flux DB critiques (déjà amorcé sur audiobook).
- Tests de concurrence sur lifecycle/transfers.
- Seuil couverture basé sur baseline mesurée, pas arbitraire.
- Contrôle imports circulaires / dépendances interdites: `scripts/check_architecture_imports.py`.

## Plan de réduction
1. Mesurer warnings Ruff/mypy/couverture.
2. Corriger par domaine.
3. Bloquer les régressions (ratchet).
