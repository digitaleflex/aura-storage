# Baseline de non-régression avant refactorisation (#336)

> Généré le 2026-11-26. Aucun changement fonctionnel.

## Environnement

- Git: `003203e` (origin/main au moment de la baseline)
- Python: 3.14.4
- Pytest: 9.1.1
- OS: Linux (environnement de travail agent)

## Commande exécutée

```bash
AURA_API_ADMIN_PASSWORD=ci-dummy-password \
AURA_S3_ACCESS_KEY=ci-dummy-access-key-1234 \
AURA_S3_SECRET_KEY=ci-dummy-secret-12345678901234567890 \
AURA_S3_ENDPOINT=https://127.0.0.1:9 \
AURA_API_DB=:memory: AURA_COOKIE_SECURE=0 \
.venv/bin/python -m pytest -q
```

## Résultat

- **665 passed, 39 skipped, 9 warnings** en 175.43s.
- Les 39 skips correspondent principalement aux tests nécessitant un DSN PostgreSQL/service externe non configuré dans cet environnement (ex. `AUDIOBOOK_TEST_DSN`, DSN PG dédiés selon tests). Ils doivent être distingués des tests SQLite réellement exécutés.

## OpenAPI / contrat

```bash
...mêmes env vars... pytest tests/test_openapi_contract.py -q
# 8 passed, 8 warnings
```

## Snapshot routes

- `docs/engineering/baseline-routes-2026-11-26.json` — 152 routes (méthode+chemin+handler+ligne) extraites par AST de `api/main.py`.
- Vérification: à comparer à `docs/API-ROUTES-AUDIT.md` et à `tests/test_openapi_contract.py` avant chaque extraction.

## Parcours critiques à protéger

- Auth: login/logout/session/CSRF, public auth, M2M bearer.
- Objets: upload intent, multipart, commit, abort, download/preview intent, delete/restore/purge.
- Partages: object/folder share, public redeem `/s`, `/f`.
- Dossiers/collections/tags.
- Admin: reconcile, integrity, orphans, audit, identities/spaces/apps.
- Portail public: catalogue, progress, bookmarks, playlists, favorites, media grants.
- Import jobs / revisions.

## Lacunes observées / à surveiller

- Couverture réelle non mesurée par un outil de coverage dans cette baseline (peut être ajoutée via `--cov` en CI).
- Tests PG skippés hors environnement PG.
- Concurrence, erreurs réseau S3, transitions d’état partielles et reprise multipart nécessitent des tests ciblés avant extraction.
- Avertissements FastAPI `on_event` deprecation (non bloquants).

## Usage

Avant chaque PR de refactor : relancer la commande baseline, comparer `baseline-routes-2026-11-26.json`, et exécuter `tests/test_openapi_contract.py`.
