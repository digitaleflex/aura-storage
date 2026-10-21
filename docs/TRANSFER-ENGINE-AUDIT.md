# Audit formel du moteur de transfert (ENG-01)

## Périmètre
Audit probant de l'implémentation actuelle (`api/main.py`, `api/lifecycle.py`, `api/storage_reconcile.py`, `api/transfer.py`) par rapport aux invariants documentés dans `docs/TRANSFER-ENGINE.md` et `docs/SECURE-BULK-TRANSFERS.md`.

## Capacités et statut

| Capacité | Statut | Preuve |
|---|---|---|
| Upload simple (single PUT) | Implémenté, testé localement | `tests/test_transfer_basic.py` |
| Upload multipart (part-level resume) | Implémenté derrière `AURA_MULTIPART_ENABLED` | `tests/test_multipart_*` |
| Commit idempotent | Implémenté | `tests/test_two_phase_purge.py` |
| Réconciliation pending/terminal | Implémenté | `api/lifecycle.py` |
| Purge deux phases | Implémenté, testé | `tests/test_two_phase_purge.py` (5/5) |
| Download reprenable (Range) | Implémenté | `api/main.py` download-intent |
| Retry/backoff | Implémenté côté client | `web/src/lib/transfer` |
| Benchmarks | Harness présent | `scripts/bench_transfer.py` |
| PostgreSQL parity réelle | Non exécuté (besoin `AURA_TEST_PG_DSN`) | — |
| E2E crypto (AES-GCM) | Planifié (ENG-07) | — |
| CDC déduplication | Planifié (ENG-07) | — |
| Object Lock / WORM | Planifié (ENG-07) | — |

## Invariants vérifiés
- Pas de suppression de référence catalogue après échec S3 (M06) : OK.
- Réconciliation idempotente : à vérifier (tests concurrents à ajouter).
- Résultats ambigus réconciliables : partiellement (abort multipart idempotent).

## Écarts identifiés
1. `api/lifecycle.py` utilise `limit=500` par défaut sans pagination stable documentée.
2. Pas de verrouillage distribué pour les sweeps concurrents.
3. PostgreSQL parity non exécutée (tests SQLite uniquement).

## Actions recommandées
- Ajouter des tests de concurrence (workers parallèles) sur `reconcile_pending`/`reconcile_terminal`.
- Exécuter la suite avec `AURA_TEST_PG_DSN` en CI.
- Documenter les résultats ambigus (S3 delete returning 204 vs 404).

## Références
- `docs/TRANSFER-ENGINE.md`, `docs/SECURE-BULK-TRANSFERS.md`, `docs/MULTIPART-UPLOAD-PLAN.md`.
EOF
echo done