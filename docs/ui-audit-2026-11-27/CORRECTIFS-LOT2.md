# Correctifs lot 2 — portail public AURA

**Date :** 27 novembre 2026  
**Référence audit :** [`AUDIT-UI-PORTAIL.md`](AUDIT-UI-PORTAIL.md)  
**Lot précédent :** [`CORRECTIFS-LOT1.md`](CORRECTIFS-LOT1.md)  
**Suite :** plusieurs points ci-dessous ont été traités dans [`CORRECTIFS-LOT3.md`](CORRECTIFS-LOT3.md) (extrait custom, libellés lecteur, carrousels, rayons).  
**Tests :** `101 passed` (`test_public_portal`, `test_public_portal_a11y`, `test_public_classification`, `test_cover_jacket`).

---

## 1. Ce qui a été corrigé

### Contenu des jaquettes

- `fallback_cover_inner()` n’invente plus d’auteur : si l’auteur est absent, la ligne `cover-author` n’est plus rendue.
- `carousel-author`, `track-author`, `book-card-author` et l’auteur de la carte de reprise sont omis quand la donnée est vide.
- « Livre audio » n’est donc plus affiché comme un nom de personne. Le kicker « LIVRE AUDIO » reste la seule mention du format.
- Le libellé de la section de reprise devient « Vos autres lectures » : il n’est plus dupliqué avec l’eyebrow « REPRENDRE L’ÉCOUTE » de la carte. Le lien de découverte pointe vers la carte `#resume-card`.

### Structure des pages et accessibilité

- `<title>` est maintenant dans `<head>` pour la connexion, le profil et le catalogue (les pages vitrine et livre l’étaient déjà).
- La page de connexion a un seul `<main id="main">` qui englobe l’intro et le panneau d’accès : le lien d’évitement a une cible réelle.
- Un test de non-régression vérifie ces deux points (`test_titles_stay_in_head_and_login_has_one_main_target`).

### Identité PWA et favicon

- `meta theme-color` : `#F7F4ED` (fond ivoire réel) au lieu de `#F8F6F1`.
- `manifest.webmanifest` : `background_color: #F7F4ED`, `theme_color: #142438`.
- `icon.svg` : fond `#142438`, trait `#D6B67F` (laiton clair, lisible sur l’encre).
- `icon-192.png`, `icon-512.png` et `icon-maskable-512.png` régénérés depuis le SVG (maskable plein fond, marque dans la zone sûre).

### Pied de page

- Suppression des liens de remplissage « À propos », « Accessibilité », « Confidentialité », « Contact » qui pointaient tous vers `/` ou `/profil`.
- Le pied de page ne garde que des destinations réelles : « La collection » → `/#tous`, puis « Se connecter » pour un visiteur, ou « Mon profil » + « Déconnexion » pour un connecté.

### Hiérarchie des pages utilitaires

- « Mon profil », les confirmations de connexion et les pages de message utilisent un `h1` de 38–52 px au lieu du 74,88 px du hero.
- La fiche livre et l’accueil conservent leur grand titrage éditorial.

### Plancher typographique

- Métadonnées à 13 px : auteurs de carrousel, catégories de cartes, catégories de piste, temps de chapitre, temps/auteur/statut du lecteur, labels de filtres.
- Sur-titres en majuscules à 11 px ; navigation mobile à 12 px.
- Kicker de jaquette à 11 px, auteur de jaquette à 13 px. Sur la petite carte de reprise (96 px), kicker et auteur sont masqués : le titre reste seul, sans micro-texte.

### Profil

- Les quatre statistiques ne sont plus des cartes bordées dans une carte bordée : elles sont posées en grille sous un simple filet.

### Fiche livre

- La grande jaquette n’est plus un cadre vide : le bloc kicker / titre / auteur est centré verticalement, avec un titre à 2 rem et un monogramme en filigrane. La composition reste minimale mais a un point focal.

### Icônes

- Le cœur des favoris est un SVG (contour au repos, plein quand actif) ; `favorites.js` réinjecte le même SVG au clic.
- Le bouton « ajouter à une liste » utilise un `+` SVG.
- Le lecteur utilise des SVG pour précédent/suivant, chapitre précédent/suivant, lecture/pause et fermeture. `player.js` bascule entre les SVG lecture et pause.
- Les glyphes `♥/♡`, `⏮/⏭`, `«/»`, `×` et `▶/⏸` disparaissent des contrôles concernés.
- Le seek de l’extrait natif reçoit `accent-color: var(--bronze)` (le lecteur reste natif, voir « reste ouvert »).

---

## 2. Avant / après

| Point | Avant | Après |
|---|---|---|
| Auteur absent | « Livre audio » affiché comme auteur | Aucune ligne auteur |
| Reprise | « Reprendre l’écoute » deux fois | Carte « Reprendre l’écoute » + section « Vos autres lectures » |
| `<title>` | Après `<body>` sur connexion/profil/catalogue | Dans `<head>` |
| Connexion | Skip link sans cible `#main` | `<main id="main">` englobant les deux colonnes |
| PWA | Fond #F8F6F1, encre #1D2B39, or #D3A560 | #F7F4ED, #142438, #D6B67F |
| Pied de page | 5 liens de remplissage | 2–3 destinations réelles |
| Profil | H1 74,88 px, stats en cartes imbriquées | H1 52 px, stats sous un filet |
| Fiche livre | Jaquette vide, titre en bas | Bloc centré, titre 2 rem |
| Métadonnées | 12 px / 8,32 px | 13 px / 11 px |
| Icônes | Glyphes Unicode | SVG pour favoris, transport, fermeture |

**Captures après lot 2 :** [`evidence-after-lot2/`](evidence-after-lot2/) (12 écrans).

---

## 3. Ce qui reste ouvert

- **Deux lecteurs audio** : l’extrait de la fiche livre est toujours un `<audio controls>` natif ; seul son accent a été réchauffé. Le lecteur complet reste custom.
- **Palette des jaquettes** : quatre teintes pastel cohérentes et contrastées, mais la variante « jaquettes profondes et sémantiques » reste une décision de direction.
- **Échelle de rayons** : 2/3/8/10/12/14/16/999 px subsistent au lieu de 4/8/14/22.
- **Flèches de carrousel** : pas d’état désactivé aux extrémités.
- **Duplication de titre** : le titre reste sur la jaquette et sous la carte ; c’est un choix de composition, pas un doublon accidentel.
- **Libellés du lecteur** : « Off » en anglais, « File » au lieu de « File d’attente », « Premium » statique qui ressemble à un bouton.
- **Revue indépendante après lot 2** : non refaite ; vérifications par rendu Chromium, styles calculés et tests.

---

## 4. Vérification

```text
101 passed in 24,97s
```

Pages rendues et inspectées à 1440×900 et 390×844 : accueil, filtres ouverts, catalogue, lecteur mobile, lecteur plein écran, fiche livre, connexion, profil, message.

Les 404 visibles dans les captures (`/covers`, `/sw.js`, `/api/public/*`, `/m/x.mp3`) sont des artefacts du serveur statique local d’audit, pas des défauts du portail.
