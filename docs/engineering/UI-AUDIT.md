# Audit interface — ce qui manque pour être à la pointe (2026-10-16)

Source : revue designer + inspection (`ObjectsPage` 1943 l., `AdminPage`,
`styles.css`, `transfer.ts`). Déjà au niveau : moteur de transfert (backoff,
concurrence adaptative), bases a11y (rôles, progressbar, `<dialog>` natif),
responsive, copies honnêtes.

## P0 — cassé ressenti

1. **Drop ignoré pendant un transfert** : fichiers avalés sans message
   (`ObjectsPage:961`, garde `transferActive`). → file d'attente ou refus annoncé.
2. **Dossier glissé = fichier fantôme** : `dataTransfer.files` (0 o) au lieu de
   `dataTransfer.items` + `webkitGetAsEntry` ; la tuyauterie dossier n'est
   câblée qu'au bouton. → router vers `planFolders()`, rejeter explicite.
3. **Aucun affordance de drop** : `onDragOver` nu, pas d'état visuel
   « Relâchez pour importer ». → overlay + état `.drop-active`.
4. **« Tout sélectionner » invisible aux lecteurs d'écran** : checkbox dans
   sous-arbre `aria-hidden` (`ObjectsPage:1383`). → sortir du conteneur masqué.

## P1 — standard moderne attendu

5. Skeletons (ledger 6 colonnes, cartes stats) au lieu de « Chargement… ».
6. Système de toasts (bas-droite, auto-dismiss 5 s, erreurs persistantes) ;
   `downloadStatus` incohérent (bas de section vs haut de page).
7. Drawer détails : focus non géré (Escape inopérant, pas de restauration).
8. Suppression en masse silencieuse pendant l'exécution → progression live
   (« 3/10… »).
9. Clavier : restauration focus `RowMenu`, flèches menu, raccourcis (`/`,
   `Delete`), légende `?`.
10. Import arborescence : progression par dossier + nom du dossier en échec.

## P2 — polish (backlog)

Dark mode (graphite déjà sur place), focus-ring `.link-button`/`.crumb`,
undo (dépend d'une API restore), progression globale + débit/ETA + pause,
auto-collapse file terminée, scroll infini + virtualisation, garde-fou taille
client (`max_object_bytes`), retry sur erreurs admin, error boundary, autofocus
login, transitions de route, coller-pour-importer (Ctrl+V), tri par colonnes.

## Dépendances API à noter

Undo-delete exige un endpoint restore/annulation (absent) ; le reste est
frontend seul.

## État vérifié dans le code — 2026-10-21

Cette section suit les trois jalons GitHub (#112 P0, #113 P1, #114 P2). Elle
décrit le code présent sur `main`, pas un déploiement.

### P0 — résolu

1. Drop pendant un transfert : les fichiers libres vont dans `pendingFiles`
   avec un toast, un dossier est refusé avec un message explicite.
2. Dossier glissé : `dataTransfer.items` + `webkitGetAsEntry`, arborescence
   routée vers `planFolders()`; fichiers vides et dossiers vides comptés et
   annoncés séparément.
3. Affordance de drop : overlay « Relâchez pour importer » et compteur de
   profondeur anti-clignotement.
4. « Tout sélectionner » : checkbox sortie du sous-arbre `aria-hidden`, avec
   un libellé accessible.

### P1 — résolu sauf virtualisation

1. Clavier : `/` (recherche), `Suppr` (confirmation de la sélection), `?`
   (légende), `Échap`; les raccourcis ignorent la saisie de texte mais
   fonctionnent quand le focus est sur une case à cocher. Menu de ligne :
   flèches/Home/End, `Échap` rend le focus au déclencheur.
2. Undo : toast « Annuler » après suppression simple ou en masse via l'API
   restore; erreurs d'échec listées avec le nom du fichier.
3. Progression globale, débit/ETA et pause/reprise dans la barre d'import.
4. Auto-collapse de la file terminée.
5. Scroll infini : oui. **Virtualisation DOM : non** — les pages font 50
   lignes et s'accumulent; un windowing mesuré reste à faire si les
   catalogues dépassent quelques milliers de lignes (les menus de ligne et
   les hauteurs variables mobile doivent être couverts par des tests dédiés).
6. Garde-fou taille client : `max_object_bytes` vérifié avant l'upload.
7. Import d'arborescence : progression « dossier n/N — nom » et nom du
   dossier en échec; la progression par fichier reste dans la file.

### P2 — résolu

Dark mode système, focus-ring `.link-button`/`.crumb`, error boundary,
autofocus login, transitions de contenu, coller-pour-importer (`Ctrl+V`),
tri serveur par colonnes, harmonisation admin (tokens, plus de valeurs
codées en dur), retry sur les erreurs admin.

### Reste ouvert

- Virtualisation DOM de la liste (voir P1.5).
