# Revue des issues GitHub — 2026-10-18

Revue des 36 issues ouvertes de `digitaleflex/aura-storage` comparées au code de
`main` (`43f44c2`) et au travail des branches préparées le même jour. Rien n'a
été modifié sur GitHub : ce document propose, `scripts/apply-issues-review.sh`
applique (à lancer par un mainteneur, après relecture).

## 1. Constat général

- **Le suivi a pris du retard sur le code.** Plusieurs issues décrivent un
  « état actuel » qui n'est plus vrai (#63 « l'UI n'envoie qu'un seul fichier »,
  alors que la file bornée, la relance et l'upload de dossier existent et sont
  couverts par Playwright). #18 et #19 portent un commentaire « Clôture avec
  preuves » mais sont restées ouvertes.
- **Trois générations d'issues se recouvrent** : la série initiale (#4–#23), la
  série sécurité P0 (#35–#42) et la série Transfer Engine (#82–#90), plus #72.
  Elles disent souvent la même chose avec des mots différents, ce qui rend la
  priorisation et la clôture difficiles.
- **#13 (MASTER) est devenu un document** de 8 000 caractères, mis à jour à la
  main, avec des sections ajoutées en fin de texte. C'est fragile : un
  *milestone* + des labels font le même travail automatiquement.
- **Aucune issue sans preuve pilote ne peut être fermée** selon la règle du
  projet, mais aucune issue ne sépare « fait dans le code » de « validé sur le
  VPS ». Résultat : tout reste ouvert, y compris ce qui est terminé côté code.
- **Hygiène** : 20 issues sans label, aucun milestone, priorités uniquement
  dans les titres (`[P0]`), pas de modèle d'issue.
- **Risques réels absents du suivi** : aucune issue ne couvre le fait que
  SSE-S3 n'était pas appliqué aux uploads (corrigé sur `fix/sse-at-rest`), la
  persistance du journal d'audit, le stockage en clair des sessions, la CI du
  front, ni la livraison par images.

## 2. Règle proposée : séparer « code » et « pilote »

Deux labels de statut, en plus des labels de thème existants :

| Label | Sens |
|---|---|
| `status:code-done` | Critères code + tests remplis sur `main`, preuve en commentaire |
| `status:needs-pilot-proof` | Reste uniquement la preuve sur le VPS réel |

Une issue « code-done + needs-pilot-proof » est rattachée à **une seule** issue
de recette pilote (#10) au lieu de rester ouverte en parallèle. On peut alors
fermer les issues de code avec un lien vers la case correspondante de #10.

## 3. Décision par issue

Légende : **Fermer** (critères remplis, preuve existante) · **Fusionner**
(doublon, fermer en `duplicate` avec lien) · **Mettre à jour** (texte faux ou
incomplet) · **Garder**.

### Infrastructure et exploitation (#4–#11)

| # | Décision | Pourquoi / quoi changer |
|---|---|---|
| #4 #5 #6 #7 | Garder, label `operations` + milestone *Pilote VPS* | Tâches serveur réelles, non vérifiables depuis le dépôt |
| #8 | **Mettre à jour** | Ajouter : SSE-S3 n'est appliqué que si la requête le demande (constat 2026-10-18) ; preuve attendue = `tests/sse-s3-smoke-test.sh` **et** un upload via l'app qui renvoie `ServerSideEncryption=AES256` ; rechiffrement de l'existant (`api.reencrypt`) + `volume.vacuum` |
| #9 | **Mettre à jour** | Pointer vers `feat/offsite-backup` (scripts + test local de bout en bout). Reste : choisir le fournisseur, première sauvegarde réelle, restauration réelle, planification + alerte |
| #10 | **Mettre à jour** | Devient *la* recette pilote unique : y regrouper les « preuves pilote dues » de #18 #19 #21 #35–#40 #63 #64 sous forme de cases |
| #11 | Garder | Dossier Go/No-Go ; dépend de #10 |

### API, données, sécurité (#18–#19, #35–#41)

| # | Décision | Pourquoi / quoi changer |
|---|---|---|
| #18 | **Fermer** | Commentaire de clôture avec preuves du 2026-10-14 (PR #24) ; la preuve pilote passe dans #10 |
| #19 | **Fermer** | Idem (PR #25, 9/9 sur PG + S3 réel) |
| #35 #36 #38 | **Fermer** (`status:code-done`) | M06 livré, 13 tests de matrice, matrice documentée ; seule la preuve pilote reste → case dans #10 |
| #37 | **Fermer** | Critères cochés dans le commentaire du 2026-10-14 ; le reste (multipart) est #72/#84 |
| #39 | **Fermer** une fois `chore/ci-web` + `test/postgres-suite` fusionnées | Critère « une régression d'isolation échoue le pipeline » : vrai sur SQLite aujourd'hui, et sur PostgreSQL avec le job `api-postgres` |
| #40 | **Mettre à jour** | Retirer ce qui est livré (M07). Garder : limiteurs en mémoire (perdus au redémarrage, non partagés entre workers), métriques Prometheus, alertes disque/sauvegarde |
| #41 | Garder | Toujours vrai (README « non validé », API-SPECIFICATION « proposal », dashboard « no public router » contredit par Compose) |
| #22 | **Fusionner** dans #35/#36/#38 | Même périmètre (rôles, identités S3 minimales, audit). Le seul point unique — *une identité S3 par application, pas l'admin* — devient une nouvelle issue (N7) |

### Transferts (#42, #72, #82–#90)

| # | Décision | Pourquoi / quoi changer |
|---|---|---|
| #42 | **Transformer en épopée** | Garder comme parapluie ; remplacer les cases détaillées par des liens vers #72, #82–#88 ; retirer ce qui est fait (clés côté serveur, URLs courtes, commit idempotent) |
| #72 | **Fusionner** avec #84 | Même sujet (multipart + reprise). Garder #72 (le plus précis, avec le gate de compatibilité) et y reporter l'ordonnanceur borné de #84 |
| #82 | **Mettre à jour** | `docs/engineering/82-transfer-engine-audit.md` existe : cocher ce qui est couvert ou fermer |
| #83 | **Mettre à jour** | Une bonne partie est livrée (états, commit idempotent, commits concurrents testés). Recentrer sur ce qui manque : vérification d'intégrité **asynchrone** (voir N5), timeout ambigu, panne PostgreSQL |
| #85 #86 #87 #88 | Garder | Toujours pertinents. #86 : la politique de retry existe déjà dans `web/src/lib/transfer.ts`, préciser ce qui reste (classification des erreurs côté API) |
| #89 | **Fusionner** dans #90 | Deux release gates parallèles ; #90 (checklist globale) doit contenir la section Transfer Engine |
| #90 | Garder | Ajouter une section « Sauvegarde/restauration » et « Chiffrement au repos » |

### Interface (#20–#23, #58, #59, #63–#66)

| # | Décision | Pourquoi / quoi changer |
|---|---|---|
| #20 | **Mettre à jour** | Cocher #62 (fermée) ; les sous-issues font foi |
| #21 | **Mettre à jour** | Hôte réel = `app.aura-storage.eurinhash.com` (pas `fichiers.`) ; routage + HTTPS livrés ; reste : HSTS/CSP (sur `fix/security-hardening`) et preuve pilote |
| #23 | **Fusionner** dans #10 | Recette UI sur le pilote = même recette |
| #58 | **Mettre à jour** | `AdminPage.tsx` (1 600 lignes) et 3 specs Playwright admin existent : lister ce qui manque au lieu de « aucune interface » |
| #59 | Garder, **décision à prendre** | Recommandation : option A (console opérateur, pas de social login) tant qu'aucune plateforme cliente ne demande d'identité utilisateur final dans AURA |
| #63 | **Fermer** | File bornée, progression, annulation, relance ciblée : `transfer.ts`, `upload-queue.spec.ts`, `transfer-engine.spec.ts` |
| #64 | **Fermer** ou réduire | Upload de dossier : `webkitdirectory`, `folder-upload.spec.ts`. Vérifier le cas « 3 niveaux + checksums » demandé, sinon garder pour ce seul test |
| #65 | Garder | Pas d'aperçu dans l'UI. Ajouter : la CSP de `fix/security-hardening` autorise déjà `img-src` vers l'hôte S3 ; il faudra `frame-src`/`object-src` pour le PDF |
| #66 | Garder | La route `restore` n'existe toujours pas côté API |

## 4. Nouvelles issues proposées

Corps complets dans `docs/engineering/issues-2026-10-18/`.

| Id | Titre | Priorité | Branche prête |
|---|---|---|---|
| N1 | [P0][Security] SSE-S3 n'était pas appliqué aux uploads : chiffrer, refuser le clair, rechiffrer l'existant | P0 | `fix/sse-at-rest` |
| N2 | [P0][Security] Sessions hachées, login à temps constant, CSP/HSTS, dashboard filtré, audit persistant | P0 | `fix/security-hardening` |
| N3 | [P1][CI] Build + typage + Playwright du front, image API, suite complète sur PostgreSQL | P1 | `chore/ci-web`, `test/postgres-suite` |
| N4 | [P1][Ops] Livraison par images versionnées (GHCR) et retour arrière en une commande | P1 | — |
| N5 | [P1][Reliability] Vérification d'intégrité asynchrone (worker) au lieu de relire 5 Go dans la requête | P1 | — |
| N6 | [P1][Ops] Supervision : métriques Prometheus, alertes disque, âge de la dernière sauvegarde | P1 | — |
| N7 | [P1][Security] Identités S3 à moindre privilège : l'API et la sauvegarde n'utilisent plus la clé admin | P1 | — |
| N8 | [P2][Maintenance] Découper `ObjectsPage.tsx` (2 900 l.) et `api/main.py` (1 500 l.) | P2 | — |
| N9 | [P2][Decision] Choisir une licence | P2 | — |

## 5. Organisation proposée

- **Milestones** : *M-Sécurité code* (N1, N2, #41), *M-Sauvegarde* (#9, N6),
  *M-Pilote VPS* (#4–#8, #10, #11), *M-Transfer Engine* (#72, #83, #85–#88, #90),
  *M-Console* (#58, #65, #66, #59).
- **Labels de priorité** `P0` `P1` `P2` (au lieu du titre) et de statut
  (`status:code-done`, `status:needs-pilot-proof`, `status:blocked`).
- **#13** devient court : règles non négociables + liens vers les milestones.
  Le registre de session passe dans les PR (déjà le cas en pratique).
- **Modèle d'issue** (`.github/ISSUE_TEMPLATE/task.md`, inclus) : Contexte ·
  État vérifié dans le code (avec chemins) · Travail · Critères code ·
  Critères pilote · Hors périmètre. La séparation code/pilote évite le blocage
  décrit en section 1.
