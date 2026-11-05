# Nouvelles issues fonctionnelles — Interface utilisateur

Ces issues ont été identifiées lors d'un audit complémentaire de l'UI.

## ISSUE-022 — Sélection en bulk (multiple) des dossiers

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Sur la page Fichiers (`ObjectsPage`), l'utilisateur peut sélectionner plusieurs fichiers individuellement, mais il n'existe pas de mécanisme de sélection en bulk (tout sélectionner, sélection par glissement, sélection par dossier) pour les dossiers.

**Conséquence :** L'utilisateur doit cliquer sur chaque dossier un par un pour effectuer une action de groupe (partage, suppression, déplacement).

**Critères d'acceptation :**
- [ ] Bouton « Tout sélectionner » qui sélectionne aussi les dossiers
- [ ] Sélection multiple des dossiers via checkboxes
- [ ] Actions de groupe disponibles sur les dossiers sélectionnés (partager, supprimer, déplacer)

**Fichiers concernés :** `web/src/pages/ObjectsPage.tsx`, `web/src/components/RowMenu.tsx`

---

## ISSUE-023 — Affichage de la taille de chaque dossier

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Dans la liste des dossiers et dans le dialogue de partage (`ShareDialog`), la taille de chaque dossier n'est pas affichée. L'utilisateur ne sait pas combien de données contient un dossier avant de le partager.

**Conséquence :** Impossible de savoir le volume de données qu'un lien de partage va exposer.

**Critères d'acceptation :**
- [ ] Calculer la taille totale de chaque dossier (récursivement, objets + sous-dossiers)
- [ ] Afficher la taille dans la liste des dossiers
- [ ] Afficher la taille dans le dialogue de partage d'un dossier

**Fichiers concernés :** `web/src/pages/ObjectsPage.tsx`, `web/src/components/ShareDialog.tsx`, `api/object_query.py`, `api/db.py`, `api/db_pg.py`

---

## ISSUE-024 — Téléchargement en ZIP d'un dossier partagé

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Quand un utilisateur ouvre un lien de partage vers un dossier (`GET /f/{token}`), il peut voir les fichiers mais doit les télécharger un par un. Il n'existe pas de bouton « Télécharger tout en ZIP ».

**Conséquence :** Télécharger un dossier avec beaucoup de fichiers est fastidieux.

**Critères d'acceptation :**
- [ ] Bouton « Télécharger le dossier en ZIP » sur la page de partage public d'un dossier
- [ ] Génération du ZIP côté frontend (JSZip) ou côté backend
- [ ] Le ZIP contient l'arborescence complète du dossier partagé

**Fichiers concernés :** `web/src/pages/`, `web/src/lib/`, `api/main.py` (si endpoint backend)
