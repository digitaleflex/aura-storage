# Plateforme de livres audio — dossier de conception

**Version :** 0.2 — conception acceptée, fondation Lot 1 implémentée
**Date :** 2026-11-20
**Statut :** **recommandations D-01 à D-12 acceptées par l'utilisateur** ; une **fondation Lot 1** est implémentée dans `audiobook/` (domaine, services, repository PostgreSQL, API FastAPI, tests). Le service n'est **pas encore déployé/intégré** à la stack Compose et ne remplace pas le portail public AURA en production.
**Périmètre :** les 12 domaines du brief, leurs règles, invariants, cycles de vie,
scénarios de défaillance, permissions, tests d'acceptation, plan de réalisation,
registre des risques, revue de conception et état d'implémentation Lot 1.

---

## 1. Pourquoi ce dossier existe

Le dépôt contient aujourd'hui deux choses différentes :

1. **AURA Storage** — une plateforme de stockage et de diffusion d'objets
   (SeaweedFS/S3, catalogue PostgreSQL/SQLite, presigned URLs, intégrité,
   lifecycle, audit, partages). C'est une infrastructure solide, mais ce n'est
   pas un backend de livres audio.
2. **Le portail public de livres audio** — un prototype construit au-dessus
   d'AURA (`api/public_ui.py`, `/api/public/*`, `listen_progress`,
   `audio_chapters`, `collections`). Il permet de se connecter avec Google,
   parcourir des « packs publiés » et écouter des pistes. Il ne gère ni les
   œuvres, ni les droits, ni les achats, ni les appareils, ni les conflits de
   progression.

Le brief demande de passer d'un backend CRUD à un **système métier**. Ce dossier
formalise cette cible avant toute écriture de code.

> **Règle de gouvernance appliquée :** aucune règle commerciale, juridique ou
> opérationnelle n'est inventée. Les points inconnus sont listés comme décisions
> à prendre dans [`09-design-review-and-decisions.md`](09-design-review-and-decisions.md).
> Le design est proposé, pas validé.

---

## 2. Recommandation architecturale en une page

### 2.1 Séparer le domaine « livres audio » d'AURA Storage

**Recommandation :** traiter la plateforme de livres audio comme un **contexte
borné distinct** d'AURA.

- **AURA** reste la **couche de stockage et de diffusion** : objets binaires,
  checksums, lifecycle, presigned URLs, audit d'accès, quotas, HLS.
- **Audiobook** possède les **utilisateurs auditeurs**, le **catalogue
  éditorial**, la **bibliothèque**, les **droits**, les **abonnements et
  paiements**, l'**écoute**, les **téléchargements**, la **découverte**, les
  **notifications**, l'**administration** et l'**analytique**.

AURA ne doit pas devenir le backend commercial : ses propres documents
(`docs/DATA-MODEL.md`) indiquent qu'il ne gère pas les utilisateurs, abonnements
ou paiements de la plateforme consommatrice. Le portail actuel est une exception
historique, pas un modèle à étendre.

### 2.2 Deux options de déploiement

| Option | Description | Avantages | Inconvénients |
|---|---|---|---|
| **A. Service séparé (recommandé)** | `audiobook-api` + base PostgreSQL dédiée ; appelle AURA via une identité de service | Frontières nettes, commerce isolé, permissions minimales, extraction/scale indépendants | Un conteneur et une base de plus à exploiter |
| **B. Monolithe modulaire** | Module `audiobook` dans le dépôt/processus API actuel, schéma et tables séparés | Moins d'exploitation, plus simple pour une très petite équipe | Risque de couplage, support SQLite/PostgreSQL coûteux, frontières plus fragiles |
| **C. Étendre le portail public** | Ajouter droits/paiements dans `api/main.py` et `public_ui.py` | Apparemment rapide | **Rejeté** : mélange stockage, identité opérateur, commerce et écoute ; viole les invariants |

Le dossier est écrit pour être **indépendant du choix A/B**. La recommandation
reste A, avec B acceptable comme étape transitoire si les règles de séparation
sont strictes (schéma dédié, aucune table partagée, adaptateur `StoragePort`).

### 2.3 Le point critique : `/m/{slug}` n'est pas un contrôle d'accès

Depuis le 2026-11-24, `GET /m/{slug}` exige un **compte premium** par défaut
(`AURA_PUBLIC_REQUIRE_PREMIUM=1`, plus `AURA_PUBLIC_MEDIA_REQUIRE_AUTH=1`). Un visiteur
anonyme reçoit 401, un compte gratuit 403 : le livre entier n'est plus téléchargeable
par quiconque possède le slug. Les intégrations publiques de confiance restent possibles
avec `AURA_PUBLIC_MEDIA_OPEN_SLUGS=slug-1,slug-2` (décision explicite de l'opérateur).
L'extrait anonyme, lui, est limité à 1 minute côté serveur (`/extrait/{id}`) et les liens
de partage `/s/{token}` sur un objet publié suivent la même règle premium (404 uniforme
en cas de refus).

**Décision de conception :** aucun contenu payant ou soumis à des droits ne doit
être exposé via `/m/{slug}`. L'API audiobook prend la décision d'accès, puis
demande à AURA une URL courte via son identité de service. Le slug public
d'AURA reste réservé aux previews explicitement gratuites et non sensibles.

**Garde-fou provisoire (2026-11-24, issue #295) :** tant que l'API audiobook ne délivre
pas encore ses propres URL signées, `AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS` permet de
déclarer les slugs dont le contenu ne doit plus être servi par `/m/{slug}` (réponse
404, sans présign ni événement de lecture). Ce n'est pas un contrôle d'accès : c'est
un interrupteur d'endiguement. La décision d'accès définitive reste celle de l'API
audiobook via son identité de service.

**Mécanisme livré (issue #301) :** une identité de service disposant de `objects:write`
peut appeler `POST /api/v1/objects/{oid}/public-access` après sa décision d'accès.
L'API renvoie un token à usage de capability et l'URL courte `/a/{token}` ; seul le
SHA‑256 du token est stocké (`public_access_grants`), jamais le token en clair ni dans
les logs. `DELETE /api/v1/objects/{oid}/public-access` révoque tous les grants d'un
objet, et le sweep périodique purge les grants expirés. Les compteurs de débit publics
sont désormais partagés en base (`public_rate_counters`) : plusieurs workers API
appliquent la même limite.

### 2.4 Le modèle d'écoute : événements + projection, pas un champ « position »

Le prototype stocke une seule ligne `(user_id, object_id, position_seconds)` et
l'écrase à chaque sauvegarde (`api/db.py:175-190`). C'est une erreur structurelle
pour le multi-appareils : une vieille position peut écraser une récente.

**Décision de conception :**

- les **événements d'écoute** sont append-only, idempotents et ordonnés par
  session ;
- la **progression courante** est une projection avec version et session
  active ;
- une position ancienne est conservée comme historique mais **ne remplace pas**
  la progression valide ;
- un retour en arrière volontaire est un événement `seek` de la session active,
  pas une position « plus basse » à ignorer ;
- la fin d'un livre est un fait distinct de la position (`completed_at`).

Le détail est dans [`02-domain-model.md`](02-domain-model.md) et
[`04-lifecycles.md`](04-lifecycles.md).

---

## 3. Audit express de l'existant

| Domaine | Ce qui existe | Verdict pour la cible |
|---|---|---|
| Identité | `users` avec `role`, `oauth_provider`, `oauth_sub`, `email` ; sessions ; Google OIDC | Insuffisant : pas de statut de compte, suppression, appareils, préférences, changement d'e-mail |
| Catalogue | `objects` = fichiers ; `collections` = packs ; `audio_chapters` ; auteur/titre déduits du nom de fichier | Insuffisant : pas d'œuvre, édition, enregistrement, contributeurs, langues, séries, droits |
| Bibliothèque | Aucune bibliothèque personnelle, favoris ou collections privées | À construire |
| Fichiers | Pipeline objet robuste (checksum, taille, SSE, lifecycle) ; ffprobe/ffmpeg hors ligne | Bon socle, mais pas de validation audio à l'ingestion ni de quarantaine éditoriale |
| Écoute | `listen_progress` en last-write-wins ; pas de session, appareil, événement, chapitre courant, reprise fiable | À reconstruire |
| Droits | La publication (`published_at`) est le seul gate ; `/m/{slug}` est public | Critique : aucun droit d'accès, licence, territoire ou fenêtre temporelle |
| Abonnements / paiements | Aucun | À construire |
| Téléchargements | `download-intent` générique AURA | Pas de grant lié à l'appareil, de lease hors ligne ou de révocation |
| Découverte | Filtre `q`, facettes déduites du nom de fichier | Insuffisant : pas de classement, popularité, recommandations |
| Notifications | Aucune | À construire |
| Administration | Administration AURA des objets/espaces | Pas d'administration éditoriale, droits, remboursements, modération |
| Analytique | Compteurs objet et egress estimé | Pas d'événements d'écoute, complétion, revenus, rétention |

**Points forts à réutiliser :** intégrité et checksum AURA, idempotence des
uploads, presigned URLs, audit JSONL, isolation par espace, HLS, révisions,
procédures de sauvegarde/restauration.

**Points à ne pas réutiliser tels quels :** `users` comme identité auditeur,
`collections` comme œuvre, `objects` comme livre, `listen_progress` comme
progression, `published_at` comme droit d'accès, `/m/{slug}` comme diffusion
protégée.

---

## 4. Les livrables

| # | Document | Contenu |
|---|---|---|
| 01 | [Cartographie des domaines](01-domain-map.md) | 12 domaines, types, dépendances, frontières, intégration AURA |
| 02 | [Modèle de domaine](02-domain-model.md) | Dictionnaire des concepts, agrégats, relations, identifiants, migration |
| 03 | [Règles et invariants](03-rules-and-invariants.md) | Catalogue de règles par domaine, 22 invariants testables |
| 04 | [Cycles de vie](04-lifecycles.md) | États, transitions autorisées/interdites, guards, effets |
| 05 | [Permissions](05-permissions.md) | Acteurs, rôles, matrice, séparation des devoirs, audit |
| 06 | [Scénarios de défaillance](06-failure-scenarios.md) | Doublons, désordre, concurrence, pannes, récupération |
| 07 | [Tests d'acceptation](07-acceptance-tests.md) | Matrice Given/When/Then, tests de concurrence, sécurité, migration |
| 08 | [Plan de réalisation et risques](08-delivery-plan-and-risks.md) | Lots, gates, migration du portail, registre des risques |
| 09 | [Revue de conception et décisions](09-design-review-and-decisions.md) | Résultats de revue, décisions acceptées, traçabilité, gate |
| 10 | [Implémentation Lot 1](10-lot1-implementation.md) | Périmètre livré, exécution, limites, conditions restantes |
| 11 | [Implémentation Lot 2](11-lot2-implementation.md) | Droits/territoires/contrats, entitlements, résolveur d'accès, historique/stats, refus |
| — | [Runbook & administration](RUNBOOK.md) | Configuration, bootstrap, opérations, sécurité, incidents |

**Ordre de lecture recommandé :** 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11.
Pour une revue rapide : ce README, puis 09, 10 et 11. Pour l'exploitation : 10/11 puis le runbook.

---

## 5. Ce que ce dossier ne fait pas

- Il ne choisit pas à votre place le modèle commercial, le prestataire de
  paiement, le DRM, la politique de contenu personnel ou la politique de
  rétention légale.
- Il ne contient pas de code de production, de migration ou de schéma exécutable.
- Il ne remplace pas une revue juridique (droits d'auteur, RGPD, TVA, conditions
  de vente, contenu fourni par l'utilisateur).
- Il ne prétend pas que le prototype actuel est prêt pour des livres payants.

---

## 6. Condition de passage au déploiement

Les recommandations **D-01 à D-12** sont acceptées et une **fondation Lot 1** est
implémentée (voir [`10-lot1-implementation.md`](10-lot1-implementation.md)),
mais le service **ne doit pas être exposé en production** tant que les conditions
opérationnelles, sécurité et conformité ne sont pas satisfaites :

1. **Intégration AURA réelle** : identité de service dédiée, privilèges minimaux,
   `AURA_API_BASE_URL`/jeton configurés (pas de fake storage hors dev).
2. **D-08 effectif** : migration/gel du prototype, retrait de tout accès payant
   via `/m/{slug}`, gestion des slugs/previews.
3. **Auth durcie** : `AUDIOBOOK_DEV_AUTH` désactivé, Google OIDC configuré,
   admin bootstrap remplacé par un contrôle d'accès conforme.
4. **D-11 complet** : limites globales appareils/sessions appliquées et auditables.
5. **D-10/D-12** : rétention/anonymisation paramétrées, sauvegarde indépendante
   et **test de restauration** validés avant toute ouverture payante.
6. **Revue sécurité/juridique** : threat model, inventaire de migration, CGV/RGPD,
   droits d'auteur/contenu importé, fiscalité/paiement sandbox avant Lot 3.

Le périmètre vertical livré couvre : **identité auditeur + catalogue publié +
bibliothèque + décision d'accès auditée + écoute/progression multi-appareils
avec résolution de conflits**, sans paiement ni offline téléchargeable.
