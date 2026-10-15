# Pilotage — Rapport d'audit et d'exécution (Master Prompt, 2026-10-15)

Branche active : `m07-audit-quotas-observability` (contient M06+M07, commits
locaux, aucun push/merge). Convention créée ici : `docs/engineering/`.

## Statuts constatés (code réel + preuves)

| Issue | État réel | Risque | Action |
|---|---|---|---|
| #35 isolation | IMPLEMENTED_UNVERIFIED (M06 sur branche) | P0 | merger après revue, puis preuve pilote |
| #36 autorisation | IMPLEMENTED_UNVERIFIED (M06 sur branche) | P0 | idem |
| #37 upload/commit | IMPLEMENTED_UNVERIFIED (streaming SHA-256, tests offline) | P0 | preuve S3 réelle |
| #38 M2M | IMPLEMENTED_UNVERIFIED (tests offline) | P0 | preuve pilote |
| #39 tests isolement | IMPLEMENTED (offline) | P1 | compléter au fil des correctifs |
| #19 catalogue PG | IMPLEMENTED_UNVERIFIED (parité sans DSN) | P0 | suite parité sur PG jetable |
| #18 sessions/intents | IMPLEMENTED_UNVERIFIED | P1 | preuve pilote |
| #40 quotas/obs | PARTIAL (M07 : usage/health/audit offline ; SSE-S3, backup, bande passante ABSENTS) | P1 | finir sur pilote |
| #41 docs/OpenAPI | VERIFIED offline (garde-fou contrat) | P2 | maintenir |
| #42 bulk | PARTIAL (plan + moteur backoff côté client) | P1 | après #83–#86 |
| #82 audit | EN COURS (ce dossier) | P0 diagnostic | publier `82-transfer-engine-audit.md` |
| #83 machine d'état | PARTIAL (transitions+idempotence offline ; concurrence commit, crash, panne PG non prouvés) | P0 | tests d'intégration ciblés |
| #84 multipart | ABSENT (PUT simple, plafond 5 Gio) | P2 | gate compatibilité SeaweedFS d'abord |
| #85 reprise Range | ABSENT (GET présigné seul, pas de Range) | P2 | gate compatibilité d'abord |
| #86 retry/backoff | PARTIAL (client : backoff+jitter borné testé ; serveur : rien) | P1 | politique serveur + baseline |
| #87 réconciliation | PARTIAL (M06 : purge 502 + `storage_failures` offline ; orphelins, lots bornés, crash : non prouvés) | P0 | intégration S3 réelle |
| #88 benchmarks | ABSENT (aucun harnais) | P2 | après #84/#86 |
| #89 release gate | PARTIAL (matrices partielle, pas de Go/No-Go) | P1 | en fin de phase |

## Doublons / recouvrements

- #84 vs #72 (multipart + reprise par partie, compatibility-gated) : **recouvrement
  fort**. Recommandation : #84 primaire, #72 dépendante à consolider (autorisation
  demandée, rien modifié).
- #37 vs #83 : complémentaires (cycle+limites vs idempotence+concurrence) : garder
  liées, ne pas fusionner.
- #40 vs M07 livré : quotas/usage/health/audit-search faits offline ; reste
  SSE-S3, backup, métriques transfert → garder #40 ouverte sur ce reste.
- #42 vs #63/#64/#85 : bulk = enveloppe ; garder, ordonner après les fondations.

## Graphe de dépendances (chemin critique)

`#82` → `#35/#36/#39` + `#87` + `#19` → `#83` (+`#37/#38` preuves live) →
`#86` → `#85` → `#84` (gate SeaweedFS) → `#88` → `#42` → `#89` → `#10/#11` →
`#13` bilan. `#41` transverse continu.

## Blocages critiques

1. Aucune preuve sur infrastructure réelle (VPS/pilote) : tout le statut
   "UNVERIFIED" en dépend ; aucune action destructrice entreprise ici.
2. M06+M07 non mergés : prérequis à toute suite sur l'autorisation et l'observabilité.
3. Compatibilité SeaweedFS (multipart, Range, presign par partie) inconnue : bloque
   #84/#85 par conception (gate explicite des issues).

## Exécutable immédiatement (sans infra, sans risque)

- [x] #82 : audit probant (ce dossier, docs seuls).
- M06/M07 : revue + merge (décision humaine requise).
- #83 partiel : tests concurrence commit en SQLite ( Reminder: à faire, offline).

## Tâches exigeant l'environnement réel

Preuves S3/pilote (#37,#38,#83,#87), parité PG (#19), SSE-S3/backup (#8,#9,#40),
gates SeaweedFS (#84,#85), benchmarks (#88), Go/No-Go (#10,#11,#89).

## Critères de fin de phase

- Diagnostic : ce rapport + audit #82 publiés, statuts ci-dessus.
- Risques critiques : M06/M07 mergés + régressions vertes + preuve pilote planifiée.
- Contrat transfert : #83 complète offline, #41 synchronisée.
- Fiabilisation : #86 serveur + #85 documentée ou prouvée.
- Gros fichiers : gate #84 tranché (implémenter ou documenter le refus).
- Livraison : #89 avec recommandation GO/NO-GO explicite.

## Suivi M7 (revue pré-merge)

- **M7 (revue)** : les mutations non scopées du dépôt s'appuient sur le
  contrôle de périmètre `get_object` effectué en amont ; tout appelant futur
  doit préserver cette vérification (le dépôt ne la refait pas).
- **M2/M3 (décisions acceptées, documentées sans changement)** :
  - le balayage de réconciliation (`reconcile_pending`) se base sur
    `created_at` avec une fenêtre par défaut de 3600 s, volontairement plus
    conservatrice que la fenêtre d'expiration de commit (410) : documenter,
    ne pas modifier ;
  - `storage_deletes_attempted` compte les suppressions réellement effectuées
    et `storage_failures` le reste : documenter, ne pas renommer.
