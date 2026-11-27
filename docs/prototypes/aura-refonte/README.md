# AURA — Refonte UX/UI · prototype haute fidélité

Prototype statique autonome, **également intégré au portail de production** :
le design system a été appliqué à `api/public_ui.py`, `api/public_book.py`,
`api/portal_assets/portal.css` et `api/main.py` (polices locales + `font-src` dans
la CSP), sans modifier le comportement (auth, facettes, lecteur, progression).

**Ouvrir** `index.html` dans un navigateur pour parcourir les maquettes. Aucun
serveur, aucune dépendance réseau : polices, couvertures et scripts sont locaux.

## Intégration au portail réel

- `api/portal_assets/portal.css` : tokens de la refonte + couche de composants
  (les sélecteurs historiques sont conservés, les scripts et les tests restent valides).
- `api/portal_assets/{instrument-serif.ttf, plus-jakarta-sans-*.woff2}` : polices
  servies en local ; `api/public_ui._ASSET_TYPES` et `_portal_csp()` mis à jour.
- `api/public_ui.py` : `site_header()`, `mobile_nav()`, `site_footer()`, hero
  éditorial avec les vraies couvertures, recherche principale, catégories issues
  des facets, réordonnancement des rayons (découverte avant reprise), cartes avec
  disponibilité et action « Écouter ».
- `api/public_book.py` : accueil public et page livre adoptent la même coquille.
- La bibliothèque s'ouvre désormais **en grille** (`vue` par défaut = `grille`) ;
  les vues liste et immersive restent accessibles, et le test de contrat a été
  adapté en conséquence.
- Validation : **112 tests** des suites portail/facettes passent ; captures réelles
  desktop/tablette/mobile du portail généré (aucune erreur console, aucun
  débordement horizontal, aucun avertissement de contraste).

## 1. Étoile polaire

> **Une bibliothèque éditée : chaque livre est un objet désirable, chaque écran
> respire, et l'écoute commence en un geste.**

La direction était déjà largement fixée par le brief (ivoire/crème, typographie
éditoriale, couvertures originales, ambiance calme, bleu nuit, nuances naturelles).
Pas de exploration de trois directions : le travail a consisté à pousser cette
direction jusqu'à un système complet et à l'appliquer aux six livrables.

**Pourquoi ça ne ressemble ni à Spotify, ni à Netflix, ni à Audible :** pas de
bandeau rouge/orange d'action, pas de rail « tendance », pas de carte gradient, pas
de vignette saturationnée. Le produit se présente comme une librairie : papier,
encre, couvertures, silence autour. L'action « Écouter » est un lien souligné ou un
bouton bleu nuit discret — jamais un appel à la consommation.

## 2. Livrables

| # | Écran | Fichier | Capture de preuve |
| --- | --- | --- | --- |
| — | Sommaire du prototype | `index.html` | — |
| 1 | Accueil — Desktop | `01-accueil-desktop.html` | `evidence/final/01-accueil-desktop/page.png` |
| 2 | Accueil — Mobile | `02-accueil-mobile.html` | `evidence/final/02-accueil-mobile/page.png` |
| 3 | Bibliothèque complète | `03-bibliotheque.html` | `evidence/final/03-bibliotheque/page.png` |
| 4 | Détail d'un livre audio | `04-livre-detail.html` | `evidence/final/04-livre-detail/page.png` |
| 5 | Lecteur audio | `05-lecteur.html` | `evidence/final/05-lecteur/page.png` |
| 6 | Recherche & filtres | `06-recherche-etats.html` | `evidence/final/06-recherche-etats/{resultats,vide,chargement,erreur}.png` |
| DS | Système de design | `design-system.html` | `evidence/final/design-system/page.png` |

Les quatre états de recherche s'ouvrent aussi directement via `?state=resultats`,
`?state=vide`, `?state=chargement`, `?state=erreur`. Ajouter `&q=un_terme` remplit
le champ et les échos de requête. `?reveal=all` affiche toutes les sections sans
attendre le défilement (utile pour les captures pleine page).

## 3. Ordre de la page d'accueil

Respecté à la lettre, sur desktop comme sur mobile :

1. en-tête et identité AURA (marque-livre + wordmark espacé) ;
2. hero éditorial — « Des histoires qui vous suivent. » ;
3. barre de recherche principale avec suggestions de requêtes naturelles ;
4. catégories, filtres, tri et mode d'affichage ;
5. « À découvrir » — sélection éditoriale + quatre titres ;
6. « Reprendre l'écoute » — trois livres en cours avec progression calculée ;
7. « La bibliothèque » — grille complète ;
8. pied de page minimal.

La carte éditoriale est **dans** la section « À découvrir », pas insérée entre la
reprise et la bibliothèque, pour ne pas casser l'ordre demandé.

## 4. Système de design

- **Couleurs.** Papier `#F7F4ED`, papier haut `#FBF9F4`, sable `#E6DDCE` ;
  encre nuit `#142438` pour les titres et les actions ; accents rares : terre cuite
  `#9C5F42`, ocre `#885F26` (aussi couleur de focus), sauge `#5E735F`. La page
  `design-system.html` donne les douze tokens avec leur rôle.
- **Typographie.** Deux familles seulement : Instrument Serif pour les titres et
  la citation, Plus Jakarta Sans pour l'interface. Échelle 82 / 42 / 21 / 16 / 13 /
  11 px. Le corps et les métadonnées ne descendent jamais sous 13 px ; seules les
  étiquettes en majuscules espacées (« BIBLIOTHÈQUE AUDIO ») restent à 11 px.
- **Rythme.** Échelle unique 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 px. Grille
  4 colonnes desktop / 3 tablette / 2 mobile, container 1 240 px.
- **Composants.** Boutons (primaire, contour, discret, désactivé), liens, pastilles
  de disponibilité, catégories, champ de recherche, carte livre, carte de reprise,
  progression, filtres actifs, pagination, états, commandes du lecteur. Tous les
  états sont dessinés, y compris le désactivé et l'erreur.
- **Règles.** Une seule accent par écran ; couverture 2:3 à coins presque carrés ;
  ombre diffuse ; pas d'émoji (icônes SVG tracées) ; pas de dégradé décoratif.

## 5. Carte livre

Chaque carte contient : couverture originale, titre (serif), auteur, durée audio,
catégorie, pastille de disponibilité (`Disponible`, `Extrait gratuit`, `Premium`,
`Bientôt`), action « Écouter », favori, et ligne de progression quand c'est pertinent.
Le temps restant des cartes de reprise est **calculé** à partir de la durée et du
pourcentage, pas saisi à la main. Les cartes restent larges (≥ 160 px de couverture
sur mobile) et les textes secondaires sont à 13 px.

## 6. Responsive

- **Desktop ≥ 1 101 px** : 4 colonnes, barre haute complète.
- **Tablette 561–1 100 px** : 3 colonnes, barre haute conservée, hero en une colonne.
- **Mobile ≤ 560 px** : 2 colonnes, barre basse à cinq entrées, bouton « Écouter »
  visible en permanent sur la couverture, recherche accessible depuis l'icône du header.

Le menu « hamburger » ouvre un panneau de navigation fonctionnel. La navigation
par catégories, le tri, la bascule grille/liste, les favoris et les onglets d'états
sont interactifs. Le bouton « Écouter » ouvre la barre miniature du lecteur pour
montrer la continuité entre catalogue et écoute. Ces interactions sont simulées :
aucun flux audio réel, aucun appel API.

## 7. Périmètre — ce qui n'est pas fait

- Le **prototype** reste autonome et n'appelle aucun backend : ses interactions
  sont simulées. Le portail réel, lui, utilise le catalogue, l'authentification,
  la progression serveur et le lecteur `player.js` existants — inchangés.
- Les 16 titres, voix, durées, résumés et couvertures du **prototype** sont des
  données illustratives (`build_covers.py`, `build.py`). Le portail affiche les
  vraies couvertures du catalogue (`/covers/{id}.jpg`).
- Quelques liens de la maquette restent des stubs (par exemple « Profil » → système
  de design) : ils indiquent une destination sans prétendre à une page finale.
- Les panneaux latéraux du lecteur (chapitres, file, marque-pages) sont présentés
  en ligne dans la vue d'écoute, pas comme des tiroirs superposés ; le design
  system et le lecteur réel pourront converger lors de l'intégration.

## 8. Validation

- **Captures réelles** dans un Chromium headless, à 1440×900 (desktop), 390×844
  (mobile) et 820×1100 (tablette). Chaque capture : aucun erreur console, aucun
  débordement horizontal, aucune image cassée.
- **Contraste** corrigé après le premier passage : l'ocre est passé de `#A98145`
  (3,2:1) à `#885F26` (5,2:1), le gris secondaire et les textes du lecteur ont
  été renforcés. Aucun avertissement de lisibilité ne subsiste.
- **Mouvement** : trois gestes retenus — entrée du hero (montée + fondu), révélation
  des sections au défilement (IntersectionObserver, désactivé si
  `prefers-reduced-motion`), retour au survol des cartes. La sonde `motion-probe`
  détecte bien les trois ; voir `evidence/proof-home/`.
- **Revue indépendante** : une première revue en aveugle a noté **7/10** et listé
  13 points. Les écarts de données (filtres, résultats de recherche, progression
  du lecteur, temps de reprise), la typographie mobile, la navigation tablette,
  l'ARIA des onglets et la cohérence des libellés ont été corrigés. La revue de
  vérification a conclu à **9/10** ; les points restants sont des stubs de
  prototype ou des choix éditoriaux assumés.
- **Texte** : aucune phrase purement décorative ajoutée. La mention explicite
  « données illustratives » reste dans le pied de page et dans ce README pour ne
  pas faire croire à un catalogue réel. Les sur-titres en majuscules sont conservés :
  c'est une convention de catalogue éditorial (kickers), pas un remplissage.

## 9. Notes d'environnement

- Chromium du cache Playwright nécessite `LD_LIBRARY_PATH=/tmp/opencode/pwlibs/root/usr/lib/x86_64-linux-gnu`
  et `FONTCONFIG_FILE=/tmp/opencode/pwlibs/fonts.conf`, plus `--no-sandbox`
  (wrapper `CHROME_PATH` utilisé pour les captures).
- `ffmpeg` n'est pas installé : `motion-entry-end.jpg` n'a pas pu être produit,
  l'outil de capture l'a signalé dans `evidence/proof-home/report.json`. Les trois
  autres frames d'entrée et la sonde de mouvement sont disponibles.
- La capture `--full` avec `?reveal=all` évite que les sections hors écran restent
  transparentes et évite le décalage du header collant provoqué par les défilements
  de la sonde.

## 10. Régénérer

```bash
cd docs/prototypes/aura-refonte
python3 build_covers.py   # couvertures SVG
python3 build.py          # 8 fichiers HTML
```

Les styles vivent dans `assets/aura.css`, les interactions dans `assets/app.js`.
Toute modification de contenu ou de structure se fait dans `build.py`, puis on
relance `python3 build.py` : c'est ce qui garantit la cohérence des six écrans.
