# Plan UI « pro » — tous les écrans (2026-11)

Objectif : une interface cohérente, sobre et sans élément inutile, sur les 11
routes. Légende : **[V]** vérifié dans le code · **[?]** à valider en
conditions réelles (aucune instance n'a été lancée pour cet audit).

Déjà fait sur la branche `claude/confident-pascal-wvhyp9` : jetons Transferts
unifiés (accent ambre), icônes SVG + navigation unique + Ctrl K, retours
d'action en toasts + barre de sélection collante.

---

## A. Transversal (à faire une fois, profite à tous les écrans)

| # | Action | Pourquoi | Prio |
|---|--------|----------|------|
| A1 | Composant `PageHeader` (h1, sous-titre, actions) | Chaque page a ses propres classes d'en-tête [V] | P0 |
| A2 | Composants `EmptyState`, `ErrorState` (avec « Réessayer »), `LoadingState` | `dashboard-error`, `shares-error`, `trash-error` sont trois copies du même bandeau [V] ; `Loading.tsx` existe mais est peu utilisé | P0 |
| A3 | Titre d'onglet par route (`Fichiers · AURA Vault`) | Seule la page Transferts met `document.title` [V] | P0 |
| A4 | Barre du haut : un menu compte (avatar → thème, densité, déconnexion) | Nom, rôle, densité, thème et Déconnexion sont 5 contrôles côte à côte [V] ; thème et densité ont déjà leur place dans Paramètres › Préférences | P0 |
| A5 | Échelle typographique (12/13/14/16/20/24/32) et fin des `px` en dur | 116 `font-size` en px dans `styles.css` [V] | P1 |
| A6 | Toutes les couleurs en jetons | 133 hex dans `styles.css`, 65 dans `aura-vault-refresh.css` [V] | P1 |
| A7 | Un seul bloc de jetons thème sombre | Les 28 jetons sont écrits deux fois (attribut + media query) [V] | P1 |
| A8 | Cibles tactiles 44 px partout (icônes de lignes, ×, menus) | `--tap-target` existe mais n'est pas appliqué aux icônes 14–16 px [V] | P1 |
| A9 | Boutons désactivés : toujours dire pourquoi (`title` + `aria-disabled`) | Constat du rapport Transferts [V] | P1 |
| A10 | Balayer les symboles texte restants (`×`, `✕`, `←`…) → `Icon` | Le registre `Icon.tsx` est prêt [V] | P1 |
| A11 | Tableaux → cartes sous 760 px sur tous les écrans, pas seulement Transferts | [?] | P1 |
| A12 | Test axe sur les 11 routes + contrôle manuel clavier/lecteur d'écran | `@axe-core/playwright` est déjà installé [V] | P1 |
| A13 | QA thème clair/sombre de chaque écran | Transferts a changé d'aspect à l'étape 1 [?] | P0 |
| A14 | Image de partage 1200×630 (`og:image`) | `og:image` pointe sur un SVG de favicon [V] | P2 |
| A15 | Découper `ObjectsPage` (4 200 l.), `AdminPage` (2 637 l.), `TransfersPage` (1 080 l.) en composants avec stories | Maintenabilité, tests visuels | P2 |
| A16 | Régression visuelle (Storybook + Chromatic, déjà en dépendances) | Empêche le retour des incohérences | P2 |

---

## B. Écran par écran

### Connexion (`/login`)
- Associer l'erreur au champ (`aria-describedby`), focus automatique sur l'identifiant. [?]
- Afficher/masquer le mot de passe. [?]
- Garder le panneau de gauche seulement ≥ 900 px ; le texte « chiffrés et vérifiés » doit rester une promesse vraie.

### Accueil / Onboarding (`/onboarding`)
- Indicateur d'étape (« 2 sur 4 »), bouton « Passer » toujours visible, jamais bloquant. [?]
- Ne s'affiche qu'une fois (`hasSeenOnboarding` existe).

### Fichiers (`/`)
- **Supprimer** la barre « Vue de contrôle » : elle répète le compte déjà affiché sous le titre [V].
- Déplacer le bloc d'usage (`VaultOverview`) hors de la page : jauge fine dans la barre latérale, détails dans Tableau de bord.
- Filtres en pastilles (Tous, Images, Documents, Autres, À traiter) au lieu de trois listes déroulantes ; filtres avancés repliés.
- Actions de ligne au survol/focus (Télécharger, Partager, ⋯) ; menu `RowMenu` pour le reste.
- « Mode maître » et bouton « ? » quittent l'en-tête : le premier va dans Paramètres/Admin, le second dans le pied de page de la liste (le raccourci `?` reste) [V].
- Clarifier ou renommer « Packs » (libellé non explicite) [?].
- Menu « Importer » (Des fichiers / Un dossier) qui ouvre directement le sélecteur ; garder le panneau pour la file d'attente. Demande des tests e2e à adapter.
- Vue grille : même qualité que la liste (état, sélection, actions) [?].

### Transferts (`/transfers`)
- Une action = un endroit : barre d'outils pour le lot, menu de ligne pour l'unité, retirer les doublons des dialogues (Pause/Reprise/Annuler/Réessayer existent en 3–4 endroits) [V, rapport existant].
- Région `aria-live="polite"` pour la progression ; noms accessibles sur les boutons d'icône.
- Vérifier anneau, étincelle et lignes annulées sur fond clair après l'étape 1 [?].
- Plateau flottant discret sur les autres pages (déjà `UploadTray`) : même langage visuel.

### Tableau de bord (`/dashboard`)
- Aucun état vide ni `aria-label` sur cet écran [V] : ajouter les deux.
- Graphiques accessibles (titre, valeurs en texte, palette 3 couleurs max, daltonisme) ; chiffres alignés (`tabular-nums`).
- Une seule carte « Espace » (aujourd'hui trois sections qui se recoupent) [?].

### Partages (`/shares`)
- Tableau avec état (actif, expire dans N jours, expiré), copie du lien en un clic avec confirmation en toast.
- Révocation avec confirmation nommée (« Révoquer le lien de rapport.pdf ? »).
- État vide avec une action claire (existe : à harmoniser via `EmptyState`).

### Corbeille (`/trash`)
- Dire la durée de conservation en tête de page.
- Restaurer en un clic avec toast « Annuler » ; « Purger » en danger avec confirmation.
- Deux `h1` dans le fichier (états vide / liste) : confirmer qu'un seul est rendu à la fois [?].

### Paramètres (`/settings`)
- Recevoir thème, densité, langue (si prévue), sessions actives (A4).
- Zone « Danger » séparée en bas (Déconnexion de tous les appareils).

### Aide (`/help`)
- Titre « Aide » (le nom du produit est déjà partout) ; ancres vers chaque section ; recherche seulement si > 10 entrées.
- Liste des raccourcis (`/`, Ctrl K, `?`, Suppr, Échap) au même endroit que la fenêtre `?`.

### Diagnostic réseau (`/diagnostic`)
- Outil de dépannage visible de tous dans le menu principal : le passer sous Aide ou Paramètres › Avancé [?].
- Résultat en phrase d'abord (« Votre connexion permet ~18 Mo/s »), détail technique replié.

### Administration (`/admin`)
- Un onglet = une route paresseuse (`/admin/overview`, `/admin/storage`…) au lieu d'un fichier de 2 637 lignes ; le `hash` actuel reste compatible [V].
- Tableaux denses : en-têtes fixes, tri, cartes sous 760 px.
- Deux `h1` dans le fichier (chargement / chargé) : un seul à l'écran [?].

### Éléments partagés
- **Dialog / Toasts / Aperçu** : focus piégé et restauré, Échap, `aria-labelledby` systématique (les dialogues Transferts n'en ont pas [V, rapport existant]).
- **Barre latérale** : sections (Espace · Outils), Paramètres et Aide en bas, jauge d'espace fine ; mode rail 68 px.

---

## C. À supprimer (inutile ou peu professionnel)

| Élément | Où | Raison |
|---------|----|--------|
| Gabarit Storybook par défaut (`Button`, `Header`, `Page` + CSS) | `web/src/stories/` | Fichiers générés par l'assistant, sans lien avec le produit [V] |
| Barre « Vue de contrôle » | `ObjectsPage.tsx:2280` | Doublon du sous-titre [V] |
| Description « neutral scaffold… No visual direction applied yet » | `web/package.json` | Périmée [V] |
| `AURA Vault File Dashboard.png` (1,4 Mo) et `transfers-ui-audit-report.md` à la racine | racine du dépôt | À ranger dans `docs/` [V] |
| Anciens alias `--graphite*` | `styles.css` | « Encore lus par l'administration et le login » : migrer vers `--side*` puis supprimer [V] |
| Alias `--aura-*` et règles `.shell-transfers` redondantes (`.btn-primary`, `.btn-ghost`, `.field`…) | `transfers.css` | Répètent désormais les règles globales ; garder seulement le gabarit [V] |
| Bandeaux d'erreur copiés (`dashboard-error`, `shares-error`, `trash-error`) | 3 pages | Remplacés par `ErrorState` [V] |
| Boutons Thème/Densité/Déconnexion nus dans la barre du haut | `Layout.tsx` | Menu compte (A4) [V] |
| Lien « Mode maître » dans l'en-tête de Fichiers | `ObjectsPage.tsx:2351` | Fonction de maintenance, pas d'usage courant [?] |
| `style={{…}}` en ligne hors largeurs de progression | 8 fichiers | Passer en classes [V] |
| Texte « Chargement… » brut | pages | `LoadingState`/squelettes [V] |

---

## D. Ordre proposé

1. **Socle (P0)** : A1, A2, A3, A4, A13, puis la liste C la plus simple (stories, package.json, rangement racine).
2. **Fichiers** : suppression de « Vue de contrôle », usage dans la barre latérale, filtres en pastilles, actions au survol.
3. **Transferts, Tableau de bord, Partages, Corbeille** : doublons d'actions, états vides, graphiques, confirmations.
4. **Paramètres, Aide, Diagnostic, Connexion, Onboarding** : petites pages, une demi-journée chacune.
5. **Dette (P1)** : A5–A12.
6. **Administration + découpage + tests visuels (P2)** : A14–A16.

Chaque étape reste livrable seule et ne touche ni l'API, ni les routes, ni le moteur de transfert.
