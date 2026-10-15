# Registre de validation — AURA Storage (2026-10-15, commit `294a63a`)

Suite complète : **220 passed, 2 skipped** (`pytest tests/ -q`, 91 s ;
skips = round-trip S3 live + parité PG, infra réelle requise).
Commande exacte § Phase 11. Branche `main`, worktree propre (hors
`web/dist.bak-*` non suivi préexistant).

## Phase 0 — Inventaire et audit (#82) : VALIDÉ

- HEAD `294a63a`, branches locales `m06-authz-isolation`,
  `m07-audit-quotas-observability` (fusionnées) ; distantes non touchées.
- Roadmap #13 + issues #18–#42, #82–#89 lues ; doublons (#84/#72) et graphe au
  rapport de pilotage (`docs/engineering/00-steering-report.md`).
- Versions épinglées : Python 3.14.4, FastAPI 0.143.1, boto3 1.43.113,
  psycopg 3.3.6, `traefik:v3.7.14`, `chrislusf/seaweedfs:4.48`,
  `postgres:17.9` (`.env.example`, jamais commité en `.env`).
- Audit probant : `docs/engineering/82-transfer-engine-audit.md` (statuts
  VERIFIED/PARTIAL/ABSENT avec références code/tests).
- Multipart/reprise/SSE-S3/Range/sauvegarde : déclarés non fonctionnels —
  aucune affirmation contraire dans les docs.

## Phase 1 — Sécurité et isolation (#35–#39) : VALIDÉ (offline)

- Sessions (expiration, invalidation logout), CSRF mutations :
  `api/authz.py`, `api/db.py:122` ; tests `test_security_isolation.py:254`,
  `test_api.py:183`.
- Refus par défaut : `authorize(scope)` partout ; garde-fou
  `test_every_sensitive_route_denies_unauthenticated`.
- Isolation 2 espaces : liste/lecture/download/commit/delete/upload →
  `test_cross_space_objects_are_invisible`, matrice M06 (13 tests).
- IDs devinés : 404 sans oracle (`_object_scope`, `api/main.py`).
- M2M : création 422 sur `admin:*`, masque `effective_scopes`, expiration,
  rotation/révocation (`test_security_isolation.py:169,214,233,269,291`).
- Secrets : jamais dans logs/réponses (tests dédiés, dont M06/M07).
- Débit : limiteurs login+M2M **mémoire process, perdus au redémarrage** —
  noté, acceptable pilote mono-worker, à redessiner si multi-processus.
- CORS : **écart** — aucun middleware CORS dans l'API (relève du proxy
  Traefik/nginx) ; en-têtes nosniff/DENY, cookies HttpOnly+SameSite=Strict,
  `secure` selon env.
- Erreurs génériques, coordonnées stockage exclues (`_object_public`).
- Bloquant release : aucune fuite inter-espace connue sur le périmètre testé.

## Phase 2 — Cohérence PG/S3 (#87, #19) : VALIDÉ (offline), PARTIEL (live)

- États et transitions : `pending/available/deleted/expired/failed/aborted`.
- Échec S3 → référence gardée (purge 502, `test_m06…`) ; reconcile :
  échec → `pending` + `storage_failures` (tests M06).
- Interruptions S3→commit, expirés, doublons (`Idempotency-Key`),
  8 commits concurrents → un digest (`test_transfer_engine.py`).
- Orphelins S3↔catalogue, lots bornés, crash worker : **non prouvés** (live requis).

## Phase 3 — Contrat API (#18, #37, #38, #41) : VALIDÉ (offline)

- `test_openapi_contract.py` (chemins+méthodes+résumés+2xx) vert ; 4 routes
  M07 documentées ; dérives 401/clamp corrigées et testées.
- Auth de chaque endpoint : matrice `AUTHORIZATION-MATRIX.md` 7/7 vérifiée.
- Limites, idempotence, checksum, TTL présignés documentés ; exemples sans secrets.

## Phase 4 — Machine d'état (#83) : PARTIEL

- Transitions invalides refusées, commit idempotent, SHA-256/taille serveur,
  expiration/abandon/timeout : tests offline verts.
- Manque : intégration PG/S3, panne PG, redémarrage — **BLOQUÉ (infra)**.

## Phase 5 — Reprise (#85) : ABSENT → BLOQUÉ

- Aucun Range/206/416/ETag côté API (`download-intent` = GET présigné seul) ;
  aucune reprise côté web. Gate SeaweedFS 4.48 à trancher sur pilote.

## Phase 6 — Retry (#86) : PARTIEL

- Client web : classification + backoff exponentiel+jitter borné + concurrence
  (défaut 3, adaptative), tests (`transfer-engine.spec.ts`, `test_transfer_engine.py`).
- Serveur : **ABSENT** (pas de `Retry-After`, pas de politique) — à spécifier.

## Phase 7 — Multipart (#84) : ABSENT → BLOQUÉ

- Aucun `CreateMultipartUpload`/partie/scheduler ; plafond 5 Gio assumé en
  attendant le gate de compatibilité. Doublon #72 à consolider (autorisation due).

## Phase 8 — Quotas/observabilité (#40) : PARTIEL

- Usage réel + limites + `measured_at`, health 4 composants, audit
  search/prune/rétention 90 j : 16 tests M07 verts ; admin lecture seule vérifiée.
- Quotas par espace non imposés (choix assumé, plafonds techniques seuls) ;
  SSE-S3, backup, métriques transfert : absents.

## Phase 9 — Sauvegarde/exploitation : BLOQUÉ (infra)

Backup PG/S3, restauration isolée, RPO/RTO, parcours pilote #10 : non exécutés.

## Phase 10 — Benchmarks (#88) : ABSENT

Aucun harnais ; sans objet avant #84/#86.

## Phase 11 — Release gate (#89) : PARTIEL — **NO-GO**

- Bloquantes non validées ; CI locale verte hors infra ; migrations non
  rejouées ici ; OpenAPI conforme au réel observé offline ; aucun secret committé.
- SHA candidat : `294a63a`. Commande suite : `AURA_API_ADMIN_PASSWORD=ci
  AURA_S3_ACCESS_KEY=ci-1234567890 AURA_S3_SECRET_KEY=ci-12345678901234567890
  AURA_S3_ENDPOINT=https://127.0.0.1:9 AURA_API_DB=:memory:
  AURA_COOKIE_SECURE=0 .venv/bin/python -m pytest tests/ -q` →
  **220 passed, 2 skipped**.
- Décision : **NO-GO** (preuves pilote dues). Merge/push uniquement sur
  autorisation explicite (fusion locale `612a34b` faite, non poussée).

## Ordre d'exécution — statut

#82 ✅ · #35–#39 ✅(offline) · #87 partiel · #83 partiel · #85 absent ·
#86 partiel · #84 absent · #40 partiel · #88 absent · #89 partiel/NO-GO ·
#9/#10/#11 bloqués.
