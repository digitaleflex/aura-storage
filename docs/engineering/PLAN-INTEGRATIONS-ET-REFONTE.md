# Plan — intégrations externes (clés, endpoints, webhooks) et refonte par étapes

Date : 2026-11-14. Décisions prises avec le propriétaire :

- **Usages visés** : envoyer des fichiers, afficher/servir des fichiers, recevoir des événements, piloter AURA par API.
- **Exposition** : API publique **par clé et par site** (domaine dédié, CORS limité, débit limité).
- **Méthode** : refonte **par étapes, en production** (petites PR testées, déployées au fil de l'eau, données conservées).

## 1. Ce qui existe déjà (à réutiliser, pas à refaire)

| Brique | État | Où |
|---|---|---|
| Clés machine (« identités de service ») | `Authorization: Bearer aura_<id>_<secret>`, scopes, durée de vie, rotation, révocation | `api/identity.py`, `POST /api/v1/admin/identities` |
| Cloisonnement | applications → espaces → buckets, quotas mensuels | `api/main.py` (routes `/api/v1/admin/*`) |
| Sites partenaires | onglet « Intégrations » (site + identité dédiée + TTL des URLs média) | `web/src/pages/AdminPage.tsx` |
| Liens publics | objets et dossiers (`/s/{token}`, `/f/{token}`) | `api/shares.py`, `api/folder_shares.py` |
| URLs média stables | patron « redirection stable côté serveur » documenté | `docs/STABLE-MEDIA-URLS.md` |
| Limitation de débit | M2M (`AURA_M2M_RATE_LIMIT`) et connexion | `api/config.py` |
| Audit | journal d'audit de toutes les actions | `api/audit.py` |
| Contrat | `docs/openapi.yaml` (87 chemins) | `docs/openapi.yaml` |

## 2. Ce qui manque

1. **Clés en libre-service** : seul un administrateur crée une clé, depuis Administration.
2. **API fermée aux navigateurs** : pas de routeur public pour l'API (choix de réduction de surface, `docs/GESTION-APIS.md`) et aucun CORS.
3. **Webhooks sortants** : rien ne prévient un outil externe quand un fichier est prêt, partagé ou supprimé.
4. **Liens de dépôt** : pas de moyen de laisser un tiers déposer un fichier sans compte.
5. **Documentation et clients** : pas de guide d'intégration, de SDK, d'exemples.
6. **Interface** : la direction « Vault » (v3) n'est livrée qu'en partie (`UI-AGENTS-BACKLOG.md`, V1–V9).

## 3. Principes de sécurité (non négociables)

- Une clé n'a **jamais** de scope `admin:*` (déjà refusé en 422 par l'API) ; en libre-service, seuls `objects:read`, `objects:write`, `objects:delete` sont offerts, jamais `objects:purge`.
- Le secret n'est affiché **qu'une fois** à la création ou à la rotation ; seul un hachage est stocké.
- Authentification **Bearer uniquement** sur l'API publique : pas de cookie de session, donc pas de CSRF inter-sites.
- CORS : jamais `*`. La liste d'origines autorisées est **propre à chaque clé** et la réponse ne renvoie que l'origine appelante si elle y figure.
- Webhooks : signature HMAC-SHA256, protection **SSRF** (refus des adresses privées, de `localhost` et des métadonnées cloud, après résolution DNS), HTTPS obligatoire, délais d'attente courts.
- Routes d'administration : **jamais** exposées sur le domaine public de l'API.
- Tout est audité (création, rotation, révocation, changement d'origines, livraison de webhook en échec).

## 4. Étapes

Chaque étape est livrée en une ou plusieurs PR, avec tests, migration `schema.sql` / `db_pg.py` / `migrations.py` si besoin, et mise à jour de `docs/openapi.yaml`. Une étape n'est déployée que si la précédente est en production et vérifiée.

### Étape 0 — Fondations (prérequis)
- Fusionner le correctif `api-postgres` ([PR 264](https://github.com/digitaleflex/aura-storage/pull/264)) et retirer l'exception de la règle 5 du backlog.
- Rédiger le modèle de menace de l'API publique (`docs/SECURITY.md`, section « API publique »).
- Choisir le domaine (`api.<domaine>`) et le consigner dans `docs/ENVIRONMENT-CONFIGURATION.md`.

### Étape 1 — Clés API en libre-service
- Table de clés rattachée à un propriétaire (utilisateur) et à son espace ; réutilise le format `aura_<id>_<secret>`.
- Routes humaines `GET/POST /api/v1/keys`, `POST /api/v1/keys/{id}/rotate`, `POST /api/v1/keys/{id}/revoke`, `PATCH /api/v1/keys/{id}` (nom, scopes, origines, expiration).
- Champs : nom, scopes limités, origines autorisées, expiration, **dernière utilisation**, débit propre.
- Page **« Clés & intégrations »** (hors Administration) : liste, création, secret affiché une fois, rotation, révocation en un clic, dernière utilisation.
- Tests : isolation entre utilisateurs, refus des scopes interdits, secret jamais relu, audit.

### Étape 2 — Exposition publique et CORS
- Routeur Traefik dédié `api.<domaine>` (TLS) ne publiant que les routes `/api/v1/objects`, `/api/v1/folders`, `/api/v1/keys` côté machine ; **aucune** route `/admin`.
- Middleware CORS applicatif : origine autorisée = celles de la clé qui s'authentifie ; prévol `OPTIONS` géré sans authentification ; en-têtes `Vary: Origin`.
- Limitation de débit **par clé** (application) en plus d'une limite par IP au bord (Traefik).
- Variables : `AURA_PUBLIC_API_DOMAIN`, `AURA_PUBLIC_API_RATE_LIMIT`.
- Tests : origine refusée, origine acceptée, prévol, clé révoquée, dépassement de débit.
- **Action manuelle du propriétaire** : enregistrement DNS de `api.<domaine>` ; je ne touche ni au DNS ni au déploiement sans accord.

### Étape 3 — Webhooks sortants
- Table `webhook_endpoints` (URL HTTPS, événements choisis, secret) et table d'**outbox** `webhook_deliveries` (état, tentatives, dernière réponse).
- Événements : `object.available`, `object.failed`, `object.deleted`, `object.restored`, `share.created`, `share.revoked`.
- Livraison par un worker : signature `X-Aura-Signature` (HMAC-SHA256 + horodatage), identifiant d'événement unique (idempotence côté récepteur), relances avec attente croissante, abandon après N essais.
- Journal des livraisons, **bouton « Rejouer »** et **« Envoyer un test »** dans l'interface.
- Tests : signature vérifiable, SSRF refusé, relance après échec, rejouer.

### Étape 4 — Envoyer et servir des fichiers depuis un site
- **Liens de dépôt** : lien à usage limité (durée, taille max, types) permettant à un tiers de déposer un fichier sans compte ; le fichier suit le cycle normal de vérification SHA-256.
- **URLs stables officielles** : route de redirection documentée (`/api/v1/objects/{id}/content`, clé requise) qui renvoie vers une URL présignée courte ; remplace le patron manuel de `STABLE-MEDIA-URLS.md`.
- Tests : taille/type refusés, lien expiré, redirection avec scope insuffisant.

### Étape 5 — Documentation et SDK
- Génération du client TypeScript depuis `docs/openapi.yaml` (paquet interne publié plus tard si souhaité) ; exemples cURL, JavaScript, Python.
- Onglet **« API »** dans l'Aide : démarrage en 5 minutes, scopes, CORS, webhooks (avec vérification de signature), erreurs, limites.
- Test d'intégration continue : le contrat OpenAPI doit rester synchrone avec les routes (`tests/test_openapi_contract.py`).

### Étape 6 — Refonte de l'interface
- Terminer la direction v3 (`UI-AGENTS-BACKLOG.md` : V1–V9) et les paquets B1–B17 (en-tête de page commun, états vides/erreur, menu compte, etc.).
- Nouvelle section **« Clés & intégrations »** : clés, origines, webhooks, journal de livraisons, liens de dépôt.
- Les agents nocturnes (4 déclencheurs) restent le moteur des paquets UI ; les étapes 1 à 5 (API) sont menées en séances supervisées, **pas** par les agents (périmètre `api/` interdit pour eux).

### Étape 7 — Durcissement et observabilité
- Usage par clé (requêtes, octets, erreurs) visible dans l'interface ; alertes sur pics et sur clé inutilisée depuis longtemps.
- Export du journal d'audit ; revue de sécurité indépendante avant toute ouverture large.

## 5. Risques et parades

| Risque | Parade |
|---|---|
| Clé volée utilisée depuis un autre site | Origines propres à la clé, expiration, révocation en un clic, débit par clé, alerte d'usage anormal |
| Webhook détourné vers le réseau interne (SSRF) | Résolution DNS puis refus des plages privées/locales/métadonnées, HTTPS seul, aucune redirection suivie |
| Fuite du secret de signature | Secret par endpoint, affiché une fois, rotation possible |
| Surface d'attaque accrue | Seules les routes machine sont publiées ; `/admin` reste interne ; revue de sécurité à l'étape 7 |
| Régression en production | Une étape déployée à la fois, migrations rétro-compatibles, tests de parité SQLite/PostgreSQL |
| Dérive du contrat d'API | Test de contrat OpenAPI obligatoire dans chaque PR d'API |

## 6. Ce qui demande une action ou un accord explicite

- DNS de `api.<domaine>` et ouverture du routeur public (étape 2).
- Tout **déploiement** (workflow manuel) : demandé à chaque étape.
- La **fusion** de toute PR touchant `api/` : sur demande du propriétaire.
