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
