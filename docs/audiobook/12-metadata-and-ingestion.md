# 12 — Métadonnées externes et ingestion commune (ebooks + audiobooks)

**Version :** 0.1 — proposition
**Date :** 2026-11-24
**Statut :** spécification, sans code de production ni déploiement. Elle complète les Lots 1 et 2 ; elle ne modifie pas leurs invariants.

## 1. Décision en une page

AURA doit pouvoir accueillir des **livres numériques** et des **livres audio** sans dupliquer la gestion des métadonnées.

- **AURA** reste la couche de stockage et de diffusion des octets.
- Le service métier possède le catalogue, les contributeurs, les droits et les décisions d'accès.
- Les API externes fournissent des **candidats de métadonnées**, jamais une vérité publiée automatiquement.
- **Shelfmark** est un outil interne optionnel d'acquisition. Il ne reçoit aucun accès direct à AURA, à PostgreSQL ou aux utilisateurs.
- Tous les fichiers, qu'ils viennent d'un opérateur, de Shelfmark ou d'un partenaire, passent par le même pipeline de staging, validation et import.
- Les ebooks et audiobooks partagent les métadonnées générales, mais conservent des modèles d'actifs et des lecteurs distincts.

Frontière de référence : [`README.md`](README.md) §2.1 et [`02-domain-model.md`](02-domain-model.md).

---

## 2. Existant et manques

### 2.1 Existant réutilisable

| Brique | État | Réutilisation |
|---|---|---|
| Catalogue `work` / `edition` / `contributor` | Implémenté Lot 1 | Cible de la revue manuelle des candidats |
| Actifs, pistes, chapitres | Implémenté Lot 1 | Ingestion audiobook |
| Droits, contrats, territoires, entitlements | Implémenté Lot 2 | Gate de publication et d'accès |
| `StoragePort` | Lecture playback via AURA | À compléter par un port d'ingestion, sans remplacer la frontière |
| Audit et `request_id` | Implémentés | Tracer recherches, revues et imports |
| `scripts/cover_candidates.py` / `.sh` | Candidats iTunes/Open Library | Référence fonctionnelle à migrer derrière un adaptateur commun |

### 2.2 Manques identifiés

- aucun port `MetadataProvider` commun ;
- aucune table d'identifiants externes ni de provenance des candidats ;
- aucune revue explicite appliquer/refuser/fusionner ;
- `EditionIn.duration_ms` est obligatoire : ce modèle est encore audiobook-centré ;
- `AssetIn.kind` ne décrit pas encore un ebook EPUB/PDF ;
- aucun adaptateur d'ingestion vers l'API Management AURA ;
- aucun lot d'import avec états, reprises et idempotence ;
- aucune intégration Shelfmark, et c'est un non-objectif de ce document.

---

## 3. Frontières de responsabilité

| Composant | Responsable de | Jamais responsable de |
|---|---|---|
| API de métadonnées externes | Rechercher et retourner des données brutes/normalisées | Décider les droits ou publier |
| Service d'agrégation métier | Cache, timeout, fallback, déduplication, score | Écraser une décision éditoriale |
| Administrateur / relecteur | Choisir une œuvre/édition, corriger, valider les droits | Contourner les gates techniques |
| Pipeline d'ingestion | Staging, scan, validation, import AURA, audit | Publier sans droits |
| AURA | Stocker, vérifier et diffuser les octets | Connaître le catalogue éditorial |
| Shelfmark | Acquisition manuelle interne dans un staging | Accéder à AURA ou aux comptes auditeurs |
| Service audiobook | Catalogue, droits, accès, écoute | Lire les tables AURA ou les secrets S3 |

---

## 4. Modèle canonique commun

### 4.1 `MetadataCandidate`

Un candidat est une proposition normalisée, pas une entité du catalogue.

| Champ | Description |
|---|---|
| `kind` | `ebook` ou `audiobook` |
| `provider` | `openlibrary`, `itunes`, `google_books`… |
| `provider_id` | Identifiant chez le fournisseur |
| `title`, `original_title` | Titres proposés |
| `language` | Code langue normalisé |
| `contributors` | Nom, rôle (`author`, `narrator`, `translator`…), position |
| `publisher`, `publication_date` | Données d'édition lorsqu'elles existent |
| `description`, `categories`, `series` | Données éditoriales candidates |
| `identifiers` | ISBN-10/13, ASIN, OLID, ID éditeur… |
| `cover_candidates` | URL, source, dimensions/type si connus, statut de revue |
| `duration_ms`, `narrator` | Optionnels, surtout audiobook ; absents = inconnu, pas zéro |
| `confidence` | Score de correspondance avec une entité locale, pas qualité du fournisseur |
| `fetched_at`, `payload_hash` | Provenance et détection de changement |

Un candidat ne contient jamais :

- un droit de diffusion ;
- un prix ou entitlement ;
- une conclusion de disponibilité commerciale ;
- une clé ou un secret de fournisseur ;
- une URL S3 présignée ;
- un chemin hôte interne.

### 4.2 Identifiants externes

Les identifiants fournisseur sont des attributs, jamais les clés primaires AURA.

Contrainte proposée : unicité de `(provider, id_kind, external_id)` pour une même cible. Une œuvre et une édition ne doivent pas partager le même identifiant externe sans règle explicite.

---

## 5. Port `MetadataProvider`

Interface proposée, indépendante du fournisseur :

```python
class MetadataProvider(Protocol):
    name: str

    def search(self, query: MetadataQuery) -> list[MetadataCandidate]:
        ...

    def lookup(self, identifier: ExternalIdentifier) -> list[MetadataCandidate]:
        ...

    def cover_candidates(self, candidate: MetadataCandidate) -> list[CoverCandidate]:
        ...
```

`MetadataQuery` porte au minimum : texte, langue, type (`ebook`/`audiobook`/`unknown`), ISBN/ASIN éventuel et limites.

Le service d'agrégation applique :

1. validation de la requête ;
2. cache court par `(provider, query_hash)` ;
3. timeout et limite de résultats par fournisseur ;
4. normalisation des langues, dates et contributeurs ;
5. déduplication des candidats ;
6. classement par correspondance ;
7. dégradation propre si un fournisseur est indisponible.

Aucun appel fournisseur ne doit bloquer la lecture du catalogue existant.

---

## 6. Fournisseurs initiaux

| Fournisseur | Priorité | Usage | Limite principale |
|---|---:|---|---|
| **Open Library** | P0 | Œuvres, éditions, auteurs, ISBN, couvertures | Données variables ; CORS navigateur non retenu |
| **iTunes Search** | P0 | Ebooks/audiobooks et pistes de couverture | Conditions Apple et disponibilité par pays |
| **Google Books** | P1 | Descriptions, catégories, dates, identifiants | Quotas et clé/config OAuth |
| **Hardcover** | P2 | Métadonnées riches si le compte le permet | Clé, conditions et périmètre de licence à vérifier |

`public-apis/public-apis` sert d'annuaire de veille. Il n'est pas une dépendance runtime et la présence d'une API dans la liste ne prouve ni son SLA ni ses droits de réutilisation.

Shelfmark utilise également des fournisseurs de métadonnées, mais **sa clé API administrateur ne doit pas devenir un accès métier partagé**. Le service AURA appellera directement les fournisseurs retenus.

---

## 7. Correspondance et déduplication

Ordre de confiance proposé :

1. identifiant externe exact déjà connu ;
2. ISBN-10/ISBN-13 équivalent ou ASIN exact ;
3. titre normalisé + auteur + langue ;
4. indices d'édition : éditeur, date, durée, narrateur, version abrégée/complète ;
5. similarité textuelle, uniquement pour proposer un candidat à revue.

Règles fermes :

- une similarité textuelle seule ne fusionne jamais automatiquement ;
- une ambiguïté reste en `review` ;
- deux narrateurs, langues ou éditions différentes ne sont pas fusionnés ;
- « illustré », « dramatisé », « abrégé », « intégral » et numéro de série sont des indices à préserver ;
- la correction manuelle est auditée et ne change jamais un UUID local ;
- un fichier déjà présent avec le même SHA-256 est signalé comme doublon, pas réimporté silencieusement.

Action de revue proposée : `create`, `link_existing`, `merge_candidate`, `reject`. `merge_candidate` exige une confirmation humaine et un motif.

---

## 8. Pipeline d'ingestion commun

### 8.1 Sources acceptées

- dépôt manuel d'un opérateur ;
- fichier préparé par Shelfmark dans un staging isolé ;
- import partenaire futur, via un adaptateur dédié.

Aucune source ne contourne les étapes suivantes.

### 8.2 États d'un `IngestItem`

```text
received
  → quarantined
  → validating
  → metadata_review
  → rights_review
  → importing
  → completed

received / quarantined / validating → rejected
validating / importing              → retryable_failed
```

Ces états décrivent le **lot d'ingestion**. Ils ne remplacent pas les états d'`Asset` du Lot 1 (`initiated`, `quarantined`, `validating`, `ready`, `rejected`, etc.).

### 8.3 Étapes obligatoires

1. **Réception** dans un répertoire de staging non public.
2. **Identité du fichier** : taille, SHA-256, nom original, source.
3. **Quarantaine et scan** antivirus.
4. **Validation technique** :
   - audiobook : type réel, conteneur, codec, durée et pistes via ffprobe ;
   - ebook : type réel, structure EPUB/PDF, absence de scripts actifs ou pièces dangereuses selon politique ;
   - couverture : MIME réel, taille, dimensions, refus SVG/HTML.
5. **Recherche de métadonnées** et correspondance avec le catalogue.
6. **Revue éditoriale** explicite.
7. **Revue des droits** : contrat/fenêtre/territoire/canal. Une API externe ne prouve jamais un droit.
8. **Import AURA** via l'API Management, avec identité de service dédiée et clé d'idempotence.
9. **Commit et vérification AURA** : taille, SHA-256, SSE et état `available` prouvé.
10. **Création des entités métier** : `Asset`, `Track`, `Chapter` pour l'audio ; modèle ebook à définir séparément.
11. **Publication** uniquement via le gate existant `require_publishable`.
12. **Audit** de chaque transition, refus et reprise.

### 8.4 Idempotence et reprise

Clé proposée : `(source, source_ref, sha256)`.

- deux appels avec la même clé ne créent qu'un seul item ;
- un échec après upload AURA déclenche une réconciliation, pas un second objet anonyme ;
- un checksum différent pour la même source est un conflit à revoir ;
- aucune URL présignée n'est conservée dans les tables d'ingestion ;
- les chemins de staging restent internes et ne sont jamais exposés par l'API.

---

## 9. Modèle de données proposé

Les noms sont indicatifs et doivent être validés avant migration.

### 9.1 `external_identifiers`

`id`, `entity_type`, `entity_id`, `provider`, `id_kind`, `external_id`, `is_primary`, `created_at`.

### 9.2 `metadata_candidates`

`id`, `ingest_item_id` nullable, `provider`, `provider_id`, `kind`, `normalized_json`, `payload_hash`, `fetched_at`, `expires_at`, `status`, `confidence`.

Le payload brut n'est conservé que si nécessaire, avec une durée de rétention définie. Aucun secret ni credential fournisseur n'y est stocké.

### 9.3 `metadata_reviews`

`id`, `candidate_id`, `decision`, `target_entity_type`, `target_entity_id`, `reviewer_id`, `reason`, `created_at`.

### 9.4 `ingest_batches` / `ingest_items`

Lot : source, clé d'idempotence, état, compteurs, dates.
Item : nom original, type déclaré/réel, taille, SHA-256, état, tentative, code d'erreur, métadonnées choisies, cible catalogue, objet AURA.

Aucune cascade SQL entre catalogue, droits et ingestion : les transitions passent par des services et des commandes idempotentes.

---

## 10. API d'administration proposée

Toutes ces routes sont **administratives**, auditées et absentes du domaine public.

| Route | Rôle |
|---|---|
| `POST /api/v1/admin/metadata/search` | Rechercher des candidats sans écrire au catalogue |
| `POST /api/v1/admin/metadata/candidates` | Créer/rafraîchir les candidats d'un item |
| `POST /api/v1/admin/metadata/review` | Appliquer, lier ou refuser un candidat |
| `POST /api/v1/admin/ingestions` | Déclarer un lot depuis une source autorisée |
| `GET /api/v1/admin/ingestions/{id}` | Consulter états, erreurs et progression |
| `POST /api/v1/admin/ingestions/{id}/retry` | Reprendre un échec idempotent |

Interdits :

- URL fournisseur arbitraire fournie par le navigateur ;
- proxy public de recherche métadonnées ;
- endpoint d'import sans authentification ;
- retour de chemins staging, clés API ou URLs S3 présignées ;
- publication implicite après import.

---

## 11. Sécurité et conformité

- clés fournisseurs uniquement côté serveur, via variables d'environnement ou secret manager ;
- HTTPS obligatoire, timeout court, redirections contrôlées ;
- protection SSRF : refus des IP privées, loopback, link-local et métadonnées cloud, y compris après résolution DNS ;
- liste blanche d'hôtes pour les images et les endpoints ;
- limitation de débit et cache par fournisseur ;
- journalisation sans credential, token, URL présignée ou payload sensible ;
- vérification des droits d'image avant publication ;
- vérification juridique des droits de diffusion, indépendante des métadonnées ;
- rétention explicite des payloads bruts et des fichiers rejetés ;
- Shelfmark isolé, sans route publique, sans compte administrateur partagé et sans credential AURA.

---

## 12. Scénarios de défaillance

| Scénario | Comportement attendu |
|---|---|
| Fournisseur indisponible | Cache ou saisie manuelle ; le catalogue reste lisible |
| Deux candidats plausibles | Aucune fusion automatique ; revue requise |
| Couverture invalide ou dangereuse | Refus et couverture typographique locale |
| Fichier corrompu / infecté | Rejet, quarantaine, jamais `ready` |
| Droits absents ou expirés | Import technique possible, publication/diffusion refusée |
| Commit AURA échoué après upload | Reprise idempotente et réconciliation |
| Même SHA-256 déjà présent | Signalement de doublon, pas de copie silencieuse |
| Shelfmark arrêté | Le dépôt manuel continue de fonctionner |
| Changement des métadonnées externes | Nouveau candidat horodaté, jamais écrasement silencieux |

---

## 13. Critères d'acceptation

- [x] Open Library et iTunes Search sont branchés derrière le même port.
- [x] Une panne fournisseur ne bloque ni le catalogue ni l'ingestion manuelle.
- [x] Un identifiant ISBN/ASIN exact est proposé avant la similarité textuelle.
- [x] Une ambiguïté ne peut pas créer ou fusionner une édition sans revue.
- [x] Chaque candidat appliqué conserve fournisseur, identifiant, date et hash.
- [x] Aucun fichier importé n'est publiable sans validation technique et droits actifs.
- [x] Le même SHA-256 importé deux fois ne produit qu'un seul actif.
- [x] Un échec après upload AURA peut être repris sans doublon.
- [x] Les credentials, URLs présignées et chemins internes n'apparaissent ni dans l'API ni dans les logs.
- [x] Les tests utilisent des réponses fournisseurs simulées, sans réseau.
- [x] Un candidat ebook et un candidat audiobook partagent le modèle commun sans imposer `duration_ms` à l'ebook.
- [ ] Shelfmark, s'il est testé, ne reçoit aucun accès AURA/PostgreSQL et écrit uniquement dans le staging.

---

## 14. Découpage de réalisation

### Phase M1 — Métadonnées communes

**Statut :** implémenté le 2026-11-24, sans déploiement ni appel réseau dans les tests.

Livré :

- `audiobook/metadata/` — modèles, normalisation, matching, transport HTTPS et agrégateur ;
- adaptateurs Open Library et iTunes Search ;
- cache TTL borné, timeout et refus des redirections ;
- migration `0007_metadata.sql` : candidats, identifiants externes et revues ;
- routes administrateur de recherche, liste et revue ;
- tests unitaires hors ligne et tests API PostgreSQL conditionnels.

Vérification sur le VPS avec PostgreSQL réel : **64 passés, 0 ignoré** (2026-11-24).

Non livré dans M1 : import AURA, validation technique des fichiers, création automatique d'œuvre/édition, mise à jour des champs du catalogue et outillage ebook. Ces points restent aux phases M2/M4.

### Phase M2 — Ingestion AURA

**Statut :** implémenté le 2026-11-24, sans déploiement ni appel réseau dans les tests.

Livré :

- migration `0008_ingestion.sql` : lots, items d'import et transitions ;
- `audiobook/ingestion/` : validation par magic bytes, SHA-256 streaming,
  hook antivirus optionnel, ffprobe optionnel et chemin de staging confiné ;
- `audiobook/storage.py` : adaptateur d'upload/commit AURA avec
  `Idempotency-Key`, PUT streamé et vérification du SHA-256 renvoyé ;
- service et routes administrateur : déclarer, importer, reprendre, rejeter et
  lister les imports ;
- rattachement optionnel à une édition existante : `Asset`, `Track` et
  `Chapter`, sans publication automatique ;
- tests unitaires hors ligne et tests API PostgreSQL conditionnels.

Vérification sur le VPS avec PostgreSQL réel : **64 passés, 0 ignoré** (2026-11-24).

Non livré dans M2 : publication automatique, import ebook dans le catalogue,
validation EPUB/PDF approfondie, cron de réconciliation et interface d'administration
dédiée. Ces points restent aux phases M4/M5.

### Phase M3 — Shelfmark optionnel

- instance Lite interne ou hôte séparé ;
- staging dédié ;
- test limité à quelques contenus légalement disponibles ;
- import par le pipeline M2, jamais accès direct.

### Phase M4 — Ebooks

**Statut :** fondation implémentée le 2026-11-24, sans lecteur ni interface dédiée.

Livré :

- migration `0009_ebook_support.sql` : `edition.publication_kind`, actifs `ebook` et table `ebook_assets` ;
- les éditions existantes restent des audiobooks ;
- gate de publication différencié : narrator/durée/pistes pour l'audio,EPUB/PDF prêt pour le numérique ;
- validation EPUB via `mimetype`, PDF via magic bytes ;
- import d'un EPUB/PDF dans une édition ebook via le pipeline M2 ;
- route `GET /api/v1/ebooks/{edition_id}/url` après décision d'accès ;
- tests de domaine et API PostgreSQL conditionnels.

Vérification sur le VPS avec PostgreSQL réel : **64 passés, 0 ignoré** (2026-11-24).

Non livré dans cette fondation : lecteur EPUB/PDF, progression de lecture, téléchargement offline, DRM et interface d'administration. Ces points relèvent des lots suivants du dossier audiobook.

### Phase M5 — Réconciliation des imports

**Statut :** base implémentée le 2026-11-24.

Livré :

- reprise bornée des items `retryable_failed` après délai et nombre maximal de tentatives ;
- détection des items restés `importing` au-delà du délai configurable ;
- route admin `POST /api/v1/admin/ingestions/reconcile` ;
- script `scripts/audiobook_reconcile.py` pour une passe cron/systemd ;
- audit de chaque transition et du résumé de passe ;
- aucun publication, suppression ou changement de droit pendant la réconciliation.

Variables : `AUDIOBOOK_INGEST_RETRY_DELAY_SECONDS`,
`AUDIOBOOK_INGEST_RETRY_MAX_ATTEMPTS`, `AUDIOBOOK_INGEST_STALE_IMPORT_SECONDS`.

Vérification sur le VPS avec PostgreSQL réel : **64 passés, 0 ignoré** (2026-11-24).

Non livré : planification cron/systemd sur le VPS, tableau de bord des échecs et alertes.

---

## 15. Décisions encore à confirmer

1. Ordre final des fournisseurs et présence de Google Books/Hardcover au lancement.
2. Durée de conservation des payloads bruts et des fichiers de staging rejetés.
3. Emplacement et permissions du staging sur le VPS ou un hôte séparé.
4. Déploiement ou non de Shelfmark ; son absence ne bloque pas M1/M2.
5. Extension du service `audiobook` aux ebooks ou création d'un contexte `publication` distinct.
6. Politique de validation EPUB/PDF et outil antivirus retenu.

Ces décisions ne remettent pas en cause la frontière : **métadonnées candidates, validation obligatoire, AURA pour les octets, droits décidés par le service métier.**
