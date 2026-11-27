# AURA Cover Intelligence — audit initial

Statut : **audit en lecture seule**. Aucune couverture, aucun livre et aucune donnée de catalogue n’ont été modifiés pour produire ce rapport.

## 1. Résumé exécutif

AURA possède déjà les briques de base de la récupération de couvertures, mais pas encore de **moteur intelligent de décision**.

Ce qui existe :

- extraction des images intégrées aux fichiers audio ;
- recherche iTunes, Open Library et Google Books (ajout récent) ;
- fichier de revue canonique avec candidats et provenance partielle ;
- page d’administration dédiée `/admin/covers` ;
- endpoints admin protégés par `admin:read` / `admin:write` + CSRF ;
- publication bornée, avec simulation et confirmation explicite ;
- stockage des couvertures dans SeaweedFS via S3, avec SSE ;
- verrous et écritures atomiques sur le fichier de revue.

Ce qui manque pour « AURA Cover Intelligence » :

- score numérique multicritère et seuils configurables ;
- décision automatique avec niveaux de confiance ;
- analyse d’image réelle (dimensions, netteté, ratio, doublons, OCR) ;
- règles éliminatoires automatisées ;
- file de traitement asynchrone dédiée aux couvertures ;
- historique des corrections et protection forte des choix humains ;
- modèles de données séparés (`Book`, `BookCover`, `CoverSource`, `CoverJob`, `CoverReview`) ;
- tableau de bord avec métriques par fournisseur.

**Conclusion :** construire le moteur, pas seulement l’interface. La précision bibliographique doit rester prioritaire sur l’esthétique.

---

## 2. État actuel du catalogue

Mesures relevées sur la base PostgreSQL de production :

| Indicateur | Valeur |
|---|---:|
| Objets audio au total | 206 |
| Livres publiés | 97 |
| Livres publiés avec couverture | 28 |
| Livres publiés sans couverture | 71 |
| Livres sans couverture déjà sondés | 69 |
| Livres dans la revue de couvertures | 69 |
| Livres avec au moins un candidat | 41 |
| Candidats disponibles | 107 |
| Fichiers audio non publiés (`available`) | 69 |
| Fichiers audio `pending` | 24 |
| Fichiers audio `expired` | 16 |

Le portail public n’affiche que les objets publiés. Les nouveaux fichiers téléversés ne reçoivent donc pas de couverture automatiquement : le flux actuel de génération ne traite que les objets publiés.

---

## 3. Inventaire du code existant

### 3.1 API principale (`api/`)

| Fichier | Responsabilité actuelle |
|---|---|
| `api/cover_enrichment.py` | recherche iTunes / Open Library / Google Books, extraction d’artwork intégré, images sœurs, `publish_cover()`, fichier de revue |
| `api/cover_review.py` | validation des URL, fusion des sélections, notation « exact / title / approx », écriture atomique, publication par lot |
| `api/main.py` | endpoints admin `/cover-candidates`, `/covers/select`, `/covers/search`, `/covers/apply`, route publique `/covers/{oid}.jpg` |
| `api/migrations.py` | schéma additif ; colonnes `cover_key`, `cover_probe_at`, `public_slug`, `published_at` sur `objects` |
| `api/import_worker.py`, `api/media_worker.py` | workers existants pour import et médias, mais aucun worker de couverture dédié |

### 3.2 Scripts d’exploitation

| Script | Rôle |
|---|---|
| `scripts/generate_audiobook_covers.py` | extraction locale des couvertures intégrées et images sœurs |
| `scripts/cover_candidates.sh` / `.py` | génération des candidats externes |
| `scripts/apply_cover.sh` | publication d’une couverture choisie manuellement |
| `scripts/apply_cover_candidates.sh` | publication d’un lot validé |
| `scripts/merge_cover_selections.py` | fusion sûre d’un export dans la revue canonique |
| `scripts/render_cover_review.py` | page HTML locale de revue |
| `scripts/refresh_public_library.sh` | cron quotidien d’enrichissement local |
| `scripts/publish_audiobooks.py` | publication manuelle et bornée des livres audio |

### 3.3 Interface

L’administration est une SPA React :

- page dédiée : `web/src/pages/AdminPage.tsx`, export `AdminCoversPage` ;
- route : `/admin/covers` dans `web/src/router.tsx` ;
- entrée latérale : `web/src/components/Layout.tsx` ;
- méthodes API : `web/src/lib/api.ts`.

La page propose galerie, recherche par livre, ISBN optionnel, validation, remplacement et application par lot avec simulation.

### 3.4 Service audiobook séparé

Le dépôt contient également `audiobook/`, un service non intégré au déploiement principal :

- `audiobook/metadata/models.py` : `MetadataCandidate`, `CoverCandidate`, normalisation ISBN, langues ;
- `audiobook/metadata/matching.py` : score déterministe 0–100, ISBN prioritaire ;
- `audiobook/metadata/aggregator.py` : cache et agrégation multi-fournisseurs ;
- `audiobook/migrations/0007_metadata.sql` : `metadata_candidates`, `external_identifiers`, `metadata_reviews` ;
- migrations `0008_ingestion.sql`, `0009_ebook_support.sql`.

Ce service contient déjà une partie de la logique bibliographique recherchée. Il doit être **réutilisé**, pas dupliqué aveuglément dans `api/`.

---

## 4. Fournisseurs actuels

| Fournisseur | État observé | Remarques |
|---|---|---|
| Google Books | intégré, mais HTTP 429 sans clé | clé optionnelle `AURA_GOOGLE_BOOKS_API_KEY` |
| Open Library | fonctionnel, avec erreurs réseau transitoires | ne pas en dépendre exclusivement ; mettre en cache |
| iTunes Search | fonctionnel | source secondaire de repli |
| Artwork intégré | fonctionnel | prioritaire lorsqu’il existe |

Les domaines autorisés pour les images sont actuellement : Open Library, `*.mzstatic.com`, Google Books, `*.googleusercontent.com`, `*.gstatic.com`. Les redirections sont refusées pour la publication, et la taille des téléchargements est bornée.

---

## 5. Stockage

Les couvertures publiées sont enregistrées dans le bucket S3 existant sous :

```text
{object_key}.cover.jpg
```

avec SSE-S3 when required, puis référencées par `objects.cover_key`. La route publique `/covers/{oid}.jpg` génère une URL présignée de courte durée.

Limites actuelles :

- pas de séparation `originals/`, `optimized/`, `pending/` ;
- pas de variantes multiples ;
- pas d’historique des anciennes couvertures ;
- une seule couverture active par objet.

---

## 6. Sécurité et gouvernance déjà en place

- endpoints admin protégés par capacités et CSRF ;
- URL externes validées contre une liste d’hôtes HTTPS ;
- pas de redirections suivies lors du téléchargement de couverture ;
- fichier de revue verrouillé (`flock` / `fcntl`) et écritures atomiques ;
- dry-run par défaut et confirmation explicite pour l’application ;
- livres déjà appliqués non modifiables par une nouvelle sélection ;
- journalisation des actions admin.

---

## 7. Écarts avec le cahier des charges

| Exigence | État | Écart |
|---|---|---|
| Multi-sources | Partiel | iTunes / Open Library / Google Books / intégré ; pas de fournisseurs extensibles via adaptateurs |
| ISBN puis titre+auteur | Partiel | ISBN accepté dans la recherche UI ; pas de hiérarchie de requêtes ni cache |
| Score multicritère | Non | seulement un badge de correspondance textuelle |
| Seuils configurables | Non | aucun seuil, aucune décision automatique |
| Qualité image | Non | redimensionnement uniquement ; pas de mesure de netteté ni de ratio |
| Doublons | Non | déduplication par URL seulement |
| OCR | Non | absent |
| Règles éliminatoires | Partiel | URL invalides et hôtes non autorisés rejetés ; pas de contrôle bibliographique automatique |
| Décision automatique | Non | validation humaine obligatoire |
| Correction manuelle avec historique | Partiel | remplacement possible, mais historique et raison non enregistrés |
| Protection des corrections humaines | Partiel | livre appliqué non résélectionnable, mais pas de statut « corrigé manuellement » |
| Worker asynchrone | Non | aucun `CoverJob` dédié |
| Modèles séparés | Non | `objects.cover_key` uniquement ; service `audiobook/` non intégré |
| Dashboard métriques | Non | absentes |

---

## 8. Architecture proposée

### 8.1 Principe

Créer un composant métier **`api/cover_intelligence/`** dans l’API AURA existante, puis lui brancher :

- les adaptateurs du service `audiobook/metadata/` ;
- le stockage S3 existant ;
- la base PostgreSQL existante ;
- la page admin existante.

Ne pas créer un second service autonome tant que le moteur n’est pas validé sur le catalogue réel.

```text
api/cover_intelligence/
├── providers/        # adaptateurs normalisés Google Books, Open Library, iTunes, embedded
├── discovery/        # stratégie de requêtes, cache, quotas, retry
├── analysis/         # matching bibliographique, validation image, doublons
├── ranking/          # scoring pondéré et règles éliminatoires
├── decision/         # seuils, sélection automatique, états d'incertitude
├── storage/          # download sécurisé, optimisation, clés S3
├── correction/       # historique, raison, protection des choix humains
└── jobs/             # file asynchrone, reprise, idempotence
```

### 8.2 Flux cible

```text
Livre / objet audio
  → profil bibliographique
  → recherches multi-sources
  → candidats normalisés
  → contrôles éliminatoires
  → score explicable sur 100
  → décision selon seuils
  → stockage et association
  → audit + interface de correction
```

### 8.3 Règle fondamentale

L’identité bibliographique prime toujours sur la qualité visuelle.

Une couverture belle mais associée au mauvais auteur, à la mauvaise langue ou à une édition contradictoire doit être rejetée, quel que soit son score technique.

---

## 9. Modèle de données cible

Ajouter de manière additive :

| Table | Rôle |
|---|---|
| `cover_books` | profil bibliographique d’un livre AURA |
| `cover_candidates` | candidats avec source, URL, taille, hash, score, statut |
| `cover_scores` | détail du calcul par critère |
| `cover_decisions` | décision automatique ou humaine, raison, seuil, auteur |
| `cover_jobs` | file asynchrone, tentatives, erreurs, état |
| `cover_history` | anciennes couvertures et restaurations |

`objects.cover_key` reste la référence de la couverture active pour la compatibilité du portail public.

---

## 10. Découpage en issues

### AURA-COVER-001 — Audit et inventaire

**Priorité haute — fondation**

Objectif : figer l’état réel avant toute automatisation.

Critères d’acceptation :

- inventaire des livres publiés et non publiés ;
- identification des couvertures existantes ;
- identification des fichiers avec artwork intégré ;
- détection des doublons ;
- rapport des livres sans couverture ;
- aucune modification destructive.

Dépendances : aucune.

---

### AURA-COVER-002 — Moteur de scoring explicable

Objectif : calculer un score sur 100 avec pondérations configurables.

Critères :

- 35 % correspondance bibliographique ;
- 25 % identité d’édition / ISBN ;
- 20 % qualité technique ;
- 10 % fiabilité source ;
- 10 % cohérence visuelle ;
- règles éliminatoires ;
- détail du score conservé.

Dépendances : AURA-COVER-001.

---

### AURA-COVER-003 — Analyse d’image et doublons

Objectif : valider techniquement les images et détecter les doublons.

Critères :

- dimensions et ratio ;
- intégrité réelle du fichier ;
- hash cryptographique et perceptuel ;
- rejet des images inutilisables ;
- signal de netteté déterministe.

Dépendances : AURA-COVER-002.

---

### AURA-COVER-004 — Décision automatique et seuils

Objectif : sélectionner automatiquement selon des seuils configurables.

Critères :

- ≥ 95 : publication automatique ;
- 88–94 : sélection automatique avec confiance inférieure ;
- 72–87 : sélection prudente ou attente ;
- < 72 : aucune association ;
- arbitrage explicite en cas de scores proches ;
- jamais de mauvaise couverture pour combler un vide.

Dépendances : AURA-COVER-002, AURA-COVER-003.

---

### AURA-COVER-005 — File asynchrone et reprise

Objectif : traiter les livres sans bloquer l’import ni l’API.

Critères :

- états `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `RETRY_SCHEDULED`, `NEEDS_REVIEW`, `NO_MATCH`, `CANCELLED` ;
- idempotence ;
- tentatives limitées et backoff ;
- reprise après interruption ;
- cache des recherches.

Dépendances : AURA-COVER-004.

---

### AURA-COVER-006 — Correction administrative et historique

Objectif : conserver la supervision humaine.

Critères :

- ancienne et nouvelle couverture enregistrées ;
- raison de la correction ;
- source de la nouvelle image ;
- date et auteur ;
- restauration possible ;
- protection des corrections humaines contre les recherches ultérieures.

Dépendances : AURA-COVER-005.

---

### AURA-COVER-007 — Migration progressive du catalogue

Objectif : traiter les livres existants sans risque.

Critères :

- mode simulation ;
- lots bornés ;
- concurrence limitée ;
- reprise ;
- journalisation ;
- rapport final ;
- aucune écrasement de couverture validée sans règle explicite.

Dépendances : AURA-COVER-006.

---

### AURA-COVER-008 — Dashboard et métriques

Objectif : rendre le moteur supervisable.

Critères :

- livres analysés, trouvés, à valider, sans couverture ;
- taux de réussite par fournisseur ;
- recherches échouées ;
- consultations des décisions et scores ;
- actions de relance et d’historique.

Dépendances : AURA-COVER-005.

---

### AURA-COVER-009 — OCR et intelligence visuelle avancée

Objectif : ajouter l’OCR comme signal de confirmation.

Critères :

- texte détecté comparé au titre et à l’auteur ;
- OCR jamais utilisé comme unique source d’identification ;
- coût maîtrisé ;
- désactivable.

Dépendances : AURA-COVER-004.

---

### AURA-COVER-010 — Apprentissage à partir des corrections

Objectif : améliorer les règles à partir des erreurs réelles, sans prétendre à un modèle IA non implémenté.

Critères :

- corrélation entre corrections et fournisseurs ;
- ajustement documenté des poids ;
- jeu de données de référence ;
- mesure de précision, pas seulement du taux de couverture.

Dépendances : AURA-COVER-006, AURA-COVER-007.

---

## 11. Ordre d’exécution recommandé

```text
001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010
```

Le tableau de bord (`008`) ne doit pas être commencé avant que le moteur soit fiable (`004`) et les corrections tracées (`006`).

---

## 12. Risques identifiés

1. **Quotas Google Books** : sans clé API, les requêtes publiques sont limitées. Fournir une clé ou accepter le repli.
2. **Qualité des métadonnées audio** : les noms de fichiers ne sont pas des identités fiables. Prioriser les tags et l’ISBN.
3. **Droits d’image** : la disponibilité via une API ne constitue pas une autorisation de redistribution.
4. **Faux positifs** : une couverture visuellement plausible peut être celle d’une autre édition.
5. **Concurrence** : API et scripts doivent partager le même verrou de revue.
6. **Dérive entre dépôt et déploiement** : plusieurs conteneurs ont été recréés depuis des images ou des répertoires de release différents pendant les essais. Toute phase d’implémentation doit vérifier l’image réellement active.

---

## 13. Décision actuelle

Aucune migration massive, aucune publication automatique et aucune modification destructive ne doivent être lancées avant validation de l’issue **AURA-COVER-001** et du moteur de scoring **AURA-COVER-002** sur un échantillon réel du catalogue.

La priorité est : **précision avant automatisation**.
