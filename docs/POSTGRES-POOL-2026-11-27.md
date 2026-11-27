# Pool de connexions PostgreSQL partagé (#325)

**Date :** 2026-11-27 · **Périmètre :** catalogue PostgreSQL de l'API (`api/db_pg.py`) ; aucun changement sur les objets ni sur les URLs présignées.

## Décision

**Pool intégré `psycopg_pool.ConnectionPool`, pas PgBouncer.**

La cible est un single-VPS : un proxy de pooling supplémentaire ajouterait un service à exploiter, un point de défaillance et une couche de configuration réseau pour un gain que le pool embarqué fournit déjà. Chaque processus/worker uvicorn possède son propre pool borné ; la somme des connexions est donc `workers × (pool_max + 1)` (une connexion de compatibilité reste pour le bootstrap/les appels raw). PgBouncer redevient pertinent si l'API passe à plusieurs machines ou si le nombre de workers augmente au point de dépasser `max_connections` PostgreSQL — la décision sera alors réécrite ici.

## Configuration

| Variable | Défaut | Rôle |
|---|---:|---|
| `AURA_DB_POOL_MIN` | 2 | Connexions préchauffées au démarrage |
| `AURA_DB_POOL_MAX` | 10 | Plafond de connexions empruntées simultanément |
| `AURA_DB_POOL_TIMEOUT` | 5 s | Délai d'acquisition avant `PoolTimeout` (pas d'attente infinie) |

Validation au démarrage : `1 <= min <= max` et `timeout > 0`. `Repository.pool_metrics()` expose `min`, `max`, `size`, `available`, `waiting`, `acquisitions`, `queued`, `avg_acquire_ms`, `timeouts`, `opens` — sans DSN ni credential, donc journalisable.

## Mesures (base PostgreSQL jetable `aura-audiobook-ci-pg`, 127.0.0.1:55432)

Outil reproductible : `scripts/db-pool-load-test.py`. Le scénario mélange des lectures catalogue concurrentes (`pg_backend_pid()`, même forme que les accès faits pendant upload/commit/génération d'URL) ; il ne modifie aucune ligne.

```
python3 scripts/db-pool-load-test.py '<DSN disposable>' \
  --threads 24 --ops 60 --min 2 --max 10 --timeout 5 --exhaust
```

- **Avant l'implémentation** : une seule connexion psycopg par processus, protégée par `@synchronized` (`api/dblock.py`) : toutes les opérations DB des endpoints sérialisées, aucune métrique d'acquisition.
- **Après** : 24 threads × 60 opérations = **1 440 opérations en 0,49 s (≈2 900 ops/s)**, **0 erreur**, **10 PIDs backend distincts** (exactement `pool_max`), pool monté de 3 à 10 connexions, `avg_acquire_ms=5,13`, `timeouts=0`.
- **Coût d'ouverture** : médiane de 10 connexions psycopg brutes successive = **18,9 ms** ; un emprunt au pool chaud coûte ~5 ms sous charge, et ~0 ms quand une connexion est disponible. Le préchauffage (`min=2`) évite ce coût sur les premières requêtes.
- **Épuisement borné** (scénario `--exhaust`, pool `min=1/max=2`, timeout 0,2 s, 12 threads retenant une connexion 0,5 s) : 2 réussites, 10 `PoolTimeout`, **aucun blocage infini** ; le pool retombe à 2 connexions disponibles et accepte une requête juste après. Le compteur `timeouts` du repository augmente de 10.
- Tests associés : `AURA_TEST_PG_DSN=<DSN> python3 -m pytest tests/test_pg_pool.py tests/test_pg_parity.py -q` → **3 passed**.

## Détails d'implémentation

- Les méthodes chaudes (`_one`, `_all`, `_run`, `_run_many`, `consume_share`, `consume_folder_share`) empruntent une connexion au pool. Les opérations multi-instructions utilisent `_transaction()`, qui épingle **la même connexion** sur le thread pendant la transaction ; les appels imbriqués la réutilisent, donc l'atomicité est préservée.
- `@synchronized` a été retiré du repository PostgreSQL : il sérialisait tout le catalogue et annulait l'intérêt du pool. Le repository SQLite garde son verrou (une seule connexion, par conception).
- `self.conn` reste une connexion dédiée au bootstrap du schéma et aux quelques appelants directs (tests, chemins legacy). Elle n'est pas utilisée par les méthodes ci-dessus, donc les limites du pool restent significatives.
- Les connexions sont rendues au pool après chaque opération ; en cas d'exception elles sont fermées (`putconn(close=True)`) pour ne pas réinjecter un état transactionnel douteux.

## Limites

- Le pool est **par processus**, pas global : avec 4 workers uvicorn et `max=10`, PostgreSQL peut voir jusqu'à 44 connexions (4 × 11). Dimensionner `max_connections` en conséquence ; sinon baisser `AURA_DB_POOL_MAX`.
- `responseHeaderTimeout` (nginx/Traefik), les index composites et les compteurs partagés restent nécessaires : ce chantier ne couvre que les connexions DB.
- La mesure de charge ci-dessus est un proxy des accès catalogue ; elle ne remplace pas un test de production avec les vrais uploads. Le test opt-in `tests/test_pg_pool.py` doit être rejoué sur la stack de recette avant activation.
