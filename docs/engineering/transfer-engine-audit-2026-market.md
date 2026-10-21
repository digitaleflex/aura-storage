# Audit du moteur de transfert AURA — comparaison au standard du marché 2026

**Date :** 2026-10-21 · **Branche :** `main` (ed1d4b6 + modification locale `ObjectsPage.tsx`) · **Source :** `docs/engineering/transfer-engine-audit.md` (52 capacités, 819 lignes), `docs/TRANSFER-ENGINE.md`, `docs/SECURE-BULK-TRANSFERS.md`.

## 1. Résumé exécutif

AURA a un moteur de transfert **solide, sécurisé et bien instrumenté** pour le cas *single-PUT direct navigateur → S3* (≤ 5 GiB, hashing SHA-256 côté serveur, SSE-AES256, idempotence, reprise réseau côté client). C'est **au-dessus de la moyenne** pour un projet de cette taille sur les axes *sécurité/intégrité/isolation*.

Mais il est **en deçà du standard marché 2026** sur les axes *grande taille, reprise, performance* : **pas de multipart, pas de Range, pas de resumable upload, pas de benchmark harness, pas de planification automatique**. Verdict global : **moderne pour un service de fichiers de petite/moyenne taille, pas "à la pointe" pour le transfert massif.**

## 2. Tableau de comparaison marché 2026

| Capacité | Standard marché 2026 (S3-compatible) | AURA | Verdict |
|---|---|---|---|
| Single-PUT signé (Content-Length/Type/SSE) | Attendu | ✅ Vérifié | À niveau |
| Multipart / UploadPart / Complete / Abort | Attendu (AWS S3, SeaweedFS 4.48) | ❌ ABSENT | **Écart majeur** |
| Resumable upload (parties déjà stockées) | Attendu (tus.io, S3 multipart) | ❌ ABSENT (single-PUT repart de zéro) | **Écart majeur** |
| Range GET / téléchargement reprenable | Attendu (HTTP Range, 206) | ❌ ABSENT | **Écart majeur** |
| Hashing SHA-256 côté serveur (streaming) | Recommandé | ✅ Vérifié (1 MiB chunks) | À niveau |
| SSE-S3 / SSE-KMS | Attendu | ✅ AES256 signé + vérifié au commit | À niveau |
| Idempotence (Idempotency-Key) | Bonne pratique | ✅ Vérifiée (replay = même ligne + URL fraîche) | À niveau |
| Intégrité post-publication (S10) | Attendu (object-lock/versioning) | ❌ ABSENT (PUT URL reste valide jusqu'au TTL, commit short-circuit) | **Écart P0** |
| Réconciliation automatique | Attendu (cron/timer) | ❌ ABSENT (route admin uniquement, rien ne la déclenche) | **Écart P0** |
| Nettoyage des orphelins (storage→catalogue) | Attendu | ❌ ABSENT (`/admin/orphans` ne scanne que les rows `available`) | **Écart P0** |
| CAS / comparaison-et-échange sur transitions | Attendu (concurrence) | ❌ ABSENT (`mark_available`/`set_status` sans prédicat de statut) | **Écart P1** |
| Rate limiting / quotas par tenant | Attendu | ❌ ABSENT (seulement cap d'intents `pending`) | Écart P2 |
| AV/quarantaine | Optionnel | ❌ ABSENT (direct `pending→available`) | Écart P3 |
| Compression streaming (zstd) | Optionnel (selon doc projet) | ❌ ABSENT (conserver octets originaux par défaut) | Conforme à la décision projet |
| Frontend state machine (phases, backoff, reconnect) | Bonne pratique | ✅ PARTIAL (25 specs, non exécutés ici) | Au-dessus de la moyenne |
| Benchmarks / baseline | Attendu (mesure avant tuning) | ❌ ABSENT (aucun harness) | **Écart P3** |
| PostgreSQL parity | Attendu | PARTIAL (tests skippés, pas de PG dispo) | À valider |

## 3. Forces (à conserver)

1. **Intégrité vérifiée** : `available` exige un SHA-256 calculé sur l'objet entier + égalité de taille + AES256 au HEAD. Aucun succès fantôme.
2. **Bytes directs navigateur→S3** : FastAPI n'est jamais dans le chemin des octets (scalabilité préservée).
3. **Isolation stricte** : chaque route filtre par espace/propriétaire ; clés/bucket/owner générés côté serveur.
4. **Audit log propre** : aucune URL présignée, aucun secret ; whitelist d'événements.
5. **Idempotence** : double commit sûr, double submit dédupliqué.
6. **Frontend avancé** : phases explicites, classification d'erreurs, backoff jitter, reconnexion auto bornée, annulation backend réelle.

## 4. Lacunes classées par risque (extrait de G1–G11)

| # | Lacune | Sévérité | Effort estimé |
|---|---|---|---|
| G1 | Aucun contrôle d'intégrité post-publication (S10) — PUT URL reste valide, commit short-circuit | P0 | Moyen (révocation capability / versioning) |
| G2 | Aucune réconciliation automatique + aucun balayage inverse | P0 | Moyen (scheduler + reverse sweep) |
| G3 | Contrat de taille reposant uniquement sur le `Content-Length` signé ; `expected_size_bytes` jamais comparé ; timeouts non configurés sur client S3 et proxy app→api (60 s par défaut) | P0 | Faible-Moyen |
| G4 | Check-then-act sans CAS ; races `commit` vs `abort`/`delete` | P1 | Moyen |
| G5 | `failed`/`aborted`/`deleted` terminaux sans chemin de nettoyage automatique | P1 | Faible |
| G6 | Replay peut remettre une URL dont le commit est refusé (expires_at original vs TTL frais) | P1 | Faible |
| G7 | Réconciliateur borné sans curseur | P2 | Faible |
| G8 | Multipart / Range / sémantique des parties sur 4.48 non prouvés | P2 (bloqué par gate #84) | Élevé |
| G9 | Pas de retry/idempotence côté serveur | P2 | Moyen |
| G10 | `SSE_ALGORITHM`/`SSE_HEADER` définis 3 fois dans `s3.py` | P3 | Trivial |
| G11 | Aucun harness de benchmark | P3 | Moyen |

## 5. Ce qu'il faudrait pour être "à la pointe 2026"

Ordre recommandé (coût croissant) :

1. **P0 sécurité/intégrité** : fermer G1 (révocation de la capability PUT après `available`, ou object-lock/versioning SeaweedFS) + G2/G3 (scheduler de réconciliation + comparaison `expected_size_bytes` + timeouts S3/proxy).
2. **P1 concurrence** : CAS sur `mark_available`/`set_status` (G4), nettoyage automatique des statuts terminaux (G5), correction du replay (G6).
3. **P2 performance/grande taille** : gate de compatibilité multipart sur 4.48 (`scripts/seaweedfs-compat-probe.py`), puis implémentation multipart + Range GET + reprise (G8), retry côté serveur (G9).
4. **P3 observabilité** : harness de benchmark (G11), tally CI, PostgreSQL parity réellement exécuté.

## 6. Verdict final

- **À la pointe sur** : sécurité, intégrité, isolation, idempotence, UX de transfert (frontend).
- **Pas à la pointe sur** : grande taille, reprise, performance mesurée, automatisation de la réconciliation.
- **Note** : 27/52 capacités VERIFIED, 8 PARTIAL, 12 ABSENT, 5 UNKNOWN (offline uniquement ; la colonne live reste UNKNOWN car aucun endpoint réel n'a été contacté — conforme à `AGENTS.md`).

**Prochaine action concrète proposée** (sans approval gate, dans le scope repo) : corriger G10 (trivial) et G3 (comparaison `expected_size_bytes` au commit) en TDD, puis ouvrir une PR. Les gates P0 (réconciliation auto, multipart) nécessitent une décision produit et, pour G8, un accès au pilote (approval gate VPS).

## 7. État du dépôt

- Branche `main`, 1 fichier modifié non commité : `web/src/pages/ObjectsPage.tsx` (+22 lignes). À inspecter avant tout commit.
- Aucune modification de code effectuée par cet audit (lecture seule).
