# Import AURA — préflight progressif et animation

- **Date :** 24 novembre 2026
- **Statut :** implémenté côté frontend ; tests unitaires et typage validés ; E2E et capture visuelle non exécutés faute de dépendances Chromium système

## Direction

L'interface reste dans le langage visuel AURA existant : surfaces claires `steel`, accent ambre `signal`, typographie IBM Plex, états sémantiques vert/bleu/orange/rouge. Aucun nouveau design system ni nouvelle dépendance d'animation n'a été introduit.

Le héros du panneau est la **vérification en direct** : un indicateur circulaire discret, une progression réelle et une liste par fichier. Les dossiers sont regroupés visuellement pour rendre les imports multi-racines lisibles.

## Parcours

1. L'utilisateur choisit des fichiers, ajoute un ou plusieurs dossiers, colle ou dépose son contenu.
2. Le contenu reste en attente : aucun import ne démarre sans le clic sur « Importer et valider ».
3. Le préflight affiche chaque fichier dans un état : en attente, vérification, vérifié, doublon ou à revérifier.
4. Les doublons sont détectés dans la destination et dans le lot sélectionné.
5. L'utilisateur peut retirer un fichier, retirer un dossier entier, relancer la vérification ou importer malgré les doublons.

Pendant un transfert, le bouton devient **« Mettre en attente »**. Le backlog ne démarre qu'après cette action explicite, avec une nouvelle vérification des doublons.

## Détection des doublons

- Nom + taille pour les gros fichiers lorsque le hash coûteux n'est pas nécessaire.
- SHA-256 pour les petits fichiers, afin de détecter aussi les contenus identiques renommés.
- SHA-256 ciblé pour les gros fichiers déjà plausibles par nom + taille.
- Comparaison limitée au dossier de destination.
- Objets existants filtrés sur le statut `available`.
- Un échec de hash produit un état « À revérifier » et bloque l'import tant que la vérification n'a pas réussi.

## Animations

- Rotation de l'indicateur pendant la vérification.
- Barre de analyse indéterminée pendant le chargement du catalogue.
- Shimmer de progression et transition de la largeur réellement vérifiée.
- Apparition courte des lignes et des dossiers.
- Animation de statut pour les fichiers vérifiés ou en doublon.
- Désactivation complète des animations sous `prefers-reduced-motion`.

## Accessibilité

- `role="progressbar"`, libellé, bornes et `aria-valuetext`.
- État indéterminé sans `aria-valuenow` trompeur.
- Résumé annoncé dans une région vive, sans annoncer chaque ligne.
- Statuts écrits en plus de la couleur.
- Boutons de retrait nommés et focus visible.
- Cible WCAG 2.1 AA ; test axe ajouté au scénario E2E.

## Validation

- `npx tsc --noEmit` : réussi.
- `npm run test:unit` : **85 tests réussis**.
- `npm run lint` : aucune erreur, 13 avertissements préexistants hors nouvelle logique.
- `git diff --check` : réussi.
- E2E Playwright : non exécutés ; Chromium ne démarre pas car plusieurs bibliothèques système manquent (`libatk`, `libgbm`, `libasound`, etc.).
- Capture avant/après : non produite pour la même raison. Le rendu visuel reste donc à vérifier dans un navigateur local.
