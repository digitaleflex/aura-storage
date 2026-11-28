# ADR-0005 — Composition, injection de dépendances et lifecycle

- Statut: Accepté
- Approuvé le: 2026-11-28
- Date: 2026-11-26
- Issue: #332

## Décision

- `create_app()` est le composition root.
- Les dépendances (repo, S3, settings, clock, audit, workers) sont construites explicitement et injectées via FastAPI dependencies ou paramètres de constructeur.
- Pas d’accès global implicite depuis le domaine.
- Startup/shutdown: init DB/S3/worker dans des hooks lifespan explicites; arrêt propre des workers.
- Tests: `create_app(settings_override=..., deps_override=...)` ou overrides FastAPI.

## Règles

- Pas d’effet de bord lourd à l’import de module.
- Un worker/job reçoit des dépendances explicites.
- Config lue via `settings`, pas dispersée.
