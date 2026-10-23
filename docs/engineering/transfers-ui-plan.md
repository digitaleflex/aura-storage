# Refonte UI/UX — page Transferts (plan d'intégration)

Statut : implémenté et vérifié — voir `transfers-ui-report.md`.
Branche : `feat/transfers-ui`.

## 1. Périmètre réel du dépôt (audit)

| Élément | Constat |
|---|---|
| Frontend | React 18 + TanStack Router/Query, Vite, un seul `styles.css` (tokens + composants). |
| Thème | Sidebar sombre (`--side: #10151d`) + surface claire, accent ambre `--signal: #9d660d`. Thème sombre disponible via `data-theme="dark"` (préférence utilisateur). |
| Routes | `/` (Fichiers), `/admin`, `/login`. Aucune route Transferts. |
| Nav | `Fichiers`, `Administration` (admin uniquement). |
| File de transferts | `startUploadQueue` (`lib/transfer.ts`) — file en mémoire, possédée par `ObjectsPage`, affichée dans le plateau flottant `UploadTray`. |
| Progression | XHR `upload.onprogress` → `QueueState`, coalescé à 250 ms. Débit global via `ThroughputWindow` (20 s). |
| Persistance | Journal IndexedDB `uploadJournal` (métadonnées seulement) pour reprendre après rechargement en re-sélectionnant les fichiers. Aucun historique serveur des transferts. |
| API transfert | `POST /objects/upload-intents`, `POST /objects/{id}/commit`, `POST /objects/{id}/abort`, `GET /objects/{id}`. Pas d'endpoint de listing des sessions de transfert. |
| Capacité | `GET /admin/usage` réservé aux admins (`admin:read`). Aucune capacité publique pour un utilisateur standard. |
| Tests | Playwright e2e (mocks réseau), régression visuelle 6 baselines, build `tsc --noEmit && vite build`. Pas de tests unitaires. |

## 2. Décisions d'architecture

1. **La file est élevée au niveau du shell** via `TransfersProvider` (au-dessus du routeur, dans la route racine) afin qu'elle survive à la navigation et soit partagée entre la page Fichiers, le plateau et la page Transferts. Aucune modification du moteur `lib/transfer.ts`.
2. **Nouvelle route `/transfers`** protégée par `RequireAuth`, rendue dans `Layout`.
3. **« Ajouter des fichiers »** renvoie vers la page Fichiers en ouvrant le panneau d'import existant (`/?import=1`). Aucun second chemin d'upload n'est créé.
4. **Périmètre des données** : la page affiche la session d'importation du navigateur en cours. Il n'existe pas d'historique serveur ; aucun transfert terminé n'est inventé ni restauré après rafraîchissement.
5. **Thème** : la palette AURA sombre de la spécification est appliquée au shell (sidebar, topbar, contenu) **uniquement sur `/transfers`** via `.shell-transfers`, pour ne pas régresser les pages existantes. Les tokens `--aura-*` sont centralisés.
6. **Capacités réelles** : pause par fichier = uniquement les fichiers non démarrés (le moteur n'interrompt pas un PUT en cours) ; annulation = `abort` backend ; reprise = nouvelle exécution du même fichier via le moteur ; pas de « ouvrir le fichier » ni de retrait de ligne (non exposés par `QueueItem`).
7. **Débit et ETA** : débit global `ThroughputWindow` ; débit par ligne échantillonné côté client ; ETA inconnu si débit nul.
8. **Stockage** : widget réel pour les admins (`adminUsage`, capacité si configurée) ; message honnête pour les autres (pas de chiffre inventé).

## 3. Fichiers

Créés :
- `web/src/lib/transferContext.tsx` — provider partagé (état, actions, débit, échantillons par fichier).
- `web/src/lib/transferDeps.ts` — dépendances moteur → API (extrait d'`ObjectsPage`).
- `web/src/pages/TransfersPage.tsx`
- `web/src/components/transfers/*` — synthèse, métriques, progression, barre d'actions, filtres, liste, ligne, badges, panneau d'erreur, dialogues.
- `web/src/components/StorageUsage.tsx`
- `web/src/transfers.css`
- `web/e2e/transfers.spec.ts`

Modifiés :
- `web/src/router.tsx` (route `/transfers`)
- `web/src/components/Layout.tsx` (entrée de nav, classe de thème, widget stockage)
- `web/src/pages/ObjectsPage.tsx` (consommation du provider, `?import=1`)
- `web/src/main.tsx` (import de `transfers.css`)
- `web/e2e/visual-regression.spec.ts` + baselines

## 4. Écarts assumés par rapport à la maquette/spécification

- Aucune maquette spécifique « Transferts » dans le dépôt : seule la capture « AURA Vault File Dashboard.png » existe. La direction artistique écrite (palette, hiérarchie) est la référence.
- Pas d'historique de transferts persistant côté serveur : compteurs = session courante.
- Pas de widgets « aide », « notifications », « type de compte » : fonctionnalités absentes.
- Entrées de nav non existantes (Tableau de bord, Stockage, Partages, Corbeille, Paramètres) non inventées.
- Pas de reprise multipart : le moteur ne l'implémente pas.
- Pas d'action « ouvrir le fichier » depuis la ligne terminée : l'`objectId` n'est pas exposé par `QueueItem`.
- Widget de stockage chiffré réservé aux admins (API `admin:read`).
