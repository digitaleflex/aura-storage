# AURA — Gestion des APIs (edge, sécurité, observabilité)

**Statut :** document d'architecture et d'exploitation. L'edge **existant** décrit ici
est vérifié dans `docker-compose.yml` et `config/traefik/README.md` (routage, TLS,
labels, réseaux). Les middlewares additionnels (rate-limit Traefik, forwardAuth,
en-têtes, métriques Prometheus) sont des **cibles documentées non activées** : ils ne
sont pas présents dans le Compose actuel. Aucune modification n'est apportée ici à
`docker-compose.yml` ni aux fichiers `config/`.

> Portée : ce document décrit la gestion **au bord** (Traefik) et l'outillage de
> documentation d'API. L'authentification et l'autorisation métier vivent dans l'API
> AURA (`api/authz.py`, voir `docs/AUTHORIZATION-MATRIX.md`) ; l'edge ne les remplace
> pas.

## 1. Architecture edge actuelle (vérifiée)

- **Traefik** publie seuls les ports hôte `80` et `443` (ACME Let's Encrypt HTTP-01).
  Le reste (SeaweedFS, PostgreSQL, API) n'expose **aucun port hôte**.
- Provider Docker avec `--providers.docker.exposedbydefault=false` : un service doit
  s'activer explicitement par labels ; les routes sont découvertes via le réseau
  `aura-edge`.
- Réseaux : `aura-edge` (bord) et `aura-storage-internal` (`internal: true`, storage).
- Routeurs existants (labels dans `docker-compose.yml`) :
  - `traefik-dashboard` → `api@internal`, protégé par BasicAuth (`dash-auth`), jamais
    publié en clair.
  - `aura-s3` → passerelle S3 SeaweedFS (`Host(S3_DOMAIN)`, port interne 8333).
  - `aura-s3-landing` → page statique pour `GET /` non signé sur `S3_DOMAIN`
    (priorité 1000).
  - `aura-app` → front nginx (`Host(APP_DOMAIN)`, racine, sans prefix/strip).
- **L'API AURA n'a pas de routeur Traefik** : elle est atteinte en same-origin via le
  proxy nginx de l'app (`app/nginx.conf` proxifie `/api/`). C'est un choix de
  réduction de surface : pas d'exposition publique directe de l'API de gestion.

### Extraits cohérents avec l'existant

Rappel de la forme des labels déjà en place (aucun secret ici, uniquement des
placeholders d'environnement) :

```yaml
labels:
  - traefik.enable=true
  - traefik.docker.network=aura-edge
  - traefik.http.routers.aura-app.rule=Host(`${APP_DOMAIN:?Set APP_DOMAIN in .env}`)
  - traefik.http.routers.aura-app.entrypoints=websecure
  - traefik.http.routers.aura-app.tls=true
  - traefik.http.routers.aura-app.tls.certresolver=le
  - traefik.http.services.aura-app.loadbalancer.server.port=80
```

## 2. Pourquoi Traefik et pas Kong / KrakenD

**Kong (gateway généraliste) — non retenu.** Kong Gateway OSS est, au moment de la
rédaction, **gelé** : la branche OSS s'arrête à **3.9.1** et l'effort de développement
se poursuit dans l'édition commerciale (plugins/Kong Konnect). Adopter Kong OSS
reviendrait à bâtir la gestion d'API sur une base qui ne reçoit plus de fonctionnalités
et dont la sécurité dépend d'une montée de version payante. En outre, Kong introduit un
magasin d'état (PostgreSQL) et des plugins supplémentaires, pour un besoin que Traefik
couvre déjà nativement (routage, TLS, labels Docker). *(Versions à re-vérifier avant
toute décision : cf. §7.)*

**KrakenD — fallback.** KrakenD 2.10 est un gateway **stateless** (configuration
déclarative, pas de base de données), orienté agrégation/versionnage d'API et
middlewares de bord (rate-limit, CORS, en-têtes). Il est un **candidat de repli** si un
jour l'API de gestion doit être exposée publiquement avec une politique de bord
dédiée (multi-version, quotas par consommateur), là où les labels Docker de Traefik ne
suffisent plus. Il n'est **pas** déployé aujourd'hui : cela ajouterait un composant et
un fichier de configuration de plus à auditer, pour un besoin non encore matérialisé.
*(Version à re-vérifier avant adoption.)*

**Traefik reste le choix par défaut** tant que le routeur, TLS et les quelques
middlewares de base du §3 couvrent le besoin : c'est le composant déjà déployé, sans
dépendance externe supplémentaire.

## 3. Middlewares Traefik utilisables (cibles, non activées)

Les middlewares se déclarent dans les labels d'un service, ou via le provider fichier.
Exemples cohérents avec le nommage `aura-*` existant ; **à n'activer qu'après revue**.

### Rate-limit au bord

Complémentaire (pas substitut) des limiteurs applicatifs de login/M2M
(`AURA_LOGIN_RATE_LIMIT`, `AURA_M2M_RATE_LIMIT`). Utile quand l'API devient exposée
publiquement.

```yaml
- traefik.http.middlewares.aura-ratelimit.ratelimit.average=100
- traefik.http.middlewares.aura-ratelimit.ratelimit.burst=50
# puis, sur la route concernée :
- traefik.http.routers.aura-app.middlewares=aura-ratelimit
```

### forwardAuth (délégation d'authentification au bord)

`forwardAuth` délègue la vérification d'une requête à un service d'authentification
externe. **Avertissement :** l'API AURA pratique déjà une autorisation serveur
default-deny par route (`api/authz.py`) ; un `forwardAuth` en amont ne doit **jamais**
remplacer cette autorisation, seulement la précéder (ex. protection du dashboard ou
d'une future route API publique). Ne pas configurer une route qui contournerait les
dépendances `authorize(...)` de l'API.

```yaml
- traefik.http.middlewares.aura-forwardauth.forwardauth.address=https://${AUTH_DOMAIN}/verify
- traefik.http.middlewares.aura-forwardauth.forwardauth.trustForwardHeader=true
# Ne jamais exposer le header de confiance à un pair non fiable.
```

### En-têtes de sécurité

L'API pose déjà `X-Content-Type-Options: nosniff` et `X-Frame-Options: DENY` pour ses
propres réponses (middleware in-app). L'edge peut compléter (HSTS, etc.) sans les
dupliquer côté app :

```yaml
- traefik.http.middlewares.aura-headers.headers.stsSeconds=31536000
- traefik.http.middlewares.aura-headers.headers.stsIncludeSubdomains=true
- traefik.http.middlewares.aura-headers.headers.contentTypeNosniff=true
- traefik.http.middlewares.aura-headers.headers.frameDeny=true
```

### BasicAuth / IP allow-list (dashboard et endpoints d'exploitation)

Le dashboard est déjà protégé par BasicAuth (`dash-auth`, `DASHBOARD_AUTH`). Pour un
endpoint d'exploitation, préférer une allow-list d'IP internes :

```yaml
- traefik.http.middlewares.aura-ipallow.ipallowlist.sourcerange=127.0.0.0/8,10.0.0.0/8
```

## 4. Observabilité

### Journaux d'accès (actifs)

`--accesslog=true` est déjà activé et `--log.level=INFO`. **Avertissement (repris de
`config/traefik/README.md`) :** les access logs peuvent contenir des query strings
portant des credentials (URLs présignées). Ne jamais commiter ces logs ; configurer
redaction et rétention avant toute exposition publique. L'API, elle, ne journalise
jamais les URLs présignées (journal d'audit à liste blanche, `docs/OBSERVABILITY.md`).

### Métriques Prometheus (cible, non activée)

Traefik sait exposer `/metrics` au format Prometheus. **Non activé actuellement** ;
il n'existe aucun service Prometheus en face. Si activé, veiller à : ne pas publier le
port de métriques sur l'hôte, restreindre l'accès au réseau interne, et ne pas y
exposer de labels à haute cardinalité (chemins complets, identifiants).

```yaml
command:
  - --metrics.prometheus=true
  - --metrics.prometheus.addEntryPointsLabels=true
  - --metrics.prometheus.addServicesLabels=true
```

Le reste de l'observabilité métier (audit, usage, supervision) est décrit dans
`docs/OBSERVABILITY.md` : ces données sont **mesurées par l'API**, pas par l'edge.

### Corrélation

Chaque réponse de l'API porte `X-Request-Id` (valeur cliente sûre reprise, sinon UUID
v4 serveur). Un `X-Request-Id` propagé par un proxy amont reste exploitable pour
corréler access logs de bord et journal d'audit applicatif.

## 5. Documentation d'API (outillage)

Le contrat de référence est `docs/openapi.yaml` (OpenAPI 3.1, version 0.2.0), gardé en
phase avec `api/main.py` par `tests/test_openapi_contract.py`.

| Outil | Usage | Remarque |
|---|---|---|
| **Swagger UI** | Explorer/« Try it » depuis le navigateur | ne servir que derrière authentification ; « Try it » déclenche des mutations réelles |
| **Redoc** | Rendu documentaire statique, lisible | bon pour publication interne en lecture seule |
| **Scalar** | UI moderne, thème clair, import OpenAPI | alternative front-end, aucune donnée sensible |
| **Hoppscotch CLI** | Tests/collections hors-ligne en CI | utile pour rejouer le contrat sans dépendre d'un environnement live |

Principes :

- Le contrat est **déjà** la source de vérité (`docs/openapi.yaml`) ; ces outils ne
  font que le consommer. Ne pas éditer la spec via un générateur.
- Ne pas exposer publiquement une UI de documentation tant que l'authentification et
  les restrictions réseau ne sont pas en place.
- Les serveurs listés dans la spec (`https://app.aura-storage.eurinhash.com`) sont
  indicatifs ; ne jamais y injecter de secret ni de credential S3.

## 6. Combinaison recommandée (cible)

1. Rester sur **Traefik** pour routage/TLS/labels (état actuel).
2. Si exposition publique requise : ajouter **rate-limit** et **en-têtes** au bord,
   **sans** retirer l'autorisation serveur de l'API.
3. Activer les **métriques Prometheus** seulement avec un scrape interne dédié et une
   politique de rétention/redaction des logs.
4. Évaluer **KrakenD 2.10** uniquement si un besoin de gateway multi-version /
   multi-consommateur apparaît (agrégation, quotas par clé).
5. **Ne pas** retenir **Kong OSS 3.9.1** (gel) sauf revue explicite.

## 7. À re-vérifier avant toute décision

- Versions et politique de support : **Kong OSS (gel annoncé à 3.9.1)** et
  **KrakenD 2.10** — à confirmer sur les canaux officiels au moment de la décision
  (aucune vérification réseau effectuée pour ce document).
- Compatibilité des middlewares Traefik avec la **version épinglée** du déploiement
  (`TRAEFIK_IMAGE` ; voir `config/traefik/README.md` sur le minimum ≥ 3.7 pour Docker
  Engine 29+).
- ~~Redaction effective des access logs pour les URLs présignées.~~ Corrigé le
  2026-10-24 : `--accesslog.fields.queryparameters.defaultmode=drop` dans le Compose.

## Références

- `docker-compose.yml`, `config/traefik/README.md`
- `docs/SECURITY.md`, `docs/OBSERVABILITY.md`, `docs/AUTHORIZATION-MATRIX.md`
- `docs/openapi.yaml`, `docs/API-SPECIFICATION.md`, `docs/FONCTIONNALITES.md`
