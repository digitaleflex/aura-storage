# Catalogue public — filtres et classification

- **Date :** 24 novembre 2026 ; révision 27 novembre 2026 (synonymes locaux)
- **Statut :** implémenté sans migration de base de données

## Filtres disponibles

Le catalogue anonyme et le catalogue connecté proposent désormais :

- recherche texte : titre, auteur, catégorie et thème ;
- auteur ;
- collection ;
- catégorie ;
- thème ;
- langue ;
- format : MP3, M4A/MP4, OGG, WAV, FLAC, AAC, EPUB, PDF ;
- durée minimale et maximale en minutes ;
- tri : titre, auteur, nouveautés, durée.

Les filtres se combinent avec une logique **ET**. Un changement de filtre remet la pagination à zéro. Les options et compteurs sont calculés sur le catalogue complet, avant filtrage.

## Classer les livres

Les catégories, thèmes et langues utilisent des étiquettes réservées dans la fiche privée d'un objet :

| Étiquette | Effet public |
|---|---|
| `categorie-roman` | Catégorie « Roman » |
| `categorie-science` | Catégorie « Science » |
| `theme-histoire` | Thème « Histoire » |
| `theme-intelligence-artificielle` | Thème « Intelligence Artificielle » |
| `langue-fr` | Langue « Français » |
| `langue-en` | Langue « Anglais » |

Règles :

- une étiquette contient au maximum 32 caractères ;
- minuscules, chiffres et tirets uniquement ;
- 20 étiquettes maximum par objet ;
- les autres étiquettes restent privées et ne sont jamais projetées dans le catalogue public ;
- un livre peut avoir plusieurs catégories, plusieurs thèmes et plusieurs langues ;
- la première langue est utilisée comme langue principale dans les métadonnées structurées.

L'éditeur d'étiquettes de la console privée affiche cette convention et propose les catégories éditoriales AURA ainsi que des raccourcis Thème et Langue.

### Taxonomie éditoriale AURA

| Catégorie | Slug | Icône |
|---|---|---|
| Développement personnel | `developpement` | Pousse |
| Finance & entrepreneuriat | `finance` | Courbe |
| Leadership & productivité | `leadership` | Boussole |
| Psychologie & relations | `psychologie` | Cœur |
| Spiritualité & bien-être | `spiritualite` | Soleil |
| Cybersécurité & technologie | `cybersecurite` | Bouclier |
| Littérature & philosophie | `litterature` | Livre |
| Méditation & audio guidé | `meditation` | Lotus |

Les catégories et thèmes sont affichés sous forme de raccourcis avec pictogrammes SVG intégrés, sans dépendance externe. Les libellés complets et les compteurs sont calculés depuis le catalogue publié.

### Classement initial et nouveaux livres

- `scripts/classify_public_catalog.py` propose une catégorie et jusqu'à trois thèmes à partir du titre et du dossier privé.
- Le script est en **dry-run par défaut** et conserve les étiquettes privées.
- Une classification éditoriale existante n'est remplacée que avec `--replace-public-tags`.
- La publication d'un audio via l'API (`PUT /api/v1/objects/{oid}/publication`) ou `scripts/publish_audiobooks.py --apply` ajoute automatiquement les étiquettes publiques manquantes, sans écraser une classification manuelle.

```bash
# Aperçu du classement des livres publiés
docker compose exec -T api python - < scripts/classify_public_catalog.py

# Application initiale (remplace uniquement les facettes publics réservés)
docker compose exec -T api python - --apply --replace-public-tags \
  < scripts/classify_public_catalog.py
```

## Collections

Le filtre **Collection** utilise les packs AURA déjà publiés. Il ne nécessite aucune donnée supplémentaire. Un pack peut servir de sélection éditoriale, de série ou de regroupement thématique ; il ne doit pas être confondu automatiquement avec une catégorie.

## Formats

Le format est déduit du type MIME :

- `audio/mpeg`, `audio/mp3` → MP3 ;
- `audio/mp4`, `audio/x-m4a` → M4A/MP4 ;
- `audio/ogg` → OGG ;
- `audio/wav`, `audio/x-wav` → WAV ;
- `audio/flac` → FLAC ;
- `audio/aac` → AAC ;
- `application/epub+zip` → EPUB ;
- `application/pdf` → PDF.

AURA ne prétend pas distinguer AAC et ALAC à l'intérieur d'un conteneur MP4 sans inspection complémentaire.

## Durées

Les bornes sont exprimées en minutes entières. Une durée inconnue est exclue lorsqu'un filtre de durée est actif. Les bornes explicites de l'URL priment sur celles déduites d'une recherche en langage naturel ; les bornes NLP sont arrondies à la minute avant filtrage pour rester identiques après soumission du formulaire.

Une borne minimale supérieure à la borne maximale affiche une erreur accessible et n'applique pas le filtre.

## URLs

Exemples :

```text
/?categorie=roman&theme=histoire&langue=fr
/?collection=classiques&format=mp3&duree_max=90
/?q=intelligence+artificielle
```

Les pages filtrées ne sont pas indexées et le HTML connecté reste en `private, no-store`.

## Synonymes de recherche locaux

Depuis le 27 novembre 2026, la recherche canonise côté serveur **la requête et le texte indexé**
(titre, auteur, catégorie, thème) avec les mêmes règles : accents/casse ignorés, puis petits groupes
de synonymes (`polar`/`policier`/`suspense` → `thriller`, `IA`/`machine learning` → `intelligence
artificielle`, `fantasy` → `fantastique`, etc., liste complète dans `api/portal_search.py`). Le texte
saisi et l'URL ne sont pas réécrits : seule la correspondance est normalisée.

- Aucun appel réseau ni service tiers : ni requête, ni titre de livre, ni donnée d'auditeur ne sort
  d'AURA. Pas de goûts appris et pas de conversation multi-tours dans la recherche.
- Kill-switch : `AURA_SEARCH_ENRICHMENT=0` désactive la canonisation et retombe sur la recherche par
  mots-clés exacte (après repli des accents).
- Mesure reproductible : `scripts/measure-portal-search.py` → `docs/search-relevance-2026-11-27.json`
  (recall@5 0,722 → 1,000 ; MRR 0,833 → 0,917). Décision détaillée dans
  `docs/RECHERCHE-SEMANTIQUE-LOCALE.md`.

## Limites et suite

- Les taxonomies sont encore des slugs : pas de hiérarchie ni de libellés multilingues. Les synonymes de recherche sont locaux et normalisés (voir ci-dessous) ; ils ne modifient pas les slugs stockés.
- Les genres iTunes ou sujets Open Library ne sont pas publiés automatiquement : une revue éditoriale reste nécessaire.
- Le catalogue est chargé puis filtré en mémoire. Pour un très grand volume, filtres et pagination devront être déplacés en base.
- Une future table `object_facets` pourra remplacer les étiquettes réservées si les catégories deviennent un modèle éditorial complet.

## Validation

- Suite Python complète : **711 tests réussis, 41 ignorés** (suite locale du 2026-11-27 ; suite PostgreSQL opt-in : 750 réussis, 2 ignorés).
- Tests frontend unitaires : **104 réussis**.
- Lint frontend : aucune erreur, 13 avertissements préexistants.
- `git diff --check` : réussi.
- Tests e2e Playwright ciblés : **3 scénarios réussis** pour le dialogue d'ajout à une liste (`web/e2e/public-playlist-dialog.spec.ts`), avec les bibliothèques Chromium isolées sous `/tmp/opencode/pwlibs`.
