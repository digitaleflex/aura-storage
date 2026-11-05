# Backlog d'issues — Audit AURA Storage (2026-11-05)

Ce fichier recense **toutes les issues identifiées** lors de l'audit de l'application dans son état actuel. Il sert de référence pour créer les issues réelles sur GitHub.

## Comment utiliser ce document

- Chaque issue a un **ID** (ISSUE-001, ISSUE-002, …), une **priorité** (P0 à P3) et une **catégorie**.
- Les **P0** sont bloquants avant toute mise en production / import de données.
- Les **P1** sont nécessaires pour que l'application soit « complète » (usage utilisateur final).
- Les **P2** sont du polish / niveaux d'interface standards.
- Les **P3** sont spécifiées mais optionnelles ou différées.

Pour créer une issue sur GitHub, copiez le bloc correspondant et collez-le dans le formulaire "New issue".

---

## Tableau récapitulatif

| ID | Titre | Priorité | Catégorie | Statut |
|----|-------|----------|-----------|--------|
| ISSUE-001 | Corriger écart statut `aborted` (API + docs) | P0 | Backend / API | ✅ Résolu |
| ISSUE-002 | Test de sauvegarde et restauration indépendant | P0 | Infra / Déploiement | Ouvert |
| ISSUE-003 | SSH key-only + pare-feu host (pilote) | P0 | Sécurité / Infra | Ouvert |
| ISSUE-004 | Persistance après redémarrage du host (pilote) | P0 | Infra / Déploiement | Ouvert |
| ISSUE-005 | Implémenter API Import Jobs (`POST/GET /api/v1/import-jobs`, cancel) | P1 | Backend / API | Ouvert |
| ISSUE-006 | UI Tableau de bord (Dashboard) | P1 | Frontend / UI | Ouvert |
| ISSUE-007 | UI Partages (gestion des liens publics) | P1 | Frontend / UI | Ouvert |
| ISSUE-008 | UI Corbeille (restaurer / purger objets soft-deleted) | P1 | Frontend / UI | Ouvert |
| ISSUE-009 | UI Paramètres / compte utilisateur | P1 | Frontend / UI | Ouvert |
| ISSUE-010 | Action « Ouvrir le fichier » depuis la ligne de transfert terminée | P1 | Frontend / UI | Ouvert |
| ISSUE-011 | Recherche plein texte (au-delà du filtre `q` sous-chaîne) | P2 | Backend / API | Ouvert |
| ISSUE-012 | Filtre par plage de dates sur les transferts | P2 | Frontend / UI | Ouvert |
| ISSUE-013 | Export de rapport de transfert (au-delà du CSV vue courante) | P2 | Frontend / UI | Ouvert |
| ISSUE-014 | Virtualisation DOM de la liste des transferts | P2 | Frontend / Performance | Ouvert |
| ISSUE-015 | Généraliser le thème sombre AURA à toute l'application | P2 | Frontend / UI | Ouvert |
| ISSUE-016 | Widgets aide, notifications, menu de compte | P2 | Frontend / UI | Ouvert |
| ISSUE-017 | Corrections accessibilité (contrastes, aria-labels, régions live) | P2 | Frontend / Accessibilité | Ouvert |
| ISSUE-018 | Adapter FTPS (migration legacy, isolé) | P3 | Backend / API | Ouvert |
| ISSUE-019 | Intégration OpenBooks (catalogue/droits) | P3 | Intégration | Ouvert |
| ISSUE-020 | Intégration Axiom (supervision/opérations) | P3 | Intégration | Ouvert |
| ISSUE-021 | Multipart upload complet (lever `AURA_MULTIPART_ENABLED=0`) | P3 | Backend / API | Ouvert |

---

## Détail des issues P0 — bloquants avant production

### ISSUE-001 — Corriger écart statut `aborted` (API + docs) ✅ RÉSOLU

**Priorité :** P0  
**Catégorie :** Backend / API  
**Statut :** ✅ Résolu (2026-11-05)

**Contexte :** Le moteur de transfert écrit le statut `aborted` quand un intent en attente est annulé par le client. Ce statut était absent de certaines énumérations, causant un `422` sur `GET /api/v1/objects?status=aborted`.

**Modifications apportées :**
- [x] `api/main.py` — `"aborted"` déjà présent dans `ObjectStatus` (ligne 437)
- [x] `api/object_query.py` — `"aborted"` déjà présent dans `OBJECT_STATUSES` (ligne 21)
- [x] `docs/openapi.yaml` — `"aborted"` ajouté aux enums `status` (lignes 240 et 2247) ; ajouté `verifying`, `suspect`, `purging` pour cohérence complète avec le code
- [x] `docs/AUTHORIZATION-MATRIX.md` — ligne 58 : `GET /api/v1/objects` documente maintenant `aborted` comme valeur de filtre `status` valide

**Vérification :** `tests/test_openapi_contract.py` + `tests/test_objects_search_filter.py` = 31 tests passés.

**Fichiers modifiés :** `docs/openapi.yaml`, `docs/AUTHORIZATION-MATRIX.md`

---

### ISSUE-002 — Test de sauvegarde et restauration indépendant

**Priorité :** P0  
**Catégorie :** Infra / Déploiement  
**Statut :** Ouvert

**Contexte :** Une restauration indépendante réussie est un **gate obligatoire avant tout import de données originales** (voir `docs/BACKUP-RESTORE.md` et `docs/FONCTIONNALITES.md` §6). À ce jour, la procédure est documentée mais aucun test de restauration n'a été effectué sur le pilote.

**Critères d'acceptation :**
- [ ] Sauvegarde complète du catalogue PostgreSQL + données SeaweedFS effectuée
- [ ] Restauration sur un environnement isolé réussie
- [ ] Vérification d'intégrité des objets restaurés (checksums SHA-256)
- [ ] Procédure documentée et reproductible
- [ ] Gate QA-01 « Backup & restore » validé

**Fichiers concernés :** `docs/BACKUP-RESTORE.md`, `docs/QA-01-CHECKLIST.md`, `scripts/`

---

### ISSUE-003 — SSH key-only + pare-feu host (pilote)

**Priorité :** P0  
**Catégorie :** Sécurité / Infra  
**Statut :** Ouvert

**Contexte :** Sur le pilote VPS, le login SSH par clé n'est pas configuré (`~/.ssh/authorized_keys` absent) et l'état effectif du pare-feu (`ufw`/`nft`, `sshd -T`) est illisible sans sudo interactif. Seul le port 22 écoute.

**Critères d'acceptation :**
- [ ] Clé publique admin installée dans `~/.ssh/authorized_keys` (0600)
- [ ] Login SSH par clé testé en 2e session
- [ ] `sshd -T` et `ufw status verbose` inspectés et durcis
- [ ] Seuls les ports 80/443 publiés (Traefik) ; ports internes SeaweedFS non publiés
- [ ] Console de secours confirmée

**Fichiers concernés :** `docs/SERVER-PROFILE.md`, `docs/HOST-BOOTSTRAP-CHECKLIST.md`, `docs/SECURITY.md`

---

### ISSUE-004 — Persistance après redémarrage du host (pilote)

**Priorité :** P0  
**Catégorie :** Infra / Déploiement  
**Statut :** Ouvert

**Contexte :** La persistance des données (volumes Docker, PostgreSQL, SeaweedFS) après un redémarrage du host n'a pas été re-prouvée sur le pilote.

**Critères d'acceptation :**
- [ ] Redémarrage du host effectué
- [ ] Tous les conteneurs AURA redémarrent automatiquement
- [ ] PostgreSQL et SeaweedFS retrouvent leurs données intactes
- [ ] Tests fonctionnels (upload/download) passent après reboot

**Fichiers concernés :** `docker-compose.yml`, `docs/DEPLOYMENT.md`, `docs/REPRODUCIBLE-SETUP.md`

---

## Détail des issues P1 — fonctions manquantes pour application complète

### ISSUE-005 — Implémenter API Import Jobs

**Priorité :** P1  
**Catégorie :** Backend / API  
**Statut :** Ouvert

**Contexte :** Les routes `POST/GET /api/v1/import-jobs` et `…/{id}/cancel` sont spécifiées dans `docs/API-SPECIFICATION.md` mais **absentes du code** (`api/main.py` ne contient pas ces routes). Elles permettraient l'import en masse de fichiers avec suivi, retry et annulation.

**Critères d'acceptation :**
- [ ] `POST /api/v1/import-jobs` crée un job d'import (tenant, created_by, total_items)
- [ ] `GET /api/v1/import-jobs` liste les jobs avec statut et progression
- [ ] `GET /api/v1/import-jobs/{id}` retourne le détail d'un job
- [ ] `POST /api/v1/import-jobs/{id}/cancel` annule un job en cours
- [ ] Routes protégées par capacité appropriée (`objects:write` ou `admin:write`)
- [ ] Ajout dans `docs/openapi.yaml` et `docs/API-ROUTES-AUDIT.md`
- [ ] Tests hors-ligne dans `tests/`

**Fichiers concernés :** `api/main.py`, `api/schema.sql`, `api/migrations.py`, `docs/openapi.yaml`, `docs/API-SPECIFICATION.md`, `docs/DATA-MODEL.md` (entité ImportJob), `tests/`

---

### ISSUE-006 — UI Tableau de bord (Dashboard)

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** La navigation actuelle ne contient que : Fichiers, Transferts, Administration. Il n'existe aucune vue d'agrégation globale (espace, stockage utilisé, activité récente, alertes, quotas).

**Critères d'acceptation :**
- [ ] Nouvelle route `/dashboard` protégée par `RequireAuth`
- [ ] Entrée de navigation « Tableau de bord » dans `Layout.tsx`
- [ ] Widgets : espace de stockage, utilisation, quotas, transferts récents, alertes
- [ ] Données réelles depuis `GET /admin/usage` (admin) ou équivalent scoped (user/operator)
- [ ] Responsive, thème cohérent avec l'application

**Fichiers concernés :** `web/src/pages/DashboardPage.tsx`, `web/src/router.tsx`, `web/src/components/Layout.tsx`, `web/src/lib/api.ts`

---

### ISSUE-007 — UI Partages (gestion des liens publics)

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** L'API permet de créer des liens publics pour objets et dossiers (`POST /api/v1/objects/{oid}/share`, `POST /api/v1/folders/{fid}/share`, liste et révocation), mais il n'existe **aucune page UI** pour gérer ces partages (création, liste, expiration, révocation).

**Critères d'acceptation :**
- [ ] Nouvelle route `/shares` (ou section dans l'UI existante)
- [ ] Liste des liens publics actifs avec expiration et nombre d'utilisations
- [ ] Création d'un lien public pour un objet ou un dossier
- [ ] Révocation immédiate d'un lien
- [ ] Protection : seuls les créateurs peuvent révoquer leurs liens

**Fichiers concernés :** `web/src/pages/SharesPage.tsx`, `web/src/router.tsx`, `web/src/components/Layout.tsx`, `web/src/lib/api.ts`

---

### ISSUE-008 — UI Corbeille (restaurer / purger objets soft-deleted)

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** L'API supporte le soft delete (`DELETE /api/v1/objects/{oid}`), la restauration (`POST /api/v1/objects/{oid}/restore`) et la purge (`POST /api/v1/objects/{oid}/purge`, `POST /api/v1/objects/trash/empty`), mais il n'existe **aucun écran UI** pour la corbeille.

**Critères d'acceptation :**
- [ ] Nouvelle route `/trash` (Corbeille)
- [ ] Liste des objets soft-deleted avec date de suppression
- [ ] Bouton « Restaurer » par objet (appelle `POST /restore`)
- [ ] Bouton « Purger » (appelle `POST /purge`, nécessite master mode pour bulk)
- [ ] Vidage de la corbeille (`POST /trash/empty`)

**Fichiers concernés :** `web/src/pages/TrashPage.tsx`, `web/src/router.tsx`, `web/src/components/Layout.tsx`, `web/src/lib/api.ts`

---

### ISSUE-009 — UI Paramètres / compte utilisateur

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Aucun menu de compte, aucun écran de paramètres utilisateur n'existe (changement de mot de passe, préférences, thème, déconnexion explicite au-delà du bouton existant).

**Critères d'acceptation :**
- [ ] Menu utilisateur dans la navbar (avatar + nom)
- [ ] Route `/settings` ou `/profile`
- [ ] Changement de mot de passe
- [ ] Préférences (thème, langue, notifications)
- [ ] Déconnexion

**Fichiers concernés :** `web/src/components/Layout.tsx`, `web/src/pages/SettingsPage.tsx`, `web/src/router.tsx`

---

### ISSUE-010 — Action « Ouvrir le fichier » depuis la ligne de transfert terminée

**Priorité :** P1  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Sur la page Transferts, `QueueItem` n'expose pas l'`objectId`, donc il est impossible d'ajouter une action « Ouvrir le fichier » ou « Télécharger » depuis une ligne terminée. L'utilisateur doit retourner sur la page Fichiers pour retrouver son fichier.

**Critères d'acceptation :**
- [ ] Exposer `objectId` (ou un identifiant de lien public) sur `QueueItem` après commit confirmé
- [ ] Ajouter une action « Ouvrir / Télécharger » dans le menu de ligne des transferts terminés
- [ ] Redirection vers l'objet ou ouverture de l'URL présignée de download

**Fichiers concernés :** `web/src/lib/transfer.ts`, `web/src/lib/transferContext.tsx`, `web/src/components/transfers/TransferList.tsx`, `web/src/components/transfers/TransferDialogs.tsx`

---

## Détail des issues P2 — polish et niveaux d'interface standards

### ISSUE-011 — Recherche plein texte

**Priorité :** P2  
**Catégorie :** Backend / API  
**Statut :** Ouvert

**Contexte :** Actuellement, `GET /api/v1/objects` supporte uniquement `q` (sous-chaîne du nom affiché). La recherche plein texte est spécifiée dans `docs/API-SPECIFICATION.md` mais non implémentée.

**Critères d'acceptation :**
- [ ] Recherche plein texte sur `display_name` et métadonnées
- [ ] Paramètre de recherche dédié (ex: `search` ou extension de `q`)
- [ ] Performance acceptable sur le catalogue attendu

**Fichiers concernés :** `api/main.py`, `api/object_query.py`, `docs/openapi.yaml`, `docs/API-SPECIFICATION.md`

---

### ISSUE-012 — Filtre par plage de dates sur les transferts

**Priorité :** P2  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** La page Transferts filtre côté client uniquement. Il n'y a pas de filtre par plage de dates car le backend n'expose pas de date de création de session de transfert.

**Critères d'acceptation :**
- [ ] Filtre « Créé entre » (date début / date fin) sur la page Transferts
- [ ] Si nécessaire, endpoint backend pour date de création de session
- [ ] Persistance dans l'URL (partageable)

**Fichiers concernés :** `web/src/pages/TransfersPage.tsx`, `web/src/components/transfers/TransfersFilters.tsx`

---

### ISSUE-013 — Export de rapport de transfert

**Priorité :** P2  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Un export CSV de la vue courante existe déjà (lot C). Il manque un « rapport de transfert » plus complet (synthèse session, échecs classés, diagnostique, ETA historique).

**Critères d'acceptation :**
- [ ] Export rapport complet (PDF ou CSV enrichi)
- [ ] Inclure synthèse : total, réussis, échoués, annulés, débit moyen, durée
- [ ] Inclure détails par fichier avec erreur classée

**Fichiers concernés :** `web/src/lib/csv.ts`, `web/src/pages/TransfersPage.tsx`, `web/src/components/transfers/diagnostics.ts`

---

### ISSUE-014 — Virtualisation DOM de la liste des transferts

**Priorité :** P2  
**Catégorie :** Frontend / Performance  
**Statut :** Ouvert

**Contexte :** Le rendu est plafonné à 50 lignes + « Afficher plus ». Aucune virtualisation DOM. Si le catalogue dépasse quelques milliers de lignes, les performances se dégraderont.

**Critères d'acceptation :**
- [ ] Virtualisation des lignes au-delà d'un seuil (ex: 200 lignes)
- [ ] `aria-rowcount` / `aria-rowindex` maintenus
- [ ] Hauteurs variables mobile couvertes par des tests

**Fichiers concernés :** `web/src/components/transfers/TransferList.tsx`, `web/src/transfers.css`

---

### ISSUE-015 — Généraliser le thème sombre AURA à toute l'application

**Priorité :** P2  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert (décision produit en attente)

**Contexte :** Le thème sombre `.shell-transfers` est limité à `/transfers`. Les autres pages conservent leur thème actuel.

**Critères d'acceptation :**
- [ ] Décision produit validée (ne pas régresser les pages existantes)
- [ ] Thème sombre AURA appliqué à Fichiers, Administration, Dashboard, etc.
- [ ] Bascule clair/sombre utilisateur si pertinent

**Fichiers concernés :** `web/src/transfers.css`, `web/src/styles.css`, `web/src/components/Layout.tsx`

---

### ISSUE-016 — Widgets aide, notifications, menu de compte

**Priorité :** P2  
**Catégorie :** Frontend / UI  
**Statut :** Ouvert

**Contexte :** Aucun widget d'aide, aucun centre de notifications, aucun menu de compte n'existe (issues UI-AUDIT.md §P2).

**Critères d'acceptation :**
- [ ] Widget d'aide / documentation intégrée
- [ ] Centre de notifications (toasts persistants + historique)
- [ ] Menu de compte utilisateur

**Fichiers concernés :** `web/src/components/Layout.tsx`, `web/src/components/Toasts.tsx`

---

### ISSUE-017 — Corrections accessibilité (a11y)

**Priorité :** P2  
**Catégorie :** Frontend / Accessibilité  
**Statut :** Ouvert

**Contexte :** D'après `transfers-ui-audit-report.md` §4 et §9 :
- `--aura-text-muted: #748399` contraste sous AA sur fonds sombres (~3.6:1)
- Pas de `aria-label` sur les boutons de la toolbar ni les items de menu de ligne
- Pas de `aria-labelledby`/`aria-described` sur les dialogues natifs
- Pas de région live pour les mises à jour de progression/ETA
- Hit targets petits (icônes 14-16px)
- Boutons désactivés sans explication (`title`/`aria-disabled` absents)

**Critères d'acceptation :**
- [ ] Corriger le contraste de `--aura-text-muted` (ou limiter son usage décoratif)
- [ ] Ajouter `aria-label` sur tous les boutons et items de menu
- [ ] Ajouter `aria-labelledby`/`aria-described` aux dialogues
- [ ] Ajouter une région live pour progression/ETA
- [ ] Agrandir les hit targets à ≥ 44×44 px
- [ ] Ajouter `aria-disabled` et `title` explicites sur les boutons désactivés

**Fichiers concernés :** `web/src/transfers.css`, `web/src/components/transfers/*.tsx`, `web/src/components/Dialog.tsx`

---

## Détail des issues P3 — spécifiées, optionnelles / différées

### ISSUE-018 — Adapter FTPS (migration legacy)

**Priorité :** P3  
**Catégorie :** Backend / API  
**Statut :** Ouvert

**Contexte :** Adaptateur FTPS pour migration/legacy, spécifié dans `docs/API-SPECIFICATION.md` et `docs/FILE-TRANSFER.md`. Optionnel, isolé.

**Fichiers concernés :** `api/`, `docs/FILE-TRANSFER.md`

---

### ISSUE-019 — Intégration OpenBooks (catalogue/droits)

**Priorité :** P3  
**Catégorie :** Intégration  
**Statut :** Ouvert

**Contexte :** Intégration OpenBooks spécifiée dans `docs/ARCHITECTURE.md`. Futur, ne doit pas conditionner l'accès normal aux données.

**Fichiers concernés :** `docs/ARCHITECTURE.md`

---

### ISSUE-020 — Intégration Axiom (supervision/opérations)

**Priorité :** P3  
**Catégorie :** Intégration  
**Statut :** Ouvert

**Contexte :** Intégration Axiom spécifiée dans `docs/ARCHITECTURE.md`. Futur, ne doit pas conditionner l'accès normal aux données.

**Fichiers concernés :** `docs/ARCHITECTURE.md`

---

### ISSUE-021 — Multipart upload complet

**Priorité :** P3  
**Catégorie :** Backend / API  
**Statut :** Ouvert

**Contexte :** Le multipart est planifié (`AURA_MULTIPART_ENABLED=1` crée la session) mais désactivé par défaut (`=0`). Upload en une requête, plafonné à 5 GiB. Deux UNKNOWN documentés : disk reclaim après abort, et 10 000-part completion.

**Fichiers concernés :** `api/main.py`, `api/s3.py`, `api/transfer.py`, `docs/MULTIPART-UPLOAD-PLAN.md`

---

## Plan de démarrage recommandé (Sprint 1)

| Semaine | Focus | Issues |
|---------|-------|--------|
| S1 | P0 — Production readiness | ISSUE-001, ISSUE-002, ISSUE-003, ISSUE-004 |
| S2 | P1 — Cœur UI manquant | ISSUE-005 (API import jobs), ISSUE-006 (Dashboard), ISSUE-007 (Partages) |
| S3 | P1 — Suite UI | ISSUE-008 (Corbeille), ISSUE-009 (Paramètres), ISSUE-010 (Ouvrir fichier) |
| S4 | P2 — Polish + recette | ISSUE-011 à ISSUE-017 |

**Recommandation :** commencer par **ISSUE-001** (écart `aborted`, rapide à corriger) et **ISSUE-002** (gate backup obligatoire).

---

## Templates d'issues GitHub suggérés

Créez ces fichiers dans `.github/ISSUE_TEMPLATE/` pour standardiser la création d'issues :

- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `.github/ISSUE_TEMPLATE/task.yml`

Voulez-vous que je crée ces templates maintenant, ou préférez-vous que je commence par implémenter l'une des issues (par exemple ISSUE-001) ?