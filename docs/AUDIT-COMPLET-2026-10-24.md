# Audit complet — site AURA Vault

> Date : 2026-10-24 · Périmètre : site en production (`app.`, `aura-storage.`, `docs.`, `traefik.`), API FastAPI, frontend React, configuration Docker/Traefik/nginx, documentation.
> Méthode : lecture seule du dépôt, requêtes HTTP non destructives, build et suites de tests locaux. Aucune correction, aucun commit.
> Ce rapport ne contient aucun secret (ni mot de passe, ni clé, ni valeur `.env`).

## 1. Synthèse

| Sévérité | Nombre |
|---|---|
| Critique | 0 |
| Élevé | 5 |
| Moyen | 20 |
| Faible | 13 |
| Info | 5 |

**Le socle est solide** : TLS correct, en-têtes de sécurité complets sur l'application, autorisation *default-deny* vérifiée sur 65 routes, sessions opaques hachées, presign court, secrets ignorés par git, `377` tests backend et `30` tests unitaires frontend au vert, `0` vulnérabilité npm en production.

**Les cinq risques à traiter en premier** :

1. **L'API utilise l'identité S3 `aura-bootstrap-admin`** (actions `Admin`) : une compromission de l'API donne le contrôle total du stockage de tous les espaces.
2. **La session humaine déployée dure 90 jours** (`AURA_SESSION_TTL: "7776000"` en dur), non surchargeable depuis `.env`, alors que la doc et le code annoncent 8 h.
3. **`download-intent` sert du HTML/SVG `inline`** depuis le domaine de stockage : un fichier uploadé peut s'exécuter sur l'origine S3 (hameçonnage/script côté domaine « de confiance »).
4. **La production sert le répertoire de travail `./web/dist`** : tout build local modifie le site, et du code non commité est actuellement en ligne. Aucune release immuable.
5. **Les documents de sécurité, d'autorisation, de backup/restore et de déploiement référencés par le README n'existent plus** dans l'arbre : les garanties ne sont plus auditables.

## 2. Périmètre, méthode et limites

- **Serveur** : la machine d'audit est le VPS de production (IP publique `153.75.248.230` = DNS de `app.aura-storage.eurinhash.com`). L'accès au démon Docker est refusé à l'utilisateur d'audit ; l'état des conteneurs est déduit de `docker-compose.yml`, des en-têtes HTTP et des fichiers montés.
- **Tests non exécutés** : e2e Playwright (API/front de dev non démarrés), parité PostgreSQL (`AURA_TEST_PG_DSN` absent, 2 tests *skipped*), restore réel, couche hôte (SSH, pare-feu, daemon Docker), charge/DDoS.
- **Audit visuel non réalisé** : les navigateurs Playwright ne peuvent pas démarrer sur ce serveur (`libatk-1.0.so.0` absent, pas de sudo interactif). Aucune capture ni passe axe-core n'a donc été produite. L'accessibilité n'est évaluée que statiquement (markup, styles).
- **Surface authentifiée non testée** en HTTP (pas d'identifiants) : upload/commit, presigned PUT/GET, routes admin destructives.
- **Origine des constats** : « vérifié » = contrôlé directement pendant cet audit ; « lecture » = établi par analyse du code/config, non reproduit en exécution.

## 3. Vérifications exécutées

| Vérification | Résultat |
|---|---|
| `cd web && npm run build` (`tsc --noEmit` + vite) | **PASS** — 216 modules, bundle 462,31 kB (143,30 kB gzip théorique) |
| `cd web && npm run test:unit` | **PASS** — 30/30 tests (3 fichiers) |
| `cd web && npm audit --omit=dev` | **PASS** — 0 vulnérabilité |
| `.venv/bin/python -m pytest tests -q` | **PASS** — 377 passed, 2 skipped (92 s) |
| TLS (4 hôtes) | **PASS** — TLS 1.2/1.3, chaîne valide, HTTP→HTTPS 301 |
| En-têtes app | **PASS** — CSP stricte, HSTS, `X-Frame-Options: DENY`, `nosniff`, Referrer-Policy |
| Ports internes | **PASS** — seuls 80/443 publics (Compose) |
| Authz non authentifiée | **PASS** — 401 sur `/me`, `/objects`, `/folders`, `/admin/*` |
| Secrets suivis par git | **PASS** — `.env` ignoré, aucun secret réel dans l'historique |
| Compression / cache des assets | **FAIL** — aucun `Content-Encoding`, aucun `Cache-Control` |
| Routes inconnues (`/robots.txt`, `/sitemap.xml`, 404) | **FAIL** — renvoient le `index.html` de la SPA en `200 text/html` |

## 4. Sécurité de la production

### Élevé

**S1. L'API tourne avec l'identité S3 d'administration (`aura-bootstrap-admin`).** `docker-compose.yml:254-255` injecte `S3_ACCESS_KEY`/`S3_SECRET_KEY` dans l'API ; comparaison programmatique avec `config/seaweedfs/s3.json` : **identiques** (`Admin, Read, Write, List`, sans restriction de bucket). L'isolation par `space_id` n'existe qu'au niveau applicatif. *Remédiation* : identité SeaweedFS dédiée à l'API, restreinte aux buckets servis ; identité distincte pour les backups ; retirer `Admin` du trafic de routine.

**S2. Session de 90 jours, non configurable.** `docker-compose.yml:263` fixe `AURA_SESSION_TTL: "7776000"` en littéral, avec un commentaire affirmant qu'elle « correspond au défaut documenté (`api/config.py`) » — or `api/config.py:51` vaut `28800` (8 h) et `.env.example` documente 28 800. Un cookie volé reste valide 90 jours, sans renouvellement glissant. *Remédiation* : `AURA_SESSION_TTL: ${AURA_SESSION_TTL:-28800}`, valeur 8–24 h, documentation alignée.

### Moyen

**S3. Aucune rédaction des query strings dans les access logs Traefik.** `docker-compose.yml:27` : `--accesslog=true` seul. Les URLs présignées (`X-Amz-Signature`, `X-Amz-Credential`) apparaissent dans `docker logs`, ce qui contredit la promesse « presigned URLs never logged ». *Remédiation* : `--accesslog.fields.queryParameters.defaultMode=drop`, rotation des logs.

**S4. La landing S3 publique n'a aucun en-tête de sécurité.** Live : seul `strict-transport-security` ; pas de CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, alors que `landing/nginx.conf:12-15` les déclare. Cause : `docker-compose.yml:435-445` monte `./landing` mais **jamais** `landing/nginx.conf` dans `/etc/nginx/conf.d/`, donc la conf par défaut de l'image sert la page. *Remédiation* : monter la conf et vérifier les en-têtes en postflight.

**S5. HSTS absent du dashboard Traefik.** `docker-compose.yml:61` n'applique que `dash-ipallow,dash-auth` ; le middleware `aura-hsts` (l. 69-70) est appliqué à app/S3/landing mais pas au dashboard. Le dashboard est bien 403 depuis Internet (allowlist + BasicAuth), mais la claim « HSTS sur tous les routeurs publics » est fausse. *Remédiation* : ajouter `aura-hsts`.

**S6. Pas de durcissement runtime des conteneurs.** Aucun `user:`, `read_only:`, `cap_drop:` ni limite mémoire/CPU dans `docker-compose.yml` ; `api/Dockerfile` ne définit pas d'utilisateur. Un RCE dans l'API tourne en root dans le conteneur. *Remédiation* : `user: 10001:10001`, `read_only`, `tmpfs`, `cap_drop: [ALL]`, limites par service.

**S7. Socket Docker monté dans Traefik.** `docker-compose.yml:36` : `:ro` n'empêche pas les appels API Docker (create/exec/privileged). Compromission de Traefik ⇒ root hôte. *Remédiation* : socket-proxy filtré ou provider fichier.

**S8. `AURA_TRUSTED_PROXIES` couvre tout le RFC1918.** `docker-compose.yml:314`, `api/netinfo.py:30-36` : tout conteneur d'un réseau privé peut forger `X-Forwarded-For` et fausser les limiteurs par IP. *Remédiation* : restreindre aux sous-réseaux réels de Traefik/app.

### Faible / Info

- **S9.** Pas de `Permissions-Policy` ni COOP/CORP sur l'app (`app/nginx.conf:9-20`).
- **S10.** Bannières de version exposées (`nginx/1.28.3`, `SeaweedFS 30GB 4.48`) → `server_tokens off`.
- **S11.** Aucun enregistrement CAA sur `eurinhash.com` (à confirmer côté DNS).
- **S12.** Artefacts locaux lisibles par le groupe : `aura-audit.jsonl` 664, `aura-catalogue.db` 644, à la racine du dépôt.
- **S13.** Actions GitHub non épinglées par SHA (`actions/checkout@v4`, `appleboy/ssh-action@v0.1.8` obsolète) alors qu'elles manipulent la clé SSH de prod.
- **S14.** `DASHBOARD_PASSWORD` en clair dans `.env` n'est consommé nulle part (seul le hash bcrypt `DASHBOARD_AUTH` sert) : secret inutile à retirer.
- **S15.** `GET /?list-type=2` sur le host S3 renvoie la landing HTML au lieu d'une réponse S3 ; CORS S3 autorise `*` en méthodes/en-têtes (origine bien verrouillée à l'app).
- **S16.** `/health/ready` (non authentifié) déclenche un `list_buckets()` S3 à chaque appel ; `/api/v1/diag/download` sert 25 Mo d'`urandom` par requête authentifiée sans quota.

## 5. Déploiement et exploitation

### Élevé

**D1. La production sert le répertoire de travail `./web/dist`.** `docker-compose.yml:404` monte `./web/dist:/usr/share/nginx/html:ro`. Preuve : après un build local à 11:10:43, l'asset live porte `Last-Modified: 11:10:43` et un ETag recalculé (`6adc9233-70de5` = taille 462 309), alors que le hash de bundle était déjà `index-BJ8fbaDp.js`. Conséquences : le code non commité est en ligne, un build local publie immédiatement, aucun rollback atomique, pas de traçabilité commit↔release. *Remédiation* : publier un artefact immuable par release (image ou répertoire versionné), ne jamais monter l'arbre de travail en prod, vérifier le hash déployé dans `scripts/deploy.sh`.

### Moyen

**D2. Aucune compression ni cache sur les assets.** Live : JS de 462 309 octets servi **sans** `Content-Encoding` (≈143 kB en gzip, soit 3,2×), CSS 84 kB idem, aucun `Cache-Control`/`Expires`. `app/nginx.conf` et `landing/nginx.conf` ne contiennent ni `gzip` ni `expires`. *Remédiation* : `gzip on` (+ brotli si dispo) et `Cache-Control: public, max-age=31536000, immutable` sur `/assets/` (hashés), `no-cache` sur `index.html`.

**D3. Healthchecks manquants sur des services critiques.** `app`, `swagger-ui`, `seaweed-master`, `seaweed-volume`, `seaweed-filer` n'en ont pas ; `app` ne dépend de l'API qu'en `service_started`. Risque de démarrage désordonné et d'indisponibilité silencieuse.

**D4. `scripts/reconcile-cron.sh` contient un `EOF` parasite** (l. 9) : l'unité systemd échouera. Le reconcile in-process compense, mais le cron est inopérant.

**D5. Le README décrit une surface d'API qui n'existe pas.** `docs/API-SPECIFICATION.md:19`, `README.md:48` et `docs/ARCHITECTURE.md:31` affirment « no Traefik route / API reachable only through the app proxy » ; `docker-compose.yml:353-365` définit bien `aura-swagger-api` (`PathPrefix /api/`, allowlist + BasicAuth + rate-limit). La doc doit dire la vérité (double protection voulue ou non).

## 6. API — sécurité et correction

### Élevé

**A1. `download-intent` sert du contenu actif `inline` depuis l'origine S3.** `api/main.py:1806` appelle `presigned_get(...)` sans `content_disposition`, donc le `Content-Type` choisi par l'uploadeur est renvoyé tel quel ; `AURA_ALLOWED_CONTENT_TYPES` est vide par défaut (`api/config.py:195-199`), donc `text/html`, `image/svg+xml`, `*xml` sont acceptés. Le frontend ouvre l'URL (`web/src/pages/ObjectsPage.tsx:1729`) : la page s'exécute sur `https://<S3_DOMAIN>`, exactement ce que `preview-intent` interdit via `PREVIEWABLE_CONTENT_TYPES` (main.py:1820-1832). La route de partage, elle, force bien `attachment` (main.py:685-690). *Remédiation* : `content_disposition="attachment"` sur `download-intent` et refus des types actifs à l'intent.

### Moyen — vérifié dans le code

**A2. Objets créés par une identité machine (`owner_id = NULL`) invisibles et impurgeables par tout humain, admin compris.** `api/main.py:290-295` : `owner_id = principal["id"] if kind == "user" else None` ; `api/db.py:490-495` n'ajoute le filtre owner que s'il est non nul. Un humain ne voit donc jamais les objets d'un service ; si le token est révoqué, les octets ne sont plus gérables (le cleanup d'orphelins les ignore, `api/storage_reconcile.py:35-40`). Défaut de gouvernance/rétention, pas d'escalade directe. *Remédiation* : scope admin « espace entier » ou route de purge par espace, et documentation explicite.

**A3. Réservation de capacité squattable et check non atomique.** `api/main.py:996-1029` : la taille **déclarée** est réservée au niveau global ; avec le multipart (`AURA_MULTIPART_ENABLED=1`, plafond 1 TiB, TTL 7 j, `max_pending_intents=100`), 100 intents suffisent à bloquer toute l'instance une semaine sans envoyer un octet. `count_pending → _check_capacity → _charge_quota → create_pending_object` n'est pas transactionnel : des requêtes concurrentes dépassent le plafond. *Remédiation* : quota de réservation par owner/espace + check+insert transactionnels.

**A4. L'état `suspect` est un cul-de-sac.** `api/main.py:1794-1800` bascule un objet en `suspect` sur un simple `HEAD` divergent ; `mark_available` n'accepte que `pending|verifying` (`api/db.py:721-738`), aucune route ne réhabilite, et `suspect` n'est pas dans le `Literal ObjectStatus` (`main.py:282-285`) alors qu'il peut être renvoyé au client. Un faux positif transitoire rend un objet définitivement non téléchargeable. *Remédiation* : route de re-vérification admin + `suspect` dans le vocabulaire public.

**A5. `purge` d'un intent multipart n'abandonne pas la session S3.** `api/lifecycle.py:162-179` ne vérifie pas le statut et n'appelle jamais `abort_multipart_upload` (contrairement à `abort_object`/`soft_delete_object`). La ligne disparaît, les octets partiels restent jusqu'à 7 jours et ne sont plus réconciliés. *Remédiation* : abort avant delete, refus des statuts non terminaux.

**A6. `objects:purge` est accordable à un token machine.** `api/authz.py:45` inclut `OBJECTS_PURGE` dans `SERVICE_SCOPES` : un token fuité peut effacer définitivement tous les objets de l'espace (owner_id NULL) sans step-up ni master mode, alors que la route est présentée comme opérateur/admin (`main.py:1766-1767`). *Remédiation* : retirer `OBJECTS_PURGE` des services ou exiger une confirmation explicite.

**A7. Cache d'idempotence `_RESP_CACHE` : itération/éviction non synchronisées et réponse périmée.** `api/main.py:1256-1278` : `.items()` puis `pop` sans verrou → `RuntimeError: dictionary changed size during iteration` possible sous commits concurrents (500) ; un rejeu avec la même `Idempotency-Key` peut renvoyer 200 « available » pendant 300 s après une purge. *Remédiation* : verrou/LRU borné + contrôle d'existence.

**A8. Compteurs de rate-limit non bornés et par processus.** `api/main.py:191-217`, `api/authz.py:59-87` : seules les entrées de l'IP courante sont purgées → croissance mémoire sous attaque distribuée ; avec plusieurs workers, la limite est multipliée. *Remédiation* : purge globale + borne LRU, ou store partagé.

**A9. Course `reconcile` vs `commit`.** La route admin (`main.py:2048-2052`) utilise exactement la fenêtre d'acceptation du commit (`intent_ttl + grace`) ; un commit lent peut perdre ses octets, puis `mark_available` échoue. Le sweep automatique masque le problème via `reconcile_extra_grace_s`. *Remédiation* : marge dédiée + `set_status(allowed_from=("pending",))` (dont l'implémentation PostgreSQL est cassée, voir A10).

### Faible

**A10.** `api/db_pg.py:696` : `"status IN (%s)" % ",".join("%%s" ...)` produit `IN (%%s)` → **aucun** placeholder créé, SQL invalide. Branche morte aujourd'hui, mais c'est le garde-fou naturel de A9 ; non couverte par les tests.
**A11.** `LoginIn` sans `max_length` (`main.py:379-382`) : le nom d'utilisateur est écrit tel quel dans l'audit JSONL à chaque échec (10/min) → injection de volume dans le journal.
**A12.** `master_mode_on` ne réinitialise pas le budget d'échecs après succès (`main.py:783-800`), contrairement à `login` : 10 erreurs de step-up bloquent aussi `/login`.
**A13.** `verifier.py:132-135` ignore le `rowcount` de `mark_available` et audite un succès pour un objet purgé entre-temps.
**A14.** `audit.py:267-278` : purge avec `os.replace` en gardant le verrou sur l'ancien inode → événements perdables en multi-processus.
**A15.** Erreurs de stockage mal classées : un S3 indisponible devient `422 upload not found` (`main.py:1345-1348`) ; `preview-intent` ne fait pas le contrôle `HEAD` que fait `download-intent`.
**A16.** `_ensure_bootstrap_admin` (`main.py:234-245`) promeut silencieusement un compte `admin` existant et n'applique aucune politique de mot de passe ; une rotation d'env est sans effet.
**A17.** `scripts/reconcile-cron.sh` (cf. D4) ne peut pas utiliser un token machine : la route exige `admin:write`, interdit aux services.

### Points forts vérifiés

- 65 routes analysées par AST : seules `health/live`, `health/ready`, `login`, `/s/{token}` sont publiques ; routes admin en `ADMIN_READ`/`ADMIN_WRITE` ; jetons machine sans `admin:*`.
- Cookie `HttpOnly; Secure; SameSite=Strict`, host-only ; Argon2 ; hash factice à temps constant ; CSRF double-submit ; login limité 10/60 s/IP.
- Presign TTL court (60–900 s), `x-amz-server-side-encryption: AES256` exigé au commit ; clés d'objet générées côté serveur ; `consume_share` atomique.
- `suspect` mis à part : intégrité vérifiée avant téléchargement (invariant S10) même si la sortie d'état manque.

## 7. Frontend

### Moyen

**F1. La CSP de production bloque le script inline de thème.** `web/index.html:13` contient un `<script>` inline ; la prod sert `script-src 'self'` sans nonce ni hash (`app/nginx.conf:20`, test `tests/test_app_csp.py:37`). Le bootstrap du thème est donc bloqué → retour du flash clair/sombre au rechargement. *Preuve* : HTML live contient le script inline ; CSP live ne l'autorise pas. *Remédiation* : déplacer le bootstrap dans un module importé avant `createRoot`, ou ajouter le hash SHA-256.

**F2. Injection de formules dans l'export CSV.** `web/src/lib/csv.ts:12-16` n'échappe pas les préfixes `= + - @` (ni tab/CR) : un fichier nommé `=HYPERLINK(...)` s'exécute à l'ouverture dans Excel/LibreOffice (export depuis `TransfersPage.tsx:646`). *Remédiation* : préfixer d'une apostrophe.

**F3. Toute erreur `/me` déconnecte.** `web/src/lib/auth.tsx:110-121` redirige vers `/login` sur 500 ou coupure réseau, en perdant la page ; seule une 401/403 devrait déconnecter.

**F4. Pas de gestion globale du 401 ni d'annulation.** `web/src/lib/api.ts:534-566` : pas d'intercepteur, pas de `signal`/timeout ; une session expirée produit un simple toast sans invalidation de `["session"]`.

**F5. `xhr.timeout` jamais armé sur les PUT présignés.** `web/src/lib/api.ts:1062-1068` : `ontimeout` est défini mais aucun timeout n'est posé → un PUT bloqué immobilise un slot de concurrence indéfiniment. Listener `abort` non retiré au settle.

**F6. `localStorage` non protégé.** `web/src/components/Layout.tsx:88-106` : lecture/écriture sans `try/catch` → écran blanc si le stockage est indisponible (Safari privé, quota), alors que `index.html` est déjà protégé.

**F7. Logout partiel.** `web/src/lib/auth.tsx:57-71` + `Layout.tsx:198-201` : seul `["session"]` est invalidé, les caches `["objects"]`, `["folders"]`, `["admin", …]` peuvent réapparaître après changement de compte ; `csrf` reste armé ; l'erreur de logout est avalée.

**F8. `window.open` après `await`.** `web/src/pages/ObjectsPage.tsx:1729` : ouverture hors geste utilisateur → bloquée par les bloqueurs de pop-up, alors que le toast annonce « Téléchargement lancé ».

### Faible

- **F9.** `web/src/lib/download.ts:27-56` : helper mort ; sur flux tronqué, retourne `integrityOk: true` sans `expectedSha256`.
- **F10.** `TransferList.tsx:307` : `aria-rowindex` décalé d'un cran (la première ligne de données est annoncée `1` alors que l'en-tête occupe déjà 1).
- **F11.** `PreviewModal.tsx:134-139` : iframe sans `sandbox` (défense en profondeur).
- **F12.** `package.json` : versions `"latest"` sur Storybook/Playwright/Vitest → installs non déterministes ; dépendances de dev inutilisées (`style-dictionary`, `@vitest/browser-playwright`, `@vitest/coverage-v8`) ; `dist.bak-20261015-203853/` non ignoré par git.
- **F13.** `robots.txt`, `sitemap.xml` et toute route inconnue renvoient le `index.html` de la SPA en `200 text/html` (soft-404 SEO).

### Changement non commité (état réel)

Le seul fichier modifié est `web/src/components/transfers/TransferList.tsx` (+33/−1) : libellés « · Léger » / « · Lourd » selon la taille, `aria-valuenow` désormais toujours renseigné, et nouvel indicateur multipart (parts reçues/manquantes, reprise, tentatives). **La virtualisation n'est pas dans ce diff** : elle est déjà commitée (`HEAD`). Le build est vert et le bundle produit est identique à celui servi en production ; ce diff est donc **actuellement en ligne**. Points à surveiller : libellés de taille affichés en texte brut dans la liste, usage de styles inline pour les parts (cohérence avec le design system), et l'`aria-valuenow` renseigné pendant la vérification d'intégrité peut annoncer une progression obsolète (le `aria-valuetext` prime, donc acceptable).

## 8. Documentation vs réalité

### Élevé

**DOC1. Quatre documents structurants référencés n'existent plus** : `docs/SECURITY.md` (README:26), `docs/AUTHORIZATION-MATRIX.md` (README:27, `api/authz.py:47`), `docs/BACKUP-RESTORE.md` (README:32, `DECISION-BACKUP-DEFERRED.md:9`), `docs/DEPLOYMENT.md` (README:17, `QA-01-CHECKLIST.md:30`). Supprimés par `296e8ea`. Les affirmations de sécurité et la matrice d'autorisation ne sont plus auditables ; les liens sont morts.

### Moyen

- **DOC2.** `docs/API-ROUTES-AUDIT.md` est faux : annonce 59 routes (le code en expose 62), liste 10 routes inexistantes et en omet 13 réelles. À régénérer depuis `api/main.py`/`openapi.yaml`.
- **DOC3.** Statut multipart contradictoire : README/`TRANSFER-ENGINE.md`/`ARCHITECTURE.md` disent « not implemented » ; `MULTIPART-UPLOAD-PLAN.md` et le code disent « implémenté derrière `AURA_MULTIPART_ENABLED` (off par défaut, non validé sur SeaweedFS 4.48) ».
- **DOC4.** Les « open gates » du README sont périmés : « external HTTPS validation » et « internal ports not published » sont validés par les logs 10-15/10-20 ; en revanche SSH par clé et pare-feu (toujours non confirmés) sont omis.
- **DOC5.** « Aucun essai de bout en bout sur le VPS » (`FONCTIONNALITES.md:12-13`) est faux : upload/download authentifié PASS et session admin réelle sont datés dans les logs 10-15/10-20.
- **DOC6.** Références de tests/benchmarks inexistantes : `tests/test_transfer_basic.py`, `scripts/bench_transfer.py` (les vrais fichiers sont `tests/test_transfer_engine.py`, `tests/commit_latency_bench.py`).
- **DOC7.** `README.md:61` impose `git clone --branch feat/secure-storage-pilot`, branche inexistante (`HEAD` = `main`) → clone impossible pour un nouvel opérateur.
- **DOC8.** Logs datés non marqués obsolètes : `GLOBAL-AUDIT-REPORT-2026-10-14.md` conclut « aucun composant déployé » ; `verification-log-2026-10-20` affirme que `deploy.sh` ne peut pas recréer `app` (corrigé depuis) et donne une taille d'`openapi.yaml` fausse.

### Faible

- **DOC9.** Liens morts : `docs/RUNBOOK.md`, `docs/DESIGN-PADDING-AUDIT.md`, `AGENTS.md` ; paragraphe dupliqué dans `ENVIRONMENT-CONFIGURATION.md:40-41`.
- **DOC10.** Il manque la matrice des deux routes `admin/reconcile-terminal` et `admin/reconcile-reverse`.

### Affirmations vérifiées exactes

- Contrat OpenAPI ≈ code : 61 opérations identiques, seul `GET /s/{token}` est hors contrat (assumé).
- Seuls 80/443 sont publiés ; API, PostgreSQL et SeaweedFS sans port hôte.
- Scopes `admin:*` refusés aux identités machine (422) et neutralisés même en base.
- Sessions hachées SHA-256, login à temps constant, CSP stricte, audit persistant : conformes aux logs N2 (implémenté, non rejoué ici).

## 9. Plan de remédiation priorisé

### P0 — sous 48 h

1. **S1** : créer une identité SeaweedFS dédiée à l'API, restreinte aux buckets servis ; retirer `Admin` ; régénérer `.env`/`s3.json` et redémarrer. Vérifier que les backups ont leur propre identité.
2. **S2** : `AURA_SESSION_TTL: ${AURA_SESSION_TTL:-28800}`, valeur cible 8–24 h ; invalider les sessions existantes si la valeur change.
3. **A1** : forcer `content_disposition="attachment"` sur `download-intent` ; refuser `text/html`, `image/svg+xml`, `*xml` quand l'allow-list est vide.
4. **D1** : ne plus servir `./web/dist` depuis l'arbre de travail ; publier un artefact immuable par release et vérifier le hash servi.
5. **F1** : sortir le bootstrap de thème du HTML inline (ou hash CSP) — correctif petit, impact visible.
6. **S4** : monter `landing/nginx.conf` et vérifier les en-têtes de la landing en postflight.
7. **DOC1** : restaurer `SECURITY.md`, `AUTHORIZATION-MATRIX.md`, `BACKUP-RESTORE.md`, `DEPLOYMENT.md` (ou retirer les références et requalifier les garanties).

### P1 — sous 2 semaines

8. **S3, S5, S6, S7, S8** : rédaction des query strings, HSTS dashboard, durcissement conteneurs, socket-proxy, `TRUSTED_PROXIES` restreint.
9. **A2 → A9** : scope admin espace, quotas de réservation + transaction, sortie de l'état `suspect`, abort multipart à la purge, retrait de `OBJECTS_PURGE` des services, verrou du cache d'idempotence, rate-limit borné, marge reconcile.
10. **D2, D3** : gzip/brotli + cache immuable des assets, healthchecks et `depends_on: service_healthy`.
11. **F2 → F8** : CSV, 401 global, timeout PUT, `localStorage`, logout, `window.open`, redirection `/me`.
12. **DOC2 → DOC8** : régénérer l'audit de routes, corriger statut multipart, gates, logs datés, branche de clone.

### P2 — dette

13. **P0 de tests** : `set_status(allowed_from=…)` sur PostgreSQL (A10), concurrence `reconcile`/`commit`, purge multipart, cycle `suspect`, `_RESP_CACHE` concurrent.
14. **A10 → A17**, **F9 → F13**, **DOC9-DOC10**, épinglage SHA des actions GitHub, `server_tokens off`, CAA, permissions des artefacts locaux.
15. Mettre en place un audit automatisé récurrent : `pytest`, `npm run build`, `npm run test:unit`, en-têtes HTTP, test de non-régression CSP, et un test d'accessibilité exécutable sur un runner disposant des bibliothèques navigateur.

## 10. Ce qui reste à vérifier (hors de portée ici)

- Audit visuel et axe-core des écrans authentifiés (navigateur indisponible sur ce serveur).
- E2E Playwright contre l'API et le front de dev.
- Parité PostgreSQL réelle des requêtes non couvertes.
- Restore réel depuis une sauvegarde indépendante (gate d'acceptation toujours ouvert).
- Couche hôte : SSH par clé, pare-feu, rotation Docker, durcissement systemd.
- Comportement sous charge, efficacité réelle des limiteurs, test de restauration après reboot.
