# Audit UI/UX — portail public AURA

**Date :** 27 novembre 2026  
**Périmètre :** portail public (accueil anonyme, connexion, fiche livre, catalogue connecté, lecteur, profil).  
**Hors périmètre :** console d’administration React (`web/src`), qui possède son propre design system sombre/ambre.  
**Mode :** audit en lecture seule — aucun fichier d’interface n’a été modifié.

**Preuves :** captures desktop 1440×900 et mobile 390×844 dans [`evidence/`](evidence/).  
**Méthode :** revue du code (`api/public_ui.py`, `api/public_book.py`, `api/portal_assets/portal.css`), rendu Chromium, styles calculés, calcul de contraste WCAG 2.1, comparaison avec le design system déclaré (`docs/prototypes/aura-refonte/README.md`, `docs/PUBLIC-PORTAL-UI.md`, `docs/BRAND-IDENTITY.md`).

---

## 1. Verdict

La direction éditoriale est claire, reconnaissable et adaptée au produit : ivoire, encre nuit, bronze, serif éditorial, couvertures 2:3, ton calme. Le problème n’est pas le concept, mais **l’exécution** : deux couches CSS superposées, deux serifs de titre en pratique (Instrument Serif et Georgia), une palette de jaquettes qui introduit cinq familles de couleurs pastel, et plusieurs contrôles qui annoncent une action sans en avoir. Deux défauts sont bloquants sur mobile (lecteur recouvert par la navigation, contrôles morts). Le reste est une série d’écarts entre le design system déclaré et le rendu réel, corrigeables par priorité.

Bilan : **2 bloquants, 8 majeurs, 11 mineurs.**

**Priorité recommandée :** (1) lecteur mobile + contrôles morts, (2) unification typographique, (3) contraste et harmonie des jaquettes, (4) formulaire de filtres, (5) nettoyage de la cascade CSS.

---

## 2. Synthèse priorisée

| # | Sévérité | Problème | Preuve |
|---|---|---|---|
| B1 | **Bloquant** | Sur mobile, la barre de navigation basse recouvre toute la rangée d’options du lecteur (vitesse, sommeil, volume, chapitres, file, agrandir, fermer). | `06-lecteur-mobile.png`, `11-annotations-lecteur-mobile.png` |
| B2 | **Bloquant** | Plusieurs contrôles sont morts ou trompeurs : hamburger desktop/mobile, icône recherche, icône favoris, suggestions « En ce moment », liens de navigation tous identiques. | `01`, `02`, `05` |
| M1 | Majeur | Trois traitements typographiques pour le titre principal : Instrument Serif 74,88 px (accueil), Georgia 66,24 px (livre), Georgia 64 px (connexion). Les sous-titres de profil sont aussi en Georgia. | `01`, `07`, `08`, `09` |
| M2 | Majeur | Les jaquettes pastel cassent l’harmonie et le contraste : 3 des 5 teintes échouent AA sur le titre/auteur. | `04`, `05` |
| M3 | Majeur | Le formulaire de filtres est structurellement cassé sur desktop (labels détachés des champs, bouton orphelin) et diffère complètement entre accueil anonyme et catalogue connecté. | `03`, `05` |
| M4 | Majeur | Le collage du hero se chevauche : la note « Le catalogue » recouvre la jaquette de droite ; sur mobile, le titre de la jaquette de gauche est coupé. | `01`, `02`, `10` |
| M5 | Majeur | Contenu dupliqué : titre/auteur répétés sur la jaquette et sous la carte ; « Livre audio » sert d’auteur quand l’auteur manque. | `04`, `05`, `07` |
| M6 | Majeur | Hiérarchie des actions inversée : le CTA principal (Google) est un bouton blanc bordé, moins visible que les puces et boutons encre. | `01`, `08` |
| M7 | Majeur | Dérive du design system : 2 blocs de tokens, 170 sélecteurs redéclarés, 94 couleurs littérales, 13 rayons, 74 tailles de police, 23 ombres, 4 specs de focus. | `portal.css` |
| M8 | Majeur | Navigation active incohérente : « Accueil » actif sur desktop, « Découvrir » actif sur mobile, pour la même page ; la page livre fait pareil ; le profil n’a aucun actif desktop. | `01`, `02`, `07` |
| m1 | Mineur | Deux lecteurs audio : `<audio>` natif pour l’extrait, lecteur custom sombre pour la lecture complète. | `05`, `07` |
| m2 | Mineur | Iconographie mixte : SVG pour la navigation, glyphes Unicode pour favoris, transport, fermeture, retour. | `05`, `06`, `09` |
| m3 | Mineur | Métadonnées PWA/icône hors palette : `theme-color` #F8F6F1, manifest #1D2B39, icône or #D3A560. | `manifest.webmanifest`, `icon.svg` |
| m4 | Mineur | Monogramme de jaquette incohérent : haut-droite dans les carrousels, bas-droite dans les grilles/fiches, masqué dans le lecteur ; taille 54,4 px, opacité 0,13. | `04`, `07` |
| m5 | Mineur | « Reprendre l’écoute » est répété dans la carte de reprise puis immédiatement comme titre de rayon. | `05` (`catalog-zones/page-resume.png`) |
| m6 | Mineur | Pied de page de remplissage : « À propos », « La collection », « Contact » pointent tous vers `/` ; « Accessibilité » et « Confidentialité » vers `/profil`. | `01`, `05` |
| m7 | Mineur | Titres surdimensionnés sur les pages utilitaires : 74,88 px pour « Mon profil » et les confirmations, alors que la tâche est administrative. | `09` |
| m8 | Mineur | Plancher typographique non tenu : métadonnées à 12 px, « LIVRE AUDIO » à 8,32 px, alors que le design system promet 13 px (11 px pour les sur-titres). | `04`, `05` |
| m9 | Mineur | Trois formes de boutons : Google 10 px, primaire 999 px, filtres 10 px ; rayons 2/3/8/10/12/14/16/999 au lieu de l’échelle 4/8/14/22. | `01`, `03`, `07` |
| m10 | Mineur | Cartes imbriquées dans le profil (statistiques dans une carte). | `09` |
| m11 | Mineur | La jaquette de la fiche livre est un grand rectangle presque vide : titre confiné en bas, monogramme à 13 % d’opacité, aucun point focal sur 380×570. | `07` |

---

## 3. Lecture de la palette et de l’harmonie

### La base est bonne

| Rôle | Valeur | Contraste sur `--bg` #F7F4ED |
|---|---|---|
| Fond ivoire | `#F7F4ED` | — |
| Surface papier | `#FBF9F4` | — |
| Encre | `#142438` | 14,28:1 |
| Texte | `#26313D` | 12,56:1 sur surface |
| Secondaire | `#5F6A78` | 5,01:1 |
| Doux | `#66717F` | 4,52:1 (limite) |
| Bronze | `#885F26` | 5,15:1 |
| Terre cuite | `#9C5F42` | 4,63:1 |
| Sauge | `#5E735F` | — (accent rare) |
| Erreur | `#93493F` | 5,85:1 |

Le socle ivoire/encre/bronze est cohérent, chaleureux et lisible. `--soft` à 4,52:1 passe AA de justesse sur le fond ivoire, mais tombe à 4,15:1 sur `--bg-deep` #F0EAE0 : à surveiller si `section-tint` est utilisé un jour.

### Le problème est l’empilement des accents

Sur une seule page d’accueil, on trouve au moins :

1. le bronze des eyebrows, catégories et liens ;
2. la terre cuite du `em` du titre ;
3. la sauge des raisons de recommandation ;
4. cinq familles pastel pour les jaquettes (28°, 42°, 152°, 190°, 262°) ;
5. un vert « extrait gratuit » (`#38523B` sur `#E5EBE1`) ;
6. un laiton clair pour le lecteur (`#D6B67F`) ;
7. l’ancien bronze `rgba(149,109,53,…)` dans les hovers ;
8. l’encre et le papier pour les boutons.

C’est une violation directe de la règle « un seul accent par écran » du design system. La couleur des jaquettes étant dérivée du hash du titre, elle n’a aucune signification : deux livres voisins peuvent être vert et prune sans raison éditoriale. Le plus grand bloc coloré de la page est donc décoratif et aléatoire, tandis que les accents porteurs de sens (bronze, terre cuite) deviennent minoritaires.

### Ce que cela produit visuellement

- **Monotonie** : les cinq fonds sont très clairs (L 86–94 %), donc les jaquettes se ressemblent en valeur et la grille manque de rythme.
- **Dispersion** : les teintes sont réparties sur tout le cercle chromatique, donc la rangée « verte/bleue/prune/rose/ocre » ne se lit pas comme une famille.
- **Perte de contraste** : trois teintes sur cinq échouent AA sur leur propre texte (voir M2).
- **Régression par rapport au prototype** : les jaquettes profondes du prototype (encre, bordeaux, olive, ocre) donnaient du rythme et de la tenue ; l’uniformisation a remplacé la variabilité par de la fadeur.

### Recommandation de palette

Deux options cohérentes, à trancher :

1. **Jaquettes profondes et sémantiques** — 4 familles (encre, terre cuite, sauge, ocre), texte crème commun, une seule valeur de luminosité. La couleur devient un repère de collection, pas un hash.
2. **Jaquettes pastel mais contrastées** — garder cinq teintes, mais les amener à L 40–55 % et utiliser un texte crème ; vérifier chaque couple au contraste, y compris le kicker et l’auteur.

Dans les deux cas : supprimer le vert « extrait gratuit » hors palette (le mapper sur la sauge), remplacer les hovers `rgba(149,109,53,…)` par le bronze `#885F26`, et ne pas introduire de laiton clair dans le lecteur sans le déclarer comme token.

---

## 4. Détail des constats

### B1 — Le lecteur mobile est inutilisable sous la barre de navigation

**Constat.** À 390×844, la barre de lecteur fait 203 px de haut (y = 641 → 844). La navigation mobile fait 58 px (y = 786 → 844) et a un `z-index: 60` contre `20` pour le lecteur. La rangée `.player-actions` est à y = 794 → 835 : elle est **entièrement sous** la navigation. Le bouton `#close` est même à x = 588, hors écran, parce que la rangée est en `overflow-x: auto` et qu’il est le dernier contrôle.

**Conséquence.** Sur mobile, l’utilisateur peut lire/mettre en pause et se déplacer, mais ne peut pas changer la vitesse, le minuteur, le volume, ouvrir les chapitres ou la file, agrandir, ni fermer le lecteur. C’est bloquant pour l’usage principal du produit.

**Preuve.** `evidence/06-lecteur-mobile.png` ; mesures : `.player-bar` 203 px, `.mobile-nav` 58 px `z-index:60`, `.player-actions` y=794, `.mobile-nav` y=786.

**Recommandation.** Au minimum : `body.has-player .mobile-nav { display: none; }` ou décaler le lecteur de la hauteur de la nav + safe-area, et faire passer `.player-actions` en `flex-wrap: wrap` (ou masquer les options secondaires derrière un bouton « Plus ») pour que « Fermer » soit toujours visible. Vérifier au passage que la hauteur du lecteur reste compatible avec `padding-bottom` du contenu.

---

### B2 — Des contrôles annoncent une action qui n’existe pas

**Constat.** Dans `public_ui.site_header()` :

- le hamburger est un `<a href="/" aria-label="Ouvrir le menu">` ; aucun menu n’est rendu, et le CSS `.mobile-menu` n’a aucun consommateur ;
- l’icône loupe est un `<a href="/">` : elle recharge l’accueil au lieu de focus la recherche ;
- l’icône cœur est un `<a href="/?vue=grille">` : elle ne mène pas aux favoris (et n’a pas de sens pour un visiteur anonyme) ;
- « Accueil » et « Bibliothèque » pointent tous les deux vers `/` ; « Découvrir » vers `/?vue=grille` ; « En cours » vers `/?vue=immersif`. Sur l’accueil anonyme, `landing_page()` n’accepte même pas de paramètre `vue` : les quatre liens mènent donc à la même page ;
- les boutons « Romans courts », « Moins d’une heure », « Nouveautés » sont des `<button type="button">` sans handler ni valeur de formulaire : ils ne font rien.

**Preuve.** `api/public_ui.py` lignes 237–286, 952–953 ; `api/public_book.py` `landing_page()` lignes 60–70 ; captures `01`, `02`, `05`.

**Recommandation.** Supprimer le hamburger tant que le menu n’existe pas (ou le transformer en vrai `<button aria-expanded>` avec panneau). Masquer le cœur pour les anonymes. Transformer les suggestions en vrais boutons de filtre (soumettre le formulaire avec un paramètre) ou les retirer. Donner à chaque entrée de navigation une destination réelle, ou réduire la navigation à deux entrées utiles.

---

### M1 — Trois traitements de titre, alors que le système promet une seule famille serif

**Constat mesuré** (Chromium, 1440 px) :

| Page | Élément | Famille | Taille |
|---|---|---|---|
| Accueil | `h1` | Instrument Serif | 74,88 px |
| Livre | `.book-info h1` | **Georgia** | 66,24 px |
| Connexion | `.intro h1` | **Georgia** | 64 px |
| Profil | `h1` | Instrument Serif | 74,88 px |
| Profil | `.profile-card h2` | **Georgia** | 24 px |
| Connexion | `.panel h2` | **Georgia** | 28 px |
| Livre | `.cover-kicker` | Instrument Serif | 9,92 px |
| Accueil | `.cover-kicker` | **Jakarta** | 8,32 px |

**Cause.** La couche « refonte » surcharge les tailles et les marges, mais pas toujours la famille. Les règles historiques restent gagnantes :

- `.book-info h1 { font-family: Georgia, serif; }` — `portal.css` ligne 505 ; la surcharge ligne 934 ne remet pas `font-family`.
- `.intro h1` et `.panel h2` — lignes 75–95.
- `.profile-card h2` — ligne 449.

**Conséquence.** Le mot « AURA » et les titres changent de personnalité selon la page. Le passage d’un serif à l’autre est subtil en capture, mais réel à l’écran (dessin du `é`, du `M`, des ligatures) et incohérent avec la promesse « deux voix seulement ».

**Recommandation.** Faire du `--serif` la seule famille de titres et du `--sans` la seule famille d’interface ; supprimer les `Georgia` en dur des règles de titres. Ajouter un test de non-régression visuel (ou un test Playwright qui vérifie `getComputedStyle(h1).fontFamily` sur chaque page).

---

### M2 — La palette des jaquettes casse l’harmonie et le contraste

**Constat.** `COVER_HUES = (28, 42, 152, 190, 262)` (`public_ui.py` ligne 500) génère cinq familles de fonds pastel (`hsl(h 30% 94%)` → `hsl(h 22% 86%)`) et de textes (`hsl(h 34% 36%)`). Sur une même rangée, on voit donc vert, bleu, prune, rose et ocre, alors que la marque du portail est ivoire/encre/bronze/terre cuite/sauge.

**Contraste WCAG 2.1** (texte normal, seuil 4,5:1 ; le titre de jaquette fait 17,6 px en 400, donc pas « grand texte ») :

| Teinte | Famille | Titre | Auteur | Verdict |
|---|---|---|---|---|
| 28° | bronze/rosé | 4,55:1 | 4,85:1 | limite OK |
| 42° | ocre | **4,02:1** | **4,45:1** | échec AA |
| 152° | vert | **3,77:1** | **4,26:1** | échec AA |
| 190° | bleu | **4,07:1** | 4,53:1 | échec AA |
| 262° | violet | 6,19:1 | 5,98:1 | OK |

Mesure sur le bas du dégradé (`hsl(h 22% 86%)`), le plus défavorable. Le `cover-kicker` est encore plus petit (8,32 px) et échoue sur les mêmes teintes.

**Conséquence.** Le plus grand bloc de couleur de la page est une palette décorative aléatoire, sans lien avec la catégorie ni avec la marque. Les jaquettes se ressemblent toutes en valeur (très claires) tout en étant chromatiquement dispersées : à la fois monotone et bruité. La promesse « aucun avertissement de lisibilité ne subsiste » du README de refonte est contredite.

**Recommandation.** Choisir un système de jaquettes **sémantique et resserré** : 3 ou 4 familles profondes (encre, terre cuite, sauge, ocre), un texte crème commun, et une variation de teinte à valeur/chroma constants. Si l’on garde cinq teintes, les assombrir (L 40–55 %) et utiliser un texte crème pour repasser AA. Ne pas utiliser la couleur comme identifiant aléatoire du titre.

---

### M3 — Le formulaire de filtres est cassé sur desktop et incohérent entre les pages

**Constat 1 — anatomie.** Dans `catalog_filter_fields()` (`public_ui.py` lignes 720–790), `facet_select()` émet :

```html
<label class="filter-field" for="…">Collection</label>
<select id="…">…</select>
```

Le label et le select sont **frères**. Or `portal.css` ligne 202 définit `.filter-field { display:flex; flex-direction:column; }` comme si le label *contenait* le champ. Résultat : le label n’est pas au-dessus du champ, il flotte à côté du champ précédent ; les selects ne partagent pas la même ligne de base, et le bouton « Appliquer les filtres » se retrouve orphelin en bas à gauche. C’est visible sur `03-filtres-desktop.png`.

**Constat 2 — deux interfaces.** Sur l’accueil anonyme, le formulaire de recherche contient **tous** les filtres : hauteur mesurée **229 px** dans un conteneur qui ressemble à une barre de recherche. Sur le catalogue connecté, la recherche fait **62 px** et les filtres sont repliés dans `<details class="filters-fold">`. Même produit, même fonction, deux compositions.

**Constat 3 — mobile.** Sur l’accueil anonyme à 390 px, les huit selects empilés occupent ~600 px avant le premier contenu. Il n’y a pas de « Filtrer et trier » repliable.

**Recommandation.** Un seul composant de filtres, partagé : barre de recherche + bouton « Filtrer et trier » (details), puis panneau de champs. Corriger le markup en enveloppant chaque paire :

```html
<div class="filter-field">
  <label for="collection-select">Collection</label>
  <select id="collection-select">…</select>
</div>
```

ou adapter `facet_select()` pour produire ce wrapper. Sur mobile, garder le panneau replié et placer « Appliquer » en bas, pleine largeur.

---

### M4 — Le collage du hero se chevauche

**Constat.** `.hero-note` est positionnée `right:0; bottom:8px` (desktop) / `right:0; bottom:0` (mobile), au-dessus de la troisième jaquette, elle-même à `left:52%` / `left:48%`. La note recouvre le titre de la jaquette de droite ; sur mobile, la jaquette de gauche est partiellement hors champ et son titre est coupé. La note est le seul élément qui masque du contenu éditorial.

**Preuve.** `01-accueil-desktop.png`, `02-accueil-mobile.png`, `10-annotations-accueil.png`.

**Recommandation.** Réserver une zone à la note (colonne ou dessous), ou réduire le stack à deux jaquettes sur mobile. Ne jamais poser un bloc de texte sur le titre d’une jaquette. Vérifier à 320 px, 390 px et 768 px.

---

### M5 — Contenu dupliqué et « Livre audio » utilisé comme auteur

**Constat.** Chaque carte de carrousel contient :

```html
<span class="cover-title">Titre</span>
<span class="cover-author">Auteur</span>
…
<span class="carousel-title">Titre</span>
<span class="carousel-author">Auteur</span>
```

Le titre et l’auteur sont donc affichés deux fois (sur la jaquette et sous la jaquette). Quand `author` est vide, `fallback_cover_inner()` remplace l’auteur par `"Livre audio"` et le rayon/carte affiche aussi `"Livre audio"` comme auteur : le lecteur voit « LIVRE AUDIO » en kicker, « Livre audio » en auteur sur la jaquette, puis « Livre audio » sous la carte. Ce n’est pas un auteur.

**Preuve.** `public_ui.py` lignes 527–541 (`fallback_cover_inner`), 193–195 (`carousel_shelf`), 665–670 (`_track_html`) ; captures `04`, `05`, `07`.

**Recommandation.** Ne pas afficher de ligne auteur si l’auteur est inconnu. Dans `fallback_cover_inner`, rendre `cover-author` uniquement si `author` est non vide. Idem pour `carousel-author`, `book-card-author`, `track-author`. Si un fallback est vraiment nécessaire, utiliser un libellé explicite (« Auteur non renseigné ») et le sortir de la jaquette.

---

### M6 — L’action principale est visuellement secondaire

**Constat.** Sur l’accueil anonyme, le CTA « Continuer avec Google » est un rectangle blanc bordé (`background:#fff`, bord `#C9C0B2`, rayon 10 px). À côté, « Toutes catégories » est une puce encre pleine, et « Appliquer les filtres » un bouton encre plein. L’œil est attiré par les contrôles secondaires, pas par l’action de connexion. Sur le catalogue connecté, le CTA « Explorer la bibliothèque » est, lui, une pilule encre pleine : le poids du CTA change selon l’état d’authentification.

**Preuve.** `01-accueil-desktop.png`, `05-catalogue-lecteur-desktop.png`, `08-connexion-desktop.png`.

**Recommandation.** Décider d’un seul niveau de poids pour l’action principale. Si Google doit rester blanc pour la reconnaissance, lui donner plus de taille/espace et calmer les puces (contour plutôt que plein). Sinon, utiliser la pilule encre pour le CTA et réserver le blanc au bouton Google de la page de connexion.

---

### M7 — Dérive mesurable du design system

Le design system déclaré (README de la refonte) promet : 12 couleurs, deux familles, une échelle 82/42/21/16/13/11, des rayons 4/8/14/22 + pilules, quatre ombres, un focus 3 px. La feuille livrée contient :

| Indicateur | Déclaré | Livré |
|---|---|---|
| Blocs `:root` | 1 | **2** (legacy + refonte) |
| Couleurs littérales | 12 tokens | **94 valeurs uniques**, dont 63 hex hors `:root` |
| Rayons | 4/8/14/22 + 999 | **13 valeurs** : 2, 3, 4, 8, 10, 12, 14, 16, 999 |
| Tailles de police | 6 | **74 valeurs uniques** |
| Ombres | 4 | **23 valeurs uniques** |
| Focus | 3 px / offset 3 | **4 specs** : 3/3, 3/2, 2/2, 2/offset -2 |
| Sélecteurs redéclarés | — | **170** (dont overrides responsive) |
| Ancien bronze | remplacé | **12 occurrences** de `rgba(149,109,53,…)` (ancien #956D35) |

La couche historique n’a pas été supprimée : elle reste entière sous la refonte, et toutes les propriétés qu’elle déclare et que la refonte ne surcharge pas continuent de gagner. C’est la cause racine des écarts M1, m1, m8, m9.

**Recommandation.** Découper `portal.css` en `tokens.css` (les 12 tokens), `base.css`, `components.css`, puis supprimer la couche historique après une passe de non-régression visuelle. Interdire les hex/rayons/ombres en dur dans les composants (lint CSS ou revue). Mettre à jour le README de la refonte pour qu’il décrive le fichier réellement livré, pas l’intention.

---

### M8 — La navigation active change selon le point de rupture

**Constat.** Sur l’accueil :

- desktop : « Accueil » est souligné (`aria-current="page"`) ;
- mobile : « Découvrir » est en gras (`mobile_nav("Découvrir")` dans `public_book.landing_page`).

Sur la fiche livre :

- desktop : « Accueil » actif (`_brand_bar()` appelle `site_header("Accueil")`) ;
- mobile : « Découvrir » actif (`mobile_nav("Découvrir")`).

Sur le profil : `site_header("Profil")` ne correspond à aucune entrée desktop, donc aucun actif ; `mobile_nav("Profil")` active « Profil ».

**Preuve.** `api/public_ui.py` lignes 237–286, 414, 481 ; `api/public_book.py` lignes 55–57, 214, 279, 347 ; captures `01`, `02`, `07`.

**Recommandation.** Calculer l’actif une seule fois à partir de la route et le passer aux deux navigations. Utiliser `aria-current="page"` sur le lien réellement courant, et pas un libellé qui ne correspond à aucune entrée.

---

### m1 — Deux lecteurs audio

L’extrait de la fiche livre utilise `<audio controls>` natif (chrome gris/bleu du navigateur, menu à trois points, bouton volume système), tandis que la lecture complète utilise une barre custom en encre avec ses propres contrôles. Ce sont deux langages visuels et deux jeux d’affordances pour la même action. Recommandation : un seul composant de lecture (le custom) pour l’extrait aussi, ou assumer le natif et le documenter ; dans tous les cas, aligner la surface du lecteur natif avec la palette (au moins `accent-color`, fond, rayon).

### m2 — Iconographie mixte

La navigation utilise des SVG tracés (`stroke-width:1.7`), mais :

- favoris : `♡` / `♥` en glyphes de police ;
- transport : `⏮`, `«`, `−15s`, `▶`, `+15s`, `»`, `⏭` ;
- fermeture : `×` ;
- retour : `←`.

Le rendu dépend de la police système et du platform ; certains glyphes peuvent devenir des emoji couleur. Le README de la refonte dit pourtant « pas d’emoji, icônes SVG tracées ». Recommandation : une seule famille d’icônes SVG, y compris pour le cœur, le `+` de playlist, le chapitre précédent/suivant et la fermeture.

### m3 — Couleurs PWA, manifest et icône hors palette

- `meta theme-color` : `#F8F6F1` (ancien fond) alors que `body` est `#F7F4ED` ;
- `manifest.webmanifest` : `background_color: #F8F6F1`, `theme_color: #1D2B39` (ancien encre), alors que l’encre de la refonte est `#142438` ;
- `icon.svg` : fond `#1D2B39`, trait `#D3A560` (or), alors que le bronze de la refonte est `#885F26`.

Ces trois valeurs sont visibles dans la barre d’adresse, l’écran de démarrage PWA et le favicon. Recommandation : aligner sur `--bg` / `--ink` / `--bronze`, et mettre à jour `BRAND-IDENTITY.md` qui documente encore une palette bleu/lime pour la marque.

### m4 — Monogramme de jaquette incohérent

Le même monogramme est :

- en haut à droite dans les carrousels (`portal.css` ligne 808) ;
- en bas à droite dans les grilles, la fiche et le hero (lignes 273, 694, 838) ;
- masqué dans le lecteur (ligne 331) ;
- à 54,4 px et opacité 0,13, souvent coupé par le bord de la jaquette.

Recommandation : une seule position (bas droite), une seule taille relative, et une opacité qui reste lisible sans devenir un artefact. Ou supprimer le monogramme : la tranche et le titre suffisent.

### m5 — « Reprendre l’écoute » deux fois de suite

La carte de reprise a pour eyebrow « REPRENDRE L’ÉCOUTE » ; le rayon immédiatement en dessous a pour titre « Reprendre l’écoute ». Recommandation : renommer le rayon « Vos autres lectures » ou supprimer l’eyebrow de la carte.

### m6 — Pied de page de remplissage

`site_footer()` : « À propos », « La collection », « Contact » → `/` ; « Accessibilité », « Confidentialité » → `/profil`. Aucun de ces liens ne mène à une page correspondante. Recommandation : soit implémenter, soit retirer les entrées non prêtes. Un pied de page qui promet des pages inexistantes coûte plus qu’un pied de page minimal.

### m7 — Titres surdimensionnés sur les pages utilitaires

« Mon profil » est rendu avec le style `h1` du hero (74,88 px desktop, 56 px mobile), alors que la page est un formulaire de réglages. Idem pour les pages de confirmation (`confirm_login_page`, `message_page`) qui héritent de `.library-header h1`. Recommandation : créer un niveau `h1` « page utilitaire » (36–44 px) et réserver le 74–82 px à l’accueil et aux pages éditoriales.

### m8 — Plancher typographique non tenu

Le README de la refonte promet « le corps et les métadonnées ne descendent jamais sous 13 px ; seules les étiquettes en majuscules espacées restent à 11 px ». Le rendu contient :

- `.cover-kicker` 8,32 px (accueil), 9,92 px (livre) ;
- `.cover-author` 11,52 px (accueil) ;
- `.carousel-author`, `.book-card-categories`, `.track-categories` 12 px ;
- `.filter-field` 12,16 px ;
- `.preview .eyebrow` 10 px.

Recommandation : appliquer le plancher 13 px aux métadonnées, 11 px aux sur-titres. Pour les jaquettes, soit augmenter, soit assumer une exception documentée (mais 8,32 px reste très petit, surtout sur mobile).

### m9 — Trois formes de boutons et une échelle de rayons absente

- Google/connexion : rayon 10 px, blanc bordé ;
- primaire : pilule 999 px, encre ;
- filtres/recherche : rayon 10 px ;
- jaquettes : 3 px ;
- cartes : 14 ou 16 px ;
- panneau de connexion : 12 px.

Le design system promet 4/8/14/22 + pilules. Recommandation : définir les rayons en tokens et n’utiliser que ceux-là ; garder 3 px pour les jaquettes comme exception « presque carré » documentée. Décider d’une seule forme de bouton primaire.

### m10 — Cartes imbriquées dans le profil

Les quatre statistiques (temps écouté, livres terminés, favoris, marque-pages) sont des `div` bordés à l’intérieur de `section.profile-card` déjà bordée. Le linter de capture signale « carte dans une carte » 4 fois. Recommandation : afficher les stats en lignes simples ou en `dl` sans bordure interne, ou sortir la carte de stats du conteneur.

### m11 — La jaquette de la fiche livre n’a pas de point focal

Sur la fiche livre, la jaquette fait 380×570 px, mais le titre est confiné dans les 100 px du bas, le kicker à 9,92 px, et le monogramme à 13 % d’opacité. Les 70 % supérieurs sont un dégradé beige avec des rayures diagonales très légères. Sur un écran de détail, le visuel principal ressemble à une page blanche plutôt qu’à une couverture. Recommandation : soit assumer une composition éditoriale plus forte (titre plus grand, auteur, filet, numéro de collection), soit réduire la jaquette et laisser le texte de la fiche occuper la place. Ne pas laisser un grand cadre vide comme visuel principal.

---

## 5. Ce qui fonctionne et qu’il ne faut pas casser

- La **direction éditoriale** : ivoire/encre/bronze, serif + sans, ton calme, pas de gradient décoratif, pas d’emoji dans la navigation.
- Le **rythme** du hero et la hiérarchie titre → lede → CTA → recherche → catégories → rayons.
- Les **jaquettes 2:3** à coins presque carrés, la tranche, le principe d’une jaquette typographique uniforme quand il n’y a pas d’artwork.
- Les **carrousels** natifs avec snap, boutons précédent/suivant, `aria-label`, et le choix de réserver les vraies couvertures aux séries.
- La **barre de lecteur custom** (contraste, seek, vitesse, sommeil) : le problème est son empilement mobile, pas son principe.
- Le **contenu éditorial** : pas de faux témoignages, pas de fausses métriques, pas de texte de remplissage. C’est une force à conserver.

---

## 6. Plan d’action proposé

### Quick wins (≈ 1 journée)

1. **Lecteur mobile** : masquer la nav ou décaler le lecteur ; rendre « Fermer » visible ; tester à 390×844.
2. **Supprimer les contrôles morts** : hamburger, cœur anonyme, suggestions « En ce moment » ; ou les brancher.
3. **Unifier les titres** : supprimer les `Georgia` en dur ; vérifier `h1`/`h2` sur accueil, livre, connexion, profil.
4. **Corriger les contrastes des jaquettes** : assombrir les teintes 42/152/190 ou passer le texte en crème.
5. **Envelopper les labels de filtres** dans `.filter-field` et aligner « Appliquer ».
6. **Renommer le rayon « Reprendre l’écoute »** et supprimer le doublon.
7. **Aligner `theme-color` / manifest / icône** sur les tokens du portail.

### Chantier structurel (≈ 2–4 jours)

8. **Fusionner les deux couches CSS** : tokens, base, composants ; supprimer la couche legacy après captures de non-régression.
9. **Un seul composant de filtres** (anonyme + connecté), replié sur mobile.
10. **Une seule navigation** calculée par route, cohérente desktop/mobile.
11. **Une seule famille d’icônes SVG** (favoris, transport, fermeture, retour).
12. **Un seul lecteur audio** (custom) pour l’extrait et la lecture complète, ou assumer le natif et le styler.
13. **Décider de la palette de jaquettes** : profonde et sémantique, ou pastel mais contrastée ; documenter le choix.

### Décisions à prendre (design)

- Le portail est-il une **librairie éditoriale** (jaquettes profondes, peu de couleurs, texte crème) ou un **catalogue pastel** (plus de variété, mais moins de contraste) ?
- Le CTA principal est-il **Google** (blanc, reconnaissance) ou **l’action encre** (pilule, hiérarchie) ?
- Le portail partage-t-il la palette **bleu/lime** de `BRAND-IDENTITY.md` ou assume-t-il une palette **ivoire/bronze** distincte ? Il faut trancher et mettre le doc à jour.

---

## 7. Annexe — correctifs types (non appliqués)

> Ces snippets sont des pistes, pas des patchs appliqués. L’audit est resté en lecture seule.

**a) Lecteur mobile.** Masquer la nav basse quand le lecteur est ouvert, ou décaler le lecteur :

```css
body.has-player .mobile-nav { display: none; }
/* ou */
body.has-player .player-bar { bottom: calc(58px + env(safe-area-inset-bottom)); }
.player-actions { flex-wrap: wrap; }
```

**b) Famille de titre unique.** Rattraper les sélecteurs legacy qui gardent Georgia :

```css
.book-info h1,
.intro h1,
.panel h2,
.profile-card h2,
.empty-state h2 { font-family: var(--serif); }
```

**c) Label + champ.** Envelopper la paire dans `facet_select()` :

```html
<div class="filter-field">
  <label for="collection-select">Collection</label>
  <select id="collection-select" name="collection">…</select>
</div>
```

**d) Auteur inconnu.** Ne pas imprimer « Livre audio » à la place d’un auteur :

```python
author = str(item.get("author") or "").strip()
author_html = f'<span class="cover-author">{ESC(author)}</span>' if author else ""
```

**e) Teintes de jaquette.** Si l’on garde cinq familles, assombrir et passer le texte en crème :

```css
.cover-title, .cover-kicker, .cover-author { color: var(--surface); }
.cover { background: linear-gradient(150deg,hsl(var(--cover-h) 32% 42%),hsl(var(--cover-h) 28% 30%)); }
```

Vérifier ensuite chaque couple au contraste (le README de la refonte affirme à tort qu’aucun avertissement ne subsiste).

---

## 8. Limites de l’audit

- Les captures ont été prises sur un **snapshot HTML local** du portail réel ; le HTML de production a été récupéré et comparé : il est identique à l’exception des images de couvertures (non servies par le serveur statique local). Les erreurs 404 de `/covers`, `/sw.js` et des endpoints `/api/public/*` sont des artefacts du harnais local, pas des défauts du portail.
- Le lecteur a été observé avec des données de démonstration ; les mesures de chevauchement (203 px / 58 px / y=786) sont indépendantes des données.
- Aucun test utilisateur ni lecteur d’écran réel n’a été passé ; les constats d’accessibilité sont limités aux contrastes calculés, à la sémantique du markup et aux styles de focus.
- La console d’administration React (`web/src`) n’est pas incluse ; elle utilise un autre design system (sombre/ambre) et mérite un audit séparé.

---

## 9. Fichiers de preuve

| Fichier | Contenu |
|---|---|
| [`evidence/01-accueil-desktop.png`](evidence/01-accueil-desktop.png) | Accueil anonyme, 1440×900 |
| [`evidence/02-accueil-mobile.png`](evidence/02-accueil-mobile.png) | Accueil anonyme, 390×844 |
| [`evidence/03-filtres-desktop.png`](evidence/03-filtres-desktop.png) | Filtres + catégories + début des rayons |
| [`evidence/04-carrousels-desktop.png`](evidence/04-carrousels-desktop.png) | Rangées de jaquettes |
| [`evidence/05-catalogue-lecteur-desktop.png`](evidence/05-catalogue-lecteur-desktop.png) | Catalogue connecté + lecteur |
| [`evidence/06-lecteur-mobile.png`](evidence/06-lecteur-mobile.png) | Lecteur mobile et nav basse |
| [`evidence/07-livre-desktop.png`](evidence/07-livre-desktop.png) | Fiche livre |
| [`evidence/08-connexion-desktop.png`](evidence/08-connexion-desktop.png) | Connexion |
| [`evidence/09-profil-desktop.png`](evidence/09-profil-desktop.png) | Profil |
| [`evidence/10-annotations-accueil.png`](evidence/10-annotations-accueil.png) | Accueil annoté (hero, filtres, monogrammes, hamburger) |
| [`evidence/11-annotations-lecteur-mobile.png`](evidence/11-annotations-lecteur-mobile.png) | Lecteur mobile annoté (chevauchement nav) |
