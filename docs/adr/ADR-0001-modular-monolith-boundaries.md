# ADR-0001 — Frontières d’architecture du monolithe modulaire AURA

- Statut: Accepté
- Approuvé le: 2026-11-28
- Date: 2026-11-26
- Issues: #337, #329
- Portée: backend API AURA (`api/`), sans changement applicatif

## Contexte

`api/main.py` concentre routes, schémas, auth, portail, objets, médias, admin, import, révisions. Des modules spécialisés existent déjà (`authz`, `store`, `s3`, `lifecycle`, `transfer`, `reconciler`, `verifier`, `scrubber`, etc.). Le refactor doit réduire le couplage sans introduire de microservices par défaut.

## Décision

Adopter un **monolithe modulaire orienté domaines**, avec ports/adaptateurs uniquement aux frontières utiles, et un **composition root** explicite.

## Principes

1. **Domaine propriétaire** : règles, états et invariants ont un propriétaire.
2. **Dépendances dirigées** : HTTP -> application -> domaine; infrastructure implémente les ports. Pas d’imports domaine->FastAPI/SQL/boto3.
3. **Composition explicite** : `create_app()` assemble dépendances; `api.main:app` reste compatible.
4. **Contrats stables** : schémas HTTP, jobs, événements et accès DB inter-domaines sont explicites.
5. **Évolution incrémentale** : extractions petites, réversibles, couvertes par tests/OpenAPI.

## Domaines initiaux (à valider avec le code)

| Domaine | Responsabilité | Invariants propriétaires | Dépendances autorisées |
|---|---|---|---|
| auth/session | login, session, CSRF, M2M, public auth | session valide, CSRF, scope, rate limit | users/sessions repo, crypto, config |
| objects/transfers | objets, intents, multipart, commit/abort, download/preview | état objet, ownership/space, checksum, transitions | S3 port, object repo, audit |
| media/catalogue public | publication, portail, grants, HLS/covers, progress | published+available, grants signés/courts, no-store | objects read models, S3/public store |
| folders/shares | dossiers, partages objet/dossier | ACL espace, token hashé, révocation/expiry | repo, audit |
| collections/tags | collections, tags | cohérence membership, visibilité | repo |
| admin/ops | reconcile, integrity, orphans, audit, identities/spaces | privilèges admin, audit append-only | repos, workers, S3 |
| import/revisions | import jobs, révisions | idempotence job, versioning/rétention | repo, S3, workers |

## Règles de dépendances

- `api/http/*` ou routeurs: parsing/validation HTTP, authz dependency, mapping erreurs. Pas de SQL.
- `api/application/*`: cas d’usage, transactions, orchestration.
- `api/domain/*`: entités/valeurs/règles/invariants, sans I/O.
- `api/infrastructure/*`: SQLite/Postgres, S3, horloge, fichiers.
- Inter-domaine: appeler un service applicatif ou un port; pas de requête SQL sur tables d’un autre domaine.

## Données et transactions

- **Propriété** : une table a un domaine propriétaire; les autres utilisent une API/lecture dédiée.
- **Transactions** : locales à un domaine quand possible. Multi-table cross-domaine = cas d’usage explicite avec ordre et idempotence.
- **SQLite/Postgres** : conserver le double backend tant que nécessaire; toute requête nouvelle doit être compatible ou isolée derrière un adaptateur. Les différences (placeholders, upsert, JSON, locks) sont absorbées par le repo/port.
- **Idempotence** : endpoints mutables critiques (commit, abort, share redeem, jobs, webhooks futurs) doivent accepter la répétition sans effet secondaire supplémentaire.

## Jobs/workers

- Rester en process/background worker simple tant que volume/latence acceptable.
- Passer à job explicite si: durée > requête HTTP, retry nécessaire, reprise après crash, ou besoin d’observabilité/idempotence forte.
- Tout job porte: id, type, état, tentative, erreur, timestamps, corrélation.

## Critères d’extraction service (futur, non par défaut)

N’extraire un service séparé que si au moins un critère mesuré est atteint:
- besoin de scaling indépendant prouvé;
- isolation de panne/sécurité nécessaire;
- cycle de release réellement indépendant;
- contrainte de latence/ressource incompatible.
Sinon, garder le module dans le monolithe.

## Conséquences

- Plus de structure et de discipline d’imports.
- Migration progressive: pas de big bang.
- Nécessite contrats OpenAPI/tests de non-régression à chaque PR.
