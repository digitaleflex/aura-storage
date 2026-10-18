## Contexte
La CI ne teste que l'API sur SQLite et la configuration. Le front (typage, build, Playwright) et l'image Docker de l'API ne sont jamais construits en CI ; `deploy.sh` les construit directement sur le serveur. La production tourne sur PostgreSQL, mais la suite n'y est jamais exécutée en entier.

## Travail
- [x] `chore/ci-web` : workflow `web.yml` — `npm run build` (tsc + vite), suite Playwright contre une API locale (SQLite, S3 factice), build + démarrage de l'image API. Corrige 2 assertions Playwright cassées depuis l'encart « Espace utilisé » (56/56 en local).
- [x] `test/postgres-suite` : job `api-postgres` (service `postgres:17.9`), suite complète avec `AURA_API_BACKEND=postgres` + tests de parité. 5 tests échouaient en mode PostgreSQL sur `main` (helpers SQLite-only) ; corrigés.

## Critères
- [ ] Les deux workflows verts sur la PR.
- [ ] Rendre les jobs `web`, `api-image` et `api-postgres` obligatoires dans la protection de `main`.
