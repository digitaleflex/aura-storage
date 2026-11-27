# Correctifs lot 1 — portail public AURA

**Date :** 27 novembre 2026  
**Référence audit :** [`AUDIT-UI-PORTAIL.md`](AUDIT-UI-PORTAIL.md)  
**Commits :** `7b74146`, `73639d7`, `8784b69`  
**Tests :** `100 passed` (`test_public_portal`, `test_public_portal_a11y`, `test_public_classification`, `test_cover_jacket`).

---

## 1. Ce qui a été corrigé

### Lecteur mobile

- La barre de lecteur est remontée au-dessus de la navigation basse (`body.has-player:not(.full-player) .player-bar`), avec `padding-bottom` du contenu ajusté.
- Les options du lecteur passent en `flex-wrap` : « Chapitres / File / Agrandir / Premium / Fermer » restent visibles et cliquables.
- Le statut du lecteur n’est plus en position absolue sur mobile : il passe sous les contrôles, sans recouvrement.
- Le lecteur plein écran reste **encre sur encre** (plus de texte papier sur fond papier) et le bouton « Agrandir » redondant est masqué quand on est déjà en plein écran.
- Le focus clavier du lecteur utilise un anneau laiton clair (`--focus-on-dark: #D6B67F`) au lieu du bronze sombre, insuffisant sur l’encre.
- Le mini-lecteur n’affiche plus le texte de jaquette en micro-caractères : uniquement le monogramme.

**Mesures après correction (390×844) :** lecteur de 271 px terminé à y=786 ; navigation de 58 px commençant à y=786 ; actions à y=668–749 ; `#close` visible à x=306. Aucun chevauchement.

### Typographie

- Une seule serif pour les titres : `.book-info h1`, `.intro h1`, `.panel h2`, `.profile-card h2`, `.hero h2` utilisent `var(--serif)`.
- Les petits textes de jaquette (`.cover-kicker`, `.cover-author`) utilisent `var(--sans)`, comme les métadonnées du design system.
- Vérifié au computed style : accueil, connexion, livre et profil rendent tous **Instrument Serif** pour les titres.

### Jaquettes

- Palette ramenée de 5 à **4 teintes** : `(28, 152, 205, 262)` — bronze/rosé, sauge, bleu ardoise, violet.
- Texte commun en encre (`--ink`) et auteur en `--text` : le contraste ne dépend plus de la teinte. Les couples passent tous largement AA (≈ 10,7:1 à 14:1 sur les fonds pastel).
- La teinte est conservée dans les grilles et la fiche livre (la règle `background: var(--bg-deep)` ne l’écrase plus).
- Le monogramme du lecteur passe en laiton clair sur le fond sombre.
- `api/cover_jacket.py` reste synchronisé avec `api/public_ui.py` (test d’égalité).

### Filtres

- Chaque label et son contrôle sont maintenant dans un même `.filter-field` : les labels sont au-dessus des champs, plus à côté du champ précédent.
- Largeur minimale des champs portée à 11 rem : les libellés « Toutes les collections », « Toutes les catégories », etc. ne sont plus tronqués.
- Le bouton « Appliquer les filtres » est aligné à droite sur desktop, pleine largeur sur mobile.
- L’accueil anonyme utilise désormais le même panneau replié `Filtrer et trier` que le catalogue connecté : la barre de recherche fait **62 px** au lieu d’un panneau de **229 px**. Les filtres restent accessibles, mais ne poussent plus le catalogue sur deux écrans.
- Les suggestions « Romans courts / Moins d’une heure / Nouveautés » sont de vrais liens (`duree_max`, `tri=recent`) au lieu de boutons inertes.
- Les puces « Toutes catégories » et « Tous thèmes » ne sont plus marquées pressées : ce sont des liens de réinitialisation, pas des filtres actifs. Une seule puce active à la fois.

### Navigation et hero

- Le hamburger mort (desktop et mobile) est supprimé ; la navigation basse suffit sur mobile.
- Les entrées pointent vers des ancres réelles : `/#decouvrir`, `/#tous`, `/#resume` (connecté), `/#recherche`, `/#favoris`.
- « En cours » n’est plus affiché pour un visiteur anonyme.
- Le cœur n’est plus affiché pour les anonymes et pointe vers `#favoris` pour un connecté.
- L’icône loupe mène à `#recherche`.
- La navigation active est cohérente desktop/mobile : accueil actif sur l’accueil, bibliothèque active sur la fiche livre.
- La note du hero ne recouvre plus la jaquette de droite : elle est placée sous la pile sur desktop et masquée sur mobile, où elle n’a pas la place de respirer.

---

## 2. Avant / après

| Point | Avant | Après |
|---|---|---|
| Lecteur mobile | Nav basse `z-index:60` sur lecteur `z-index:20`, actions masquées | Lecteur remonté au-dessus de la nav, actions visibles |
| Plein écran | Texte papier sur fond papier (~1:1) | Encre sur encre, focus laiton |
| Titre livre | Georgia 66 px | Instrument Serif 66 px |
| Titre connexion | Georgia 64 px | Instrument Serif 64 px |
| Kicker jaquette | Serif sur la fiche, sans dans les carrousels | Sans partout |
| Jaquettes | 5 pastels, 3/5 échouent AA | 4 teintes, texte encre, AA |
| Grille / fiche | Fond sable neutre, teinte perdue | Teinte conservée |
| Filtres desktop | Labels détachés, bouton orphelin | Labels au-dessus, grille alignée |
| Filtres anonymes | Panneau ouvert de 229 px | Barre de 62 px + panneau replié |
| Hamburger | Lien mort visible partout | Supprimé |
| Suggestions | Boutons inertes | Liens de filtre |
| Hero | Note sur la 3e jaquette | Note sous la pile, masquée sur mobile |

**Captures après :** [`evidence-after/`](evidence-after/) (10 écrans).

---

## 3. Ce qui reste ouvert

Ces points sont dans l’audit mais **hors du lot 1** :

- **Palette pastel** : les 4 teintes sont plus cohérentes et contrastées, mais restent décoratives. La variante « jaquettes profondes et sémantiques » reste une décision de direction.
- **Duplication de contenu** : titre/auteur toujours répétés sur la jaquette et sous la carte ; « Livre audio » sert encore d’auteur quand l’auteur manque.
- **Deux lecteurs audio** : extrait en `<audio>` natif, lecture complète en lecteur custom.
- **Iconographie** : glyphes Unicode pour favoris, transport, fermeture et retour, alors que la navigation utilise des SVG.
- **PWA / favicon** : `theme-color` #F8F6F1, manifest #1D2B39, icône or #D3A560, toujours hors palette.
- **Pied de page** : « À propos », « La collection », « Contact » pointent encore vers `/`.
- **Titres utilitaires** : « Mon profil » et les confirmations gardent le `h1` hero de 74,88 px.
- **Plancher typographique** : 12 px pour plusieurs métadonnées, 8,32 px pour le kicker de jaquette.
- **Rayons** : échelle 2/3/8/10/12/14/16/999 au lieu de 4/8/14/22.
- **Profil** : cartes de statistiques imbriquées.
- **Fiche livre** : jaquette 380×570 encore très vide (m11).
- **`<title>` / skip link** : `<title>` émis après `<body>` sur certains pages, lien d’évitement de la connexion sans cible `#main`.
- **Revue indépendante après correction** : non refaite ; les vérifications sont le rendu Chromium, les computed styles et les 100 tests.

---

## 4. Vérification

```text
100 passed in 44,27s
```

Pages rendues et inspectées à 1440×900 et 390×844 :
accueil anonyme, filtres ouverts, catalogue connecté, lecteur mobile, lecteur plein écran, fiche livre, connexion, profil.

Les erreurs 404 visibles dans certaines captures (`/covers`, `/sw.js`, `/api/public/*`, `/m/x.mp3`) sont des artefacts du serveur statique local utilisé pour l’audit, pas des défauts du portail.
