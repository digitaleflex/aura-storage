# Catalogue public — filtres et classification

- **Date :** 24 novembre 2026
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

L'éditeur d'étiquettes de la console privée affiche cette convention et propose des boutons de classification rapide : Roman, Science, Informatique, Histoire, Intelligence artificielle, Français et Anglais.

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

## Limites et suite

- Les taxonomies sont encore des slugs : pas de hiérarchie, de synonymes ni de libellés multilingues.
- Les genres iTunes ou sujets Open Library ne sont pas publiés automatiquement : une revue éditoriale reste nécessaire.
- Le catalogue est chargé puis filtré en mémoire. Pour un très grand volume, filtres et pagination devront être déplacés en base.
- Une future table `object_facets` pourra remplacer les étiquettes réservées si les catégories deviennent un modèle éditorial complet.

## Validation

- Suite Python complète : **700 tests réussis, 39 ignorés**.
- Tests frontend unitaires : **104 réussis**.
- Lint frontend : aucune erreur, 13 avertissements préexistants.
- `git diff --check` : réussi.
- Capture visuelle Playwright : non exécutée, car les bibliothèques système Chromium sont toujours absentes (`libatk`, `libgbm`, `libasound`, etc.).
