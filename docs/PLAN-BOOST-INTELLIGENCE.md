# Plan d’exécution — Booster AURA et rendre la plateforme plus intelligente

> **Date :** 2026-11-16  
> **Base d’analyse :** `README.md`, `docs/ETAT-DES-FONCTIONNALITES.md`, `docs/AUDIT-COMPLET-2026-10-24.md`, `docs/ISSUES-AUDIT-2026-11.md`, `docs/OBSERVABILITY.md`, `docs/DECISION-*.md`, `output/STRUCTURED_MAP.md`, `api/main.py`, `docker-compose.yml`.

## 1. Objectif et principes

**Objectif :** faire passer AURA d’un pilote fonctionnel à une plateforme **fiable, sécurisée, observable et “intelligente”** (recherche, automatisation, aide à la décision), sans régression.

**Principes de pilotage**
- **Preuve avant statut** : une capacité n’est “validée” qu’avec un test/log daté (cf. `docs/ETAT-DES-FONCTIONNALITES.md` §9).
- **Fondations d’abord** : clore les gates prod/sécurité avant les fonctionnalités avancées.
- **Lots incrémentaux** : chaque lot livre valeur + critères de validation + rollback clair.
- **Périmètre contrôlé** : distinguer *corrigé dans le code* vs *confirmé en déploiement/VPS* (ETAT §8).

**Légende statut** : Spécifié / Implémenté / Validé (preuve).

## 2. État des fonctionnalités restantes (backlog produit)

| Fonctionnalité | État actuel | Décision proposée | Lot cible |
|---|---|---|---|
| Gates prod P0 (backup/restore, reboot/persistance, e2e VPS réel, parité PG) | Non validé | **À faire en priorité** (bloquant prod) | Lot 0 |
| Confirmation déploiement remédiations S1/S2/A1/D1 | Corrigé code, à confirmer | **À valider au déploiement** | Lot 0–1 |
| Multipart en production (flag OFF, 2 UNKNOWNs gate 4.48) | Implémenté, non validé | **Finaliser & activer progressivement** | Lot 3 |
| Import jobs | API partielle, **sans worker** (`api/main.py:4321`) | **Implémenter le worker** | Lot 3 |
| Révisions de contenu | Schéma+repo, **pas d’API** (`tests/test_revisions.py`) | **Exposer API + UI minimale** | Lot 3 |
| Recherche avancée (FTS/facettes) | Substring `q` uniquement | **Nouvelle capacité “smart”** | Lot 2 |
| Métadonnées enrichies / doublons / PII (détection) | Absent | **Progressif, opt-in** | Lot 2/4 |
| Détection d’anomalies & alerting (audit/usage) | Données présentes, analyse manuelle | **Règles puis scoring** | Lot 4 |
| Quotas par app/identité + limites débit/egress | Quotas espace uniquement | **Étendre le modèle** | Lot 4 |
| FTPS (ISSUE-018) | Spécification seule | **Différé** (après socle stabilisé) | Backlog |
| Intégration OpenBooks (ISSUE-019) | Spécification seule | **Différé** | Backlog |
| Intégration Axiom (ISSUE-020) | Spécification seule | **Différé** | Backlog |
| Better Auth / Google OAuth | Différé (décision) | **Différé** (réactiver si besoin multi-utilisateurs) | Backlog |
| Fonctions transfert avancées (décisions) | Différé | **Évaluer après Lot 3** | Backlog |

## 3. Roadmap par lots

### Lot 0 — Clôture des gates & vérité terrain (Bloquant)
**Objectif :** base éprouvée, preuves exploitables.
- **Tâches**
  - Sauvegarde + **restore indépendant** isolé, vérification SHA-256/intégrité (`scripts/aura-backup.sh`, `docs/BACKUP-RESTORE.md`, runbook).
  - Test persistance après reboot hôte (containers, données, upload/download) avec log daté.
  - E2E **réel** sur VPS (API + front + S3/PG réels) sur parcours critiques : login, upload/commit, download, partage, corbeille, admin de base.
  - Suite backend avec `AURA_TEST_PG_DSN` (lever les 2 skips parité PG) ; consigner résultats.
  - Vérifier au déploiement : identité S3 API dédiée (pas de bootstrap/admin), `AURA_SESSION_TTL` effectif, `Content-Disposition: attachment` sur download, artefact web immuable servi hors worktree (hash vérifié).
- **Modules/fichiers** : `scripts/*backup*`, `scripts/deploy.sh`, `docker-compose.yml`, `.env` (sans secrets committés), `docs/verification-log-*.md`.
- **Critères de validation** : logs datés dans `docs/`, restore concluant, reboot OK, e2e réel vert, parité PG verte.
- **Risque/effort** : Moyen (opérations VPS) ; dépendances infra/humaines.

### Lot 1 — Sécurisation & durcissement plateforme (P0/P1)
**Objectif :** réduire la surface de risque et fiabiliser le runtime.
- **Tâches**
  - Durcissement conteneurs : `user`, `read_only`, `tmpfs`, `cap_drop`, limites CPU/mémoire par service (`docker-compose.yml`).
  - Traefik : ne plus exposer le socket Docker directement (proxy filtré ou provider fichier) ; HSTS/headers complets partout (app, landing, dashboard) ; CSP sans inline fragile.
  - Réseau/confiance : restreindre `AURA_TRUSTED_PROXIES` aux sous-réseaux réels (`api/config.py`, compose/env).
  - Fiabilité service : healthchecks sur `app`, `swagger-ui`, services Seaweed + `depends_on: service_healthy` ; compression et `Cache-Control` immuable sur assets hashés.
  - Hygiène : corriger points signalés (scripts/reconcile, docs obsolètes/régénérer `API-ROUTES-AUDIT.md` depuis code+OpenAPI, routes inconnues 404 propres si pertinent).
- **Validation** : `docker compose config` OK, scan headers, tests de non-régression, vérif qu’aucun privilège excessif ne subsiste.
- **Risque/effort** : Moyen ; peut impacter le démarrage (healthchecks) — rollout progressif.

### Lot 2 — Intelligence “données & recherche” (Quick wins smart)
**Objectif :** rendre le contenu trouvable et exploitable.
- **Tâches**
  - **Recherche full-text** PostgreSQL (FTS/trigrammes) sur `display_name`, tags, métadonnées clés ; facettes (type, taille, date, statut, dossier) ; endpoint dédié + UI recherche/filtres (`api/main.py`, `api/store.py`/requêtes, `web/src`).
  - **Métadonnées enrichies automatiques** (pipeline async) : extraction basique (type MIME fiable, dimensions/durée média), empreintes pour détection de doublons ; stockage en catalogue.
  - **Insights catalogue** : compteurs/tendances (croissance, objets froids, gros consommateurs) exposés pour Dashboard/Admin.
- **Validation** : tests requêtes/pertinence, perf sur jeu de données réaliste, feature flag si nécessaire.
- **Risque/effort** : Moyen ; attention migrations PG et coût d’indexation.

### Lot 3 — Moteurs manquants & robustesse des flux (Cœur produit)
**Objectif :** compléter les capacités partiellement livrées.
- **Tâches**
  - **Worker import-jobs** : consommer les jobs créés par l’API, états/transitions, retries idempotents, observabilité (`api/main.py`, module worker dédié, éventuellement service/process).
  - **Multipart** : lever les UNKNOWNs compat SeaweedFS 4.48 (reclaim disque après abort, complétion gros volumes), activer via flag de façon contrôlée, durcir reprise/retry/TTL.
  - **Révisions de contenu** : API CRUD/lecture des révisions (s’appuyer sur schéma+repo existants), règles de rétention, exposition UI minimale (historique/restauration).
  - **Pipeline de jobs unifié** (option) : mutualiser vérif, AV scan, transcodage/HLS/miniatures avec files/états traçables.
- **Validation** : tests d’intégration flux bout-en-bout, gros fichiers, interruptions/reprises, nettoyage après abort.
- **Risque/effort** : Élevé (I/O, stockage, cas limites).

### Lot 4 — Observabilité intelligente, quotas & garde-fous
**Objectif :** plateforme pilotable et proactive.
- **Tâches**
  - **Anomalies/alertes** sur audit & usage : règles (pics échecs auth, partages/egress anormaux, suppressions massives), seuils configurables, notifications/export (`api/audit.py`, endpoints admin, vues web).
  - **Quotas étendus** : par application/identité et limites de débit/egress ; visibilité et erreurs claires côté UI/API.
  - **Métriques & SRE** : exposition Prometheus/OpenTelemetry, corrélation `X-Request-Id`, SLO/alertes (latence, erreurs, backlog réconciliation/vérif/scrub), conscience capacité SeaweedFS.
  - **Politiques de partage intelligentes** : expiration/contraintes par défaut, détection de liens permissifs.
- **Validation** : jeux de scénarios (bruteforce simulé, egress burst), tableaux de bord admin, non-régression perf.
- **Risque/effort** : Moyen à élevé.

### Lot 5 — UX & collaboration “smart”
**Objectif :** valeur perçue et adoption.
- **Tâches**
  - Dashboard/console enrichis : activité, santé, top consommateurs, transferts en cours, alertes actionnables.
  - Recherche/tri rapides, prévisualisations fiables, gestion globale 401/timeouts/retry UX, exports assainis (CSV), accessibilité.
  - Collaboration : versioning visible, publication/packs médias améliorés, workflows légers d’approbation si besoin.
- **Validation** : tests e2e (mock + réel), accessibilité (axe), retours utilisateurs.
- **Risque/effort** : Moyen.

## 4. Backlog différé (hors séquence immédiate)
- **FTPS** (`docs/ISSUE-018-FTPS-SPEC.md`), **OpenBooks** (`ISSUE-019`), **Axiom** (`ISSUE-020`) : implémenter après stabilisation Lots 0–3 et besoin confirmé.
- **Better Auth / Google OAuth** : réactiver si ouverture multi-utilisateurs/SSO (cf. `docs/DECISION-BETTER-AUTH.md`).
- **Fonctions transfert avancées** : prioriser selon mesures réelles post-pilote (cf. `docs/DECISION-ADVANCED-TRANSFER-FEATURES.md`).

## 5. Ordre d’exécution recommandé (prochaines itérations)

1. **Semaine/itération A (Lot 0)** : produire toutes les preuves VPS (restore, reboot, e2e réel, parité PG) + confirmer remédiations S1/S2/A1/D1 en déploiement.
2. **Itération B (Lot 1)** : durcissement compose/Traefik/proxies/headers/healthchecks/assets.
3. **Itération C (Lot 2 — quick win)** : recherche FTS + facettes (API + UI) derrière feature flag.
4. **Itération D (Lot 3)** : worker import-jobs, puis clôture gate multipart et activation progressive.
5. **Itération E (Lot 3/5)** : API révisions + UI historique minimal.
6. **Itération F (Lot 4)** : règles d’anomalies sur audit + quotas par app/débit + métriques.

## 6. Suivi (gouvernance légère)

- **Tableau de suivi** (à maintenir dans ce fichier ou issue tracker) : Lot | Tâche | Responsable | Statut (Spécifié/Implémenté/Validé) | Preuve (lien log/test/date) | Notes.
- **Definition of Done par lot** : code + tests automatisés pertinents + doc mise à jour + preuve de validation (et log daté pour gates VPS).
- **Revue de lot** : vérifier non-régression sécurité/intégrité et mettre à jour `docs/ETAT-DES-FONCTIONNALITES.md`.

## 7. Quick wins immédiats (fort impact / effort maîtrisé)
1. Recherche FTS PostgreSQL sur le catalogue (valeur utilisateur immédiate).
2. Règles d’alerte simples sur audit/usage (sans ML) + vues Dashboard.
3. Finaliser import-jobs worker (débloque une capacité “à moitié” livrée).
4. Durcissement headers/healthchecks/compression (fiabilité & perf perçues).
5. Confirmer et tracer les correctifs P0 en déploiement réel (crédibilité sécurité).
