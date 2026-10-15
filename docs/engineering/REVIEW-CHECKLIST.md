# Checklist de revue — fusion M06 + M07 + ENG (commit `612a34b`)

Fusion locale sur `main`, **non poussée**. Cocher chaque point avant `git push`.

## 1. Périmètre du merge

- [ ] `git log --oneline main` contient : `472ffac` (M06), `f8e3add` (M07),
      `23d2289` (ENG), `5391a0f` (revue) + merge `612a34b`.
- [ ] `git status` propre (hors `web/dist.bak-*` préexistant, non suivi).
- [ ] Aucun secret dans le diff : `git diff main~1 --stat` relu ; `.env` et
      `config/seaweedfs/s3.json` absents du suivi (`git check-ignore`).

## 2. Code backend (`api/`)

- [ ] `lifecycle.py` : purge → `StorageDeleteError`/502, ligne gardée ; reconcile
      n'expire qu'après suppression effective + `storage_failures`.
- [ ] `audit.py` : whitelist scalaire, verrou append/prune, clamps, `ValueError`
      si rétention < 1 ; portée mono-worker honnête en commentaire.
- [ ] `main.py` : middleware request-ID sans `UnboundLocalError` ; 4 endpoints
      (`audit`, `audit/prune`, `usage`, `health`) sous `ADMIN_READ`/`ADMIN_WRITE`.
- [ ] `authz.py` : Bearer seul (plus de `X-AURA-Key`) ; `_m2m_blocked` sans
      résidu ; CSRF sur les mutations humaines.
- [ ] `db.py` + `db_pg.py` : bucket défaut strict (409 sans défaut) ; `ping`,
      `space_usage`, `stored_bytes` (disponibles uniquement) miroirs.
- [ ] `config.py` : gardes `RuntimeError` (rétention ≥ 1, fenêtres ≥ 1/0).

## 3. Tests (preuves exactes à consigner)

- [ ] Suite complète : `220 passed, 2 skipped` (skips = S3 live, parité PG).
      Commande : `AURA_API_ADMIN_PASSWORD=ci AURA_S3_ACCESS_KEY=ci-1234567890
      AURA_S3_SECRET_KEY=ci-12345678901234567890 AURA_S3_ENDPOINT=https://127.0.0.1:9
      AURA_API_DB=:memory: AURA_COOKIE_SECURE=0 python3 -m pytest tests/ -q`.
- [ ] `test_m06_isolation_matrix.py` (13) : matrice propriétaire/autre
      espace/appli/sans-auth/sans-permission/révoqué/scope + purge 502 +
      reconcile en échec.
- [ ] `test_m07_observability.py` (16) : request-ID, permissions, filtres,
      pagination/clamps, fenêtre `truncated`, attribution threaded, whitelist,
      prune concurrente, hygiène secrets.
- [ ] `test_transfer_engine.py` : commits concurrents convergent (8 threads,
      un digest).
- [ ] `test_openapi_contract.py` : chemins + méthodes synchronisés.
- [ ] `tsc --noEmit` (web) vert.

## 4. Documentation et contrat

- [ ] `docs/openapi.yaml` : 4 routes M07 + purge 502 + 401 admin + notes clamp.
- [ ] `docs/AUTHORIZATION-MATRIX.md` : matrice + section M07 (rétention,
      exception login, purge owner-scopée).
- [ ] `docs/OBSERVABILITY.md` : pagination/rétention, métriques indisponibles,
      validations infra réelle.
- [ ] `docs/engineering/` : rapport de pilotage + audit #82 + suivi revue (M2/M3/M6/M7).
- [ ] Aucune affirmation pilote/S3/PG dans les docs (formulations
      « non validé », « à prouver » présentes).

## 5. Sécurité (relecture explicite)

- [ ] Aucun token/secret/URL présignée dans logs, audit, réponses, diff.
- [ ] Cross-scope → 404 générique, sans `bucket`/`object_key`.
- [ ] `admin:*` ineffectif sur identités service (création 422 + masque).
- [ ] Prune : `admin:write` + CSRF ; lectures obs : `admin:read`.

## 6. Frontend

- [ ] Sections Consommation / Supervision / Journal d'audit affichent des
      valeurs réelles + fraîcheur, sans métrique inventée.
- [ ] `ReconcileResponse.storage_failures` affiché.

## 7. Portes pilote (bloquantes pour données réelles, pas pour le push)

- [ ] SSE-S3, backup/restore indépendant, preuves S3/Parité-PG : **dues**
      (issues #8, #9, #19, #37, #87). Aucun import d'originaux avant.
- [ ] Doublon #84 vs #72 : consolidation proposée, en attente d'autorisation.

## 8. Après revue

- [ ] Push explicite : `git push origin main` (autorisation requise).
- [ ] Issues GitHub : commenter #35/#36/#39/#40/#82/#83 avec liens commits
      (ne rien fermer sans preuve pilote).
