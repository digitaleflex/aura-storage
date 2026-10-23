# Transferts — rapport d'implémentation

Branche : `feat/transfers-ui`  
Date : 23 octobre 2026  
Périmètre : page `/transfers`, coquille (navigation + widget de stockage), file
d'importation partagée. Moteur de transfert, API, authentification et stockage
inchangés.

## 1. Ce qui a été livré

### Architecture

- **File d'importation élevée au niveau du shell** (`src/lib/transferContext.tsx`).
  Le moteur `startUploadQueue` / `UploadQueue` de `src/lib/transfer.ts` est
  réutilisé tel quel. La file survit désormais à la navigation : un import lancé
  depuis la page Fichiers continue et devient visible/contrôlable sur `/transfers`.
- **Nouvelle route protégée `/transfers`** (`RequireAuth`, même `Layout`).
- **« Ajouter des fichiers »** renvoie vers `/?import=1`, qui ouvre le panneau
  d'import existant. Aucun second chemin d'upload n'a été créé.
- **Thème AURA sombre** appliqué au shell uniquement sur `/transfers`
  (`.shell-transfers`), via des tokens `--aura-*` centralisés dans
  `src/transfers.css`. Les autres pages conservent leur thème.
- **Nettoyage de session** : un changement de session (déconnexion, changement
  de compte) annule et vide la file en mémoire.

### Interface

- En-tête : titre, sous-titre, indication « Session courante ».
- Synthèse : anneau de progression par fichiers, volume transféré, barre de
  volume, six indicateurs (débit, temps restant, actifs, terminés, en attente,
  échecs). Les deux progressions sont distinctes et protégées contre les totaux
  nuls.
- Barre d'actions : pause globale, reprise, ajout de fichiers, annulation
  globale confirmée, menu secondaire (relance des échecs, effacement d'une file
  terminée, réinitialisation des filtres).
- Filtres : onglets de statut avec compteurs exacts, recherche locale avec
  effacement, panneau avancé (type, taille min/max en Mo, tri).
- Sélection multiple avec actions groupées (pause, reprise, annulation
  confirmée, désélection).
- Liste : nom + type + heure d'ajout, taille, progression (%, barre, octets),
  badge de statut texte + couleur, vitesse par fichier, menu d'actions
  contextuelles. Pagination locale par blocs de 50.
- Panneau d'échec inline : titre dérivé de `failureKind`, message serveur,
  nouvelle tentative, accès aux détails.
- Dialogue de détails : taille, octets transférés, progression, tentatives,
  mode de vérification, empreinte SHA-256, durées de commit, chronologie des
  étapes, erreur classifiée. Aucun identifiant de corrélation inventé, aucune
  trace interne.
- États vides distincts : file vide (session) vs aucun résultat de filtre.
- Responsive : grille 3/2/1 colonnes, barre d'actions repliée, tableau
  transformé en cartes sous 768 px (pas de tableau comprimé).
- Accessibilité : `progressbar` nommés, badges compréhensibles sans couleur,
  boutons iconographiques libellés, dialogues natifs avec focus/Échap, une
  seule région live pour le nombre de fichiers terminés (pas d'annonce par
  octet), `prefers-reduced-motion` respecté.
- Sidebar : entrée « Transferts » avec compteur, état actif vert citron, widget
  « Stockage utilisé » avec volume, capacité, barre et pourcentage réels
  lorsqu'ils sont disponibles.

## 2. Fichiers

Créés :
- `web/src/lib/transferContext.tsx`
- `web/src/lib/transferDeps.ts`
- `web/src/lib/format.ts`
- `web/src/pages/TransfersPage.tsx`
- `web/src/components/StorageUsage.tsx`
- `web/src/components/transfers/TransferIcon.tsx`
- `web/src/components/transfers/model.ts`
- `web/src/components/transfers/TransfersOverview.tsx`
- `web/src/components/transfers/TransfersToolbar.tsx`
- `web/src/components/transfers/TransfersFilters.tsx`
- `web/src/components/transfers/TransferList.tsx`
- `web/src/components/transfers/TransferDialogs.tsx`
- `web/src/transfers.css`
- `web/e2e/transfers.spec.ts`
- `web/e2e/transfers.spec.ts-snapshots/transfers-desktop-linux.png`
- `web/e2e/transfers.spec.ts-snapshots/transfers-mobile-linux.png`
- `docs/engineering/transfers-ui-plan.md`
- `docs/engineering/transfers-ui-report.md` (ce fichier)

Modifiés :
- `web/src/router.tsx` — provider racine + route `/transfers`
- `web/src/components/Layout.tsx` — entrée de navigation, classe de thème,
  widget de stockage (desktop + tiroir mobile)
- `web/src/pages/ObjectsPage.tsx` — consommation du provider partagé,
  `?import=1`
- `web/src/main.tsx` — import de `transfers.css`
- `web/README.md` — documentation de la page et du test
- `web/e2e/vault-ui-behaviors.spec.ts` — deux assertions mises à jour (voir §5)
- `web/e2e/visual-regression.spec.ts-snapshots/files-desktop-linux.png`,
  `admin-desktop-linux.png` — nouvelles entrées de navigation

## 3. Règles de données appliquées

- Statuts dérivés du moteur : `idle` → En attente (ou En pause si le fichier est
  suspendu), `requesting-intent` → Initialisation, `uploading` → En cours,
  `validating` → Vérification, `available` → Terminé, `failed` → Échec,
  `cancelled` → Annulé.
- Progression fichiers = terminés / (total − annulés). Progression volume =
  octets transférés / octets du périmètre (hors annulés).
- Débit global = fenêtre glissante de 20 s du moteur ; 0 affiché comme
  « Inactif », « Calcul en cours » pendant la première seconde d'activité.
- Temps restant = octets restants / débit ; jamais « 0 s » quand il reste des
  fichiers ou quand le débit est inconnu.
- Vitesse par fichier : dérivée des deltas d'octets observés sur ≥ 1 s, jamais
  inventée. Les fichiers non en cours affichent « — ».
- Pause : uniquement les fichiers non démarrés (le moteur n'interrompt pas un
  PUT en cours) ; l'interface l'explique explicitement.
- Annulation : `abort` backend pour les envois en cours, marquage annulé pour
  la file ; les fichiers déjà publiés restent dans le stockage.
- Reprise : `retryItem` du moteur, nouvelle soumission avec la même clé
  d'idempotence ; aucune réutilisation à l'aveugle d'un identifiant expiré.
- Succès affiché uniquement après la phase `available` confirmée par le commit
  serveur.

## 4. Vérifications exécutées

| Commande | Résultat |
|---|---|
| `cd web && npx tsc --noEmit` | OK |
| `cd web && npm run build` | OK (tsc + Vite, 210 modules) |
| `npx playwright test e2e/transfers.spec.ts` | 19 tests OK |
| `npm run test:unit` (Vitest) | 25 tests OK |
| `npx playwright test` (suite complète) | **163 tests OK** (dernière exécution après le lot D) |
| Baselines visuelles | `transfers-desktop` et `transfers-mobile` créées ; `files-desktop` et `admin-desktop` régénérées pour la nouvelle entrée de navigation |

Note d'environnement : la machine de test n'a pas les bibliothèques GUI de
Chromium ; les e2e ont été exécutés avec `LD_LIBRARY_PATH` et `FONTCONFIG_FILE`
pointant vers des bibliothèques/polices extraites localement. Aucun changement
du dépôt n'en dépend.

## 5. Écarts, limites et points à connaître

1. **Pas d'historique serveur des transferts.** L'API n'expose ni liste ni
   session de transfert persistée : la page suit donc la session du navigateur.
   Un rechargement efface la file (le journal IndexedDB permet seulement de
   reprendre en re-sélectionnant les fichiers sur la page Fichiers). Les chiffres
   de la maquette (346 fichiers, sessions passées) ne sont pas reproductibles.
2. **Maquette « Transferts » absente du dépôt.** Seule la capture « AURA Vault
   File Dashboard.png » existe. La direction écrite (palette sombre, hiérarchie)
   a servi de référence ; le rendu est comparé aux baselines créées.
3. **Thème limité à `/transfers`.** Une refonte sombre de toute l'application
   n'était pas demandée et aurait régressé les pages existantes. Les contrôles
   densité/thème sont masqués sur cette page, dont l'identité est fixe.
4. **Widget de stockage** : les volumes/capacité réels viennent de
   `GET /admin/usage` (`admin:read`). Pour les autres comptes, aucun chiffre
   n'est inventé : le message « Chiffré au repos, intégrité vérifiée » est
   conservé. L'API ne fournit pas de capacité publique.
5. **Navigation** : seules les destinations existantes sont proposées
   (Fichiers, Transferts, Administration). Tableau de bord, Stockage, Partages,
   Corbeille et Paramètres n'existent pas et n'ont pas été inventés. Aide,
   notifications et menu de compte ne sont pas ajoutés.
6. **Actions par ligne** : pas d'« ouvrir le fichier » car `QueueItem` n'expose
   pas l'`objectId` ; pas de retrait unitaire d'une ligne terminée (le moteur ne
   propose que l'effacement global d'une file terminée). Pas de reprise
   multipart : le moteur ne l'implémente pas.
7. **Filtres/recherche/tri côté client** : la file est locale, il n'y a pas
   d'endpoint paginé de transferts. Les critères non disponibles (plage de
   dates serveur) ne sont pas proposés.
8. **Performance** : rendu plafonné à 50 lignes + « Afficher plus » ; les mises
   à jour de progression restent coalescées à 250 ms par le moteur. Pas de
   virtualisation, non nécessaire aux volumes mesurés.
9. **Message d'erreur** : `state.error` est affiché tel que fourni par le
   backend (message utilisateur déjà exposé par le plateau existant) ; aucune
   trace, chemin ou secret n'est ajouté. Le libellé est classé par
   `failureKind`.
10. **Deux tests existants corrigés** :
    - `vault-ui-behaviors.spec.ts` attendait `ajouté(s) à la file d'attente`,
      alors que le code (commit `36c3dc5`) affiche déjà « 1 fichier ajouté… » :
      l'assertion a été alignée sur le comportement livré.
    - le même fichier cherchait `2.0 Ko` sans portée ; le nouveau widget de
      sidebar affiche légitimement ce volume en plus de la synthèse du coffre.
      L'assertion est désormais limitée à la barre latérale.

## 6. Sécurité et intégrité

- Aucun endpoint, contrat API, jeton ou mécanisme d'authentification modifié.
- Aucun client API parallèle : `transferDeps` réutilise `lib/api.ts` et
  `putToPresignedUrl`.
- Aucun secret/token dans le DOM ; pas de chemins internes ni de traces.
- Les contrôles d'accès restent côté serveur ; masquer un bouton n'est jamais
  utilisé comme contrôle.
- L'annulation ne supprime pas les fichiers publiés ; elle appelle l'`abort`
  backend et laisse le serveur décider du nettoyage.
- Le succès n'est jamais affiché avant la confirmation du commit.
- La file en mémoire est vidée au changement de session.

## 7. Tâches restantes (hors périmètre)

- Historique de transferts serveur (nouvel endpoint) si une vraie page
  « historique » est souhaitée.
- Virtualisation si des milliers de lignes deviennent courantes.
- Filtre par plage de dates si le backend expose une date de création de
  session.
- Export de rapport de transfert.
- Intégration des e2e au CI (le workflow actuel ne lance que build + pytest).
- Décision produit sur une généralisation du thème sombre AURA au reste de
  l'application.

## 8. Backlog publié et lot A

Backlog complet : [`transfers-backlog.md`](transfers-backlog.md). 24 issues publiées,
regroupées en cinq jalons GitHub :

| Jalon | Issues |
|---|---|
| Transferts A — Quick wins (M22) | #224 → #231 |
| Transferts B — Pilotage (M23) | #232 → #236 |
| Transferts C — Liste & reprise (M24) | #237 → #241 |
| Transferts D — Qualité & CI (M25) | #242 → #245 |
| Transferts E — Backend & produit (M26) | #246 → #247 |

### Lot A — implémenté

- **A1 #224** — dialogue d'annulation avec compteurs réels (envois en cours, fichiers
  en attente, fichiers déjà vérifiés conservés).
- **A2 #225** — position dans la file (« Prochain dans la file », « 2e dans la file »).
- **A3 #226** — bandeau « Connexion perdue », reprise automatique au retour du réseau,
  bouton « Réessayer » honnête (refus explicite si toujours hors-ligne).
- **A4 #227** — lien « Tout voir » dans le plateau et action « Voir » dans le toast de
  fin d'import.
- **A5 #228** — sélection par statut (échecs / actifs / en attente) depuis le menu
  secondaire, avec compteurs.
- **A6 #229** — en-tête de tableau sticky sous la topbar ; suppression du clipping qui
  cassait le sticky et les menus de ligne.
- **A7 #230** — copie du nom du fichier et du message d'erreur (presse-papiers, retour
  toast, repli si l'API est refusée).
- **A8 #231** — titre d'onglet dynamique `(N) Transferts — AURA Vault` /
  `(N échec) …`, restauré en quittant la page.

Cinq tests e2e supplémentaires couvrent ces comportements (titre/position/annulation/
sélection, copie, lien depuis le plateau, hors-ligne, sticky). Suite complète :
**151 tests OK**, build OK.

## 9. Lot B — implémenté (PR #252)

- **B1 #232** — filtres, recherche, type, taille et tri dans l'URL ; retour/avant
  restaure la vue ; la saisie est debouncée et n'empile pas l'historique.
- **B2 #233** — surlignage de 900 ms d'une ligne qui atteint Terminé ou Échec,
  désactivé avec `prefers-reduced-motion`.
- **B3 #234** — historique de débit sur 60 s (1 point/seconde) et sparkline dans
  la tuile « Débit actuel ».
- **B4 #235** — durée écoulée, débit moyen et ETA basé sur un débit lissé (EMA),
  avec état « Estimation instable ».
- **B5 #236** — horodatage d'ajout mémorisé par le provider, y compris pour les
  fichiers encore en attente.

Vérifications : `tsc`, build, **154 tests Playwright**. Les baselines visuelles
ont été régénérées (sparkline + durée). Le lot B est mergé dans `main` (PR #252)
et déployé (run `40000979514`), avec CSP vérifiée.

> **Note d'exploitation** : le conteneur `app` sert `./web/dist` en bind mount.
> Un `npm run build` exécuté sur l'hôte met donc immédiatement le nouveau
> bundle à disposition de la production, avant même le workflow de déploiement.
> Toujours déclencher le déploiement après un build local, ou considérer ce
> build comme une mise en production de fait.

## 10. Lot C — implémenté (PR #253)

- **C1 #237** — tri par clic sur les entêtes (Nom, Taille, Statut) avec `aria-sort`,
  flèches et synchronisation URL.
- **C2 #238** — colonnes adaptatives : vitesse masquée sous 1150 px, taille sous
  1000 px, puis cartes sous 760 px, sans débordement horizontal.
- **C3 #239** — bandeau « Import interrompu » quand le journal IndexedDB contient
  des entrées, avec bouton vers l'import existant.
- **C4 #240** — export CSV de la vue courante (séparateur `;`, BOM UTF-8,
  échappement RFC 4180), nom horodaté.
- **C5 #241** — virtualisation par fenêtre au-delà de 200 lignes, hauteurs
  mesurées, spacers, `aria-rowcount`/`aria-rowindex`, panneaux d'erreur à hauteur
  fixe.

Vérifications : `tsc`, build, **159 tests Playwright** (5 tests dédiés au lot C).
Le lot C est mergé dans `main` (PR #253) et déployé (run `40008115267`), avec CSP vérifiée.

## 11. Lot D — livré (PR #255)

- **D1 #242** — Vitest + `npm run test:unit`, 25 tests sur `model.ts` et
  `format.ts` (statuts, périmètres, tri, ETA, formats, cas limites).
- **D2 #243** — job `e2e` dans `web.yml` (API en mémoire + Vite + Playwright,
  artefact `test-results` en échec) et tests unitaires dans le job existant.
  Le mot de passe admin du job a été aligné sur celui utilisé par les tests.
- **D3 #244** — suite axe sur Login, Fichiers, Transferts (vide) et
  Administration ; correction des contrastes des en-têtes triables, des
  libellés de métriques et de l'avatar, et de la structure ARIA du catalogue.
- **D4 #245** — annonces lecteur d'écran discrètes sur les transitions de
  statut et les changements réseau, throttlées à 2 s, sans annonce par octet.

Les baselines visuelles restent un contrôle local : elles dépendent du
rasterizer et des polices de l'hôte de référence, donc le job CI les ignore
(`test.skip` sous `CI`) et exécute le reste de la suite. Le lot D est sur
`main` mais n'a pas été déployé.
