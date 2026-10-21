# #82 — Audit probant du moteur de transfert (ENG-01)

> **État au 2026-10-20.** Cette synthèse courte est **conservée** (règle du dépôt : en cas
> d'arbitrage éditorial, on garde les deux fichiers). L'audit étendu, la matrice de
> transitions, l'analyse d'échecs et la classification par capacité sont désormais dans
> [`transfer-engine-audit.md`](transfer-engine-audit.md) ; la compatibilité multipart
> mesurée sur le tag épinglé est dans
> [`multipart-compat-4.48.md`](multipart-compat-4.48.md). Aucune section de ce fichier n'a
> été supprimée.

Méthode : chaque constat renvoie à du code ou à un test. Statuts :
`VERIFIED` (observé + preuve pertinente), `IMPLEMENTED_UNVERIFIED` (code
présent, comportement non validé hors mocks), `PARTIAL`, `ABSENT`.
Rien hors ligne ne prouve la compatibilité SeaweedFS.

## Chaîne upload (traçage)

`POST /api/v1/objects/upload-intents` (`api/main.py:upload_intent`) →
politique serveur (`api/transfer.py:validate_upload_policy`) → clé
serveur `aura/<space>/<acteur>/<uuid>`, bucket de l'espace → PUT présigné
(`api/s3.py:presigned_put`, `ContentLength` signé, TTL 900 s) →
`POST …/commit` : `head_object`, `stream_sha256` sans tout charger
(`api/s3.py:stream_sha256`), `mark_available` → `GET …/download-intent`
(GET présigné TTL 900 s).

## Matrice des capacités

| Capacité | Statut | Preuve |
|---|---|---|
| Intent persistée avant réponse | VERIFIED (offline) | `create_pending_object` avant `presigned_put` ; `test_api.py`, `test_m06_isolation_matrix.py` |
| Clé/bucket côté serveur, `object_key`/`owner_id`/`space_id` refusés | VERIFIED (offline) | `extra="forbid"` ; `test_client_cannot_choose_object_key_or_owner` |
| Politique type/taille/vide | VERIFIED (offline) | `validate_upload_policy` ; `test_transfer_engine.py` |
| Idempotence `Idempotency-Key` + replay | VERIFIED (offline) | `get_pending_by_idempotency` ; tests double submit |
| Commit idempotent (répété → available) | VERIFIED (offline) | branche `available` ; tests |
| Refus commit aborté/expiré/supprimé | VERIFIED (offline) | 409/410 ; tests |
| Vérification taille + SHA-256 avant `available` | VERIFIED (offline) | `mark_available` après hash ; `test_commit_streaming.py` |
| Expiration intent + grâce 300 s | VERIFIED (offline) | `intent_grace_s` ; tests |
| Isolation espace/propriétaire, 404 sans oracle | VERIFIED (offline) | `_object_scope` sur toutes les routes ; `test_security_isolation.py`, matrice M06 (13 tests) |
| Scopes service vs `human=True` dossiers | VERIFIED (offline) | `api/authz.py` ; tests confusion M06 |
| Purge : échec S3 → 502, référence gardée | VERIFIED (offline) | `StorageDeleteError` ; `test_m06…purge_storage_failure` |
| Reconcile : échec S3 → `pending` + `storage_failures` | VERIFIED (offline) | `api/lifecycle.py` ; tests M06 |
| Soft delete (référence gardée avant purge) | VERIFIED (offline) | statut `deleted` ; `test_soft_delete_and_purge` |
| Backoff+jitter borné côté client | VERIFIED (offline) | `web/src/lib/transfer.ts:backoffDelay/classifyError` ; tests moteur |
| Audit sans secrets/URL, request ID, recherche/filtres/pagination/rétention | VERIFIED (offline) | `api/audit.py` ; 10 tests M07 |
| Usage octets vérifiés + limites + `measured_at` | VERIFIED (offline) | `space_usage`/`stored_bytes` ; tests M07 |
| Health api/db/S3/disque + erreurs récentes | VERIFIED (offline) | `/admin/health` ; tests M07 (dégradé honnête offline) |
| Contrat OpenAPI synchronisé | VERIFIED (offline) | `test_openapi_contract.py` (chemins+méthodes) |
| Commits concurrents convergents | PARTIAL | aucune épreuve de concurrence commit/commit observée (`test_db_concurrency.py` existe : périmètre à vérifier) |
| Panne PG / crash worker / redémarrage | PARTIAL | abort best-effort + reconcile documentés ; pas de test crash observé |
| Orphelins S3↔catalogue, lots bornés, grâce avant nettoyage destructeur | PARTIAL | balayage `pending` seul ; pas de détection d'orphelins ni de pagination |
| Multipart / reprise par partie | ABSENT | PUT simple seul, plafond 5 Gio (`AURA_MAX_OBJECT_BYTES`) |
| Reprise Range côté serveur | ABSENT | GET présigné seul, aucune gestion `Range`/`Content-Range`/`ETag` |
| Politique retry serveur | ABSENT | rien côté API ; seul le client web réessaie |
| Benchmarks | ABSENT | aucun harnais |
| Preuve SeaweedFS réelle (tout le ci-dessus en live) | ABSENT | `tests/s3-smoke-test.sh`, `sse-s3-smoke-test.sh` non exécutés ici |
| SSE-S3, backup/restore, DNS/TLS/VPS | ABSENT (ici) | issues #4–#11, non touchées |

## Analyse des échecs

- **Crash après PUT S3, avant commit** : intent reste `pending`, reconcile
  l'expire après grâce ; pas de perte de référence. Échec S3 au reconcile :
  reste `pending` (prouvé offline).
- **Timeout ambigu commit** : re-commit idempotent si `available`, 409/410
  sinon ; double-submit couvert par `Idempotency-Key`.
- **Commit concurrent au nettoyage** : reconcile ne traite que `pending` ;
  `commit` sur ligne expirée → 410. Concurrence commit/commit non éprouvée.
- **URL expirée** : commit → 410 après grâce ; téléchargement : pas de
  renouvellement automatique observé (renouveler = nouvelle intention).
- **Divergence PG/S3** : pas de transaction distribuée ; ordre purge =
  S3-puis-ligne (sûr), reconcile = S3-puis-`expired` (sûr). Orphelins
  (objet S3 sans ligne, ligne sans objet hors `pending`) : non détectés.
- **Version SeaweedFS épinglée** : images via variables d'environnement
  (`docker-compose.yml`, `${SEAWEEDFS_IMAGE:?…}`) ; valeur effective non
  résolue ici (`.env` non lu) → compatibilité multipart/Range à trancher
  sur le pilote, jamais par la documentation AWS.

## Invariants de sûreté / vivacité

Sûreté : jamais d'`available` sans hash vérifié ; jamais de suppression de
référence sur échec S3 ; jamais de secret/URL dans l'audit ; isolement par
404. Vivacité : grâce d'intention, replay idempotent, reconcile réessayable,
retry client borné. Limite : sans pilote, la vivacité réelle (S3, PG, réseau)
n'est pas prouvée.

## Lacunes ordonnées (vers #83, #86, #87, #84, #85, #88)

1. Concurrence commit/commit + panne PG + crash (tests d'intégration).
2. Détection orphelins + reconcile borné/paginé + preuve S3 réelle.
3. Politique retry serveur + classification d'erreurs partagée client/serveur.
4. Gates SeaweedFS multipart/Range sur version épinglée.
5. Harnais benchmark baseline avant tout tuning.
