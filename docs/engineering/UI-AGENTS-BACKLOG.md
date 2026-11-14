# Backlog des agents UI (exécution nocturne)

Source : `docs/engineering/UI-PLAN-PRO-2026-11.md`. Ce fichier est l'état
partagé des agents : chacun prend le **premier paquet non coché de son rôle**,
le livre en une PR, coche la case dans cette même PR, puis s'arrête.

## Règles communes (non négociables)

1. **Un paquet = une PR**, petite et relisible. Branche `agents/<id>-<slug>`
   créée depuis `origin/main` à jour. Ne jamais pousser sur `main`.
2. **Périmètre interdit** : `api/`, `scripts/`, `deploy/`, `config/`,
   `docker-compose.yml`, `.github/workflows/`, `web/src/lib/transfer*.ts`
   (moteur de transfert), routes et contrats d'API. Seuls `web/`, `docs/` et
   `landing/` peuvent changer.
3. **Vérifier avant d'ouvrir la PR** : `cd web && npm ci && npm run build &&
   npm run test:unit`. Mettre à jour les tests e2e (`web/e2e/`) que le changement
   rend faux ; ne jamais supprimer, ignorer (`skip`) ni affaiblir un test pour
   passer au vert.
4. **PR** : gabarit `.github/PULL_REQUEST_TEMPLATE.md`, titre `type(ui): …`,
   cases du backlog cochées dans la même PR. Pied de page d'attribution Claude.
5. **Merge** : attendre que **toutes** les vérifications soient vertes :
   `unit-tests`, `e2e` (workflow `CI Tests (PR)`), `config` et `api-postgres`
   (workflow `Validate storage configuration`), et que la PR soit fusionnable.
   Alors seulement : merge **squash**, puis supprimer la branche.
   *(L'exception sur `api-postgres`, en vigueur du 2026-11-12 au 2026-11-14,
   est retirée : le job est de nouveau vert depuis la correction de
   `cancel_import_job`. Un job rouge, quel qu'il soit, bloque.)*
6. **Si rouge** : lire le journal, corriger, repousser (2 tentatives
   maximum). Toujours rouge → fermer la PR, marquer le paquet `⛔ bloqué :
   <raison>` dans le backlog (PR docs séparée, mergée si verte) et passer au
   rôle suivant. Ne jamais forcer, ne jamais contourner la CI.
7. **Maximum 2 PR par agent et par nuit.** Pas de refactor hors paquet. Aucun
   secret, aucune donnée réelle, aucun déploiement (le workflow de déploiement
   est manuel et n'est jamais lancé par un agent).
8. Le français est la langue de l'interface, des commits et des PR.
9. En cas de doute sur un choix produit : ne pas improviser. Marquer
   `❓ décision : <question>` et passer au paquet suivant.

Légende : `[ ]` à faire · `[x]` fait · `⛔` bloqué · `❓` en attente de décision.

---

## Rôle BUILDER — nouveaux composants et écrans

- [ ] **B1** `PageHeader` (h1, sous-titre, actions) + adoption sur Paramètres, Aide, Corbeille, Partages, Tableau de bord
- [ ] **B2** `EmptyState`, `ErrorState` (avec « Réessayer »), `LoadingState` ; remplacer `dashboard-error`, `shares-error`, `trash-error`
- [ ] **B3** Hook `useDocumentTitle` : titre d'onglet par route (`Fichiers · AURA Vault`)
- [ ] **B4** Menu compte dans la barre du haut (avatar → thème, densité, déconnexion) ; retirer les boutons nus. Cible : maquette « AURA Vault — Nouvelle interface » (la recherche, la barre latérale flottante et la feuille sont déjà en place)
- [x] **B5** Fichiers : supprimer la barre « Vue de contrôle » (fait avec la direction v3)
- [ ] **B6** Fichiers : filtres en pastilles (Tous, Images, Documents, Autres, À traiter), filtres avancés repliés
- [ ] **B7** Fichiers : actions de ligne au survol/focus (Télécharger, Partager, ⋯)
- [ ] **B8** Barre latérale : jauge d'espace fine ; retirer `VaultOverview` de la page Fichiers (détails au Tableau de bord)
- [ ] **B9** Transferts : une action à un seul endroit (retirer les doublons dans les dialogues)
- [ ] **B10** Tableau de bord : états vides, `aria-label`, `tabular-nums`, graphiques accessibles
- [ ] **B11** Partages : état (actif / expire dans N jours / expiré), copie du lien en toast, révocation avec confirmation nommée
- [ ] **B12** Corbeille : durée de conservation en tête, restaurer avec toast « Annuler », purge avec confirmation
- [ ] **B13** Paramètres : thème, densité, sessions ; zone « Danger » séparée
- [ ] **B14** Aide : titre « Aide », ancres, liste des raccourcis ; Diagnostic réseau déplacé sous Aide/Paramètres
- [ ] **B15** Connexion : erreur liée au champ (`aria-describedby`), focus automatique, afficher/masquer le mot de passe
- [ ] **B16** Onboarding : indicateur d'étape, « Passer » toujours visible
- [ ] **B17** Administration : un onglet = une route paresseuse (le `hash` actuel reste compatible)

### Direction v3 (maquette « AURA Vault — Nouvelle interface »)

Socle déjà livré (`web/src/vault-v3.css`) : barre latérale flottante, feuille
arrondie, recherche globale dans la barre du haut, rayons, bandeau de synthèse.
Reste, dans l'ordre :

- [ ] **V1** Fichiers : filtres en pastilles (Tous, Images, Documents, Audio et archives, À traiter) à la place des listes déroulantes
- [ ] **V2** Fichiers : dossiers en cartes compactes au-dessus de la liste
- [ ] **V3** Fichiers : panneau de détails à droite (empreinte SHA-256, étapes de vérification, Télécharger / Partager / Corbeille) à la place de la fenêtre
- [ ] **V4** Fichiers : actions de ligne au survol ou au focus (Télécharger, Partager, ⋯)
- [ ] **V5** Barre latérale : bloc d'espace utilisé (jauge) conforme à la maquette ; retirer `VaultOverview` de la page Fichiers
- [ ] **V6** Transferts : bandeau de synthèse (anneau, débit, temps restant, échecs) et lignes avec barre de progression, bouton plein unique « Ajouter des fichiers »
- [ ] **V7** Connexion : mise en page en deux panneaux
- [ ] **V8** Mobile : barre d'onglets en bas (Fichiers, Transferts, Partagés, Corbeille) et bouton « Importer » flottant
- [ ] **V9** Police des titres : ajouter Manrope en auto-hébergé (licence OFL) puis l'appliquer aux titres

## Rôle A11Y-TESTS — accessibilité et filet de tests

- [ ] **T1** Test axe (`@axe-core/playwright`) sur chaque route : Connexion, Fichiers, Transferts, Tableau de bord, Partages, Corbeille, Paramètres, Aide, Diagnostic, Admin
- [ ] **T2** Cibles tactiles 44 px : icônes de lignes, ×, menus (`--tap-target`)
- [ ] **T3** Boutons désactivés : `title` + `aria-disabled` expliquant pourquoi
- [ ] **T4** Transferts : région `aria-live="polite"` pour la progression ; noms accessibles sur les boutons d'icône
- [ ] **T5** Dialogues : `aria-labelledby` systématique, focus piégé puis restauré
- [ ] **T6** Tableaux → cartes sous 760 px sur tous les écrans
- [ ] **T7** Tests unitaires/composants des nouveaux composants (`PageHeader`, `EmptyState`, `ErrorState`, menu compte)
- [ ] **T8** Stories Storybook des composants communs

## Rôle NETTOYAGE — dette et suppressions

- [ ] **N1** Supprimer le gabarit Storybook par défaut (`web/src/stories/`), vérifier qu'aucun import ne subsiste
- [ ] **N2** `web/package.json` : description à jour ; ranger `AURA Vault File Dashboard.png` et `transfers-ui-audit-report.md` dans `docs/`
- [ ] **N3** Symboles texte restants (`×`, `✕`, `←`…) → `Icon`
- [ ] **N4** Migrer les alias `--graphite*` vers `--side*` puis les supprimer
- [ ] **N5** `transfers.css` : supprimer les règles `.shell-transfers` redondantes avec les règles globales ; garder le gabarit
- [ ] **N6** Un seul bloc de jetons pour le thème sombre
- [ ] **N7** Échelle typographique (12/13/14/16/20/24/32) : remplacer les `font-size` en px, fichier par fichier (≤ 1 fichier CSS par PR)
- [ ] **N8** Couleurs hex en dur → jetons, fichier par fichier
- [ ] **N9** `style={{…}}` en ligne hors largeurs de progression → classes
- [ ] **N10** Découper `ObjectsPage.tsx` : extraire un composant à la fois (≤ 400 lignes déplacées par PR)

## Rôle REVUE — qualité

Chaque nuit : lister les PR fusionnées depuis 24 h par les autres rôles, les
relire avec la skill `engineering:code-review` (correction, sécurité,
accessibilité, régressions visuelles évidentes). N'ouvrir une PR de correction
que pour un **vrai défaut** (jamais pour du style). Consigner le résultat dans
`docs/engineering/UI-AGENTS-LOG.md` (une ligne par PR relue : numéro, verdict).
