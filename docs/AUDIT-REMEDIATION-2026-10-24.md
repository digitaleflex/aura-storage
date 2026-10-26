# Remédiation de l'audit du 2026-10-24

> Contrepartie de [`AUDIT-COMPLET-2026-10-24.md`](AUDIT-COMPLET-2026-10-24.md).
> État après application des correctifs : ce qui est corrigé, ce qui est préparé
> mais nécessite une action opérateur, et ce qui reste volontairement ouvert.
> Aucun secret n'est reproduit ici.

## 1. Vérifications exécutées après correctifs

| Vérification | Résultat |
|---|---|
| `.venv/bin/python -m pytest tests -q` | **382 passed, 2 skipped** (5 tests de régression ajoutés) |
| `cd web && npm run build` | **PASS** (218 modules) |
| `cd web && npm run test:unit` | **PASS** — 33 tests (dont 3 nouveaux sur le CSV) |
| `docker compose config -q` | **PASS** |
| `bash -n` sur `deploy.sh`, `reconcile-cron.sh`, `generate-config.sh` | **PASS** |
| Site live (frontend) | **PASS** — nouveau bundle `index-DKBl-91V.js` servi, plus aucun `<script>` inline, `robots.txt` et `sitemap.xml` réels |

## 2. Corrigé dans le dépôt

### Sécurité / API

| Constat | Correctif |
|---|---|
| A1 téléchargement inline | `download-intent` force `Content-Disposition: attachment` ; `preview-intent` fait le même contrôle d'intégrité que le téléchargement |
| A2 objets machine invisibles | opérateurs/admins ont un scope espace (`owner_id NULL` inclus) ; un utilisateur simple reste limité à ses objets |
| A3 réservation de capacité | plafond par owner (`AURA_MAX_PENDING_BYTES_PER_OWNER`, 100 GiB) + admission sérialisée par le verrou du dépôt |
| A4 état `suspect` | `suspect` ajouté au vocabulaire public + route `POST /api/v1/admin/objects/{oid}/reverify` (re-hash, republication ou 409) |
| A5 purge multipart | `purge_object` abandonne la session S3 avant de supprimer la ligne |
| A6 purge machine | `objects:purge` retiré de `SERVICE_SCOPES` (422 à la création) |
| A7 cache d'idempotence | accès sérialisés par `_RESP_CACHE_LOCK` |
| A8 rate-limit | purge globale + borne de 10 000 entrées (login et M2M) |
| A9 reconcile vs commit | marge `reconcile_extra_grace_s` appliquée aussi à la route admin |
| A10 SQL PostgreSQL | `status IN (%s, %s)` corrigé |
| A11 entrées login | `max_length` sur username/password |
| A12 master mode | budget d'échecs remis à zéro après succès |
| A13 vérificateur | `rowcount == 0` audité `superseded`, plus de faux succès |
| A14 purge d'audit | verrou `flock` sur un fichier `.lock` dédié |
| A15 erreurs stockage | contrôle HEAD partagé entre download et preview |
| A16 bootstrap | avertissement mot de passe faible + journalisation des promotions implicites |
| S2 session 90 j | Compose : `${AURA_SESSION_TTL:-28800}` ; au démarrage, les sessions plus longues que la politique sont révoquées |
| S16 `/health/ready` | verdict mis en cache 5 s (plus de `list_buckets` par requête) |
| S12 artefacts locaux | `aura-audit.jsonl` et `aura-catalogue.db` en `0600` |

### Frontend

| Constat | Correctif |
|---|---|
| F1 CSP vs script inline | bootstrap de thème déplacé dans `src/theme-boot.ts` (module, aucun inline) |
| F2 injection CSV | préfixe apostrophe sur `= + - @` (tab/CR) + tests |
| F3 `/me` en erreur | déconnexion uniquement sur 401/403, sinon bouton « Réessayer » |
| F4 401 global / annulation | événement `aura:unauthorized`, `signal` + `timeoutMs` dans `request()` |
| F5 PUT sans timeout | `xhr.timeout` armé (120 s), listeners nettoyés |
| F6 `localStorage` | helper `safeStorage` (lecture/écriture protégées) |
| F7 logout partiel | `finally` + `queryClient.clear()` |
| F8 pop-up bloquée | fenêtre ouverte dans le geste utilisateur puis redirigée |
| F9 téléchargement tronqué | contrôle de complétude + `res.ok` sur le probe |
| F10 `aria-rowindex` | en-tête = 1, données à partir de 2, `aria-rowcount` inclut l'en-tête |
| F11 iframe PDF | `sandbox` restrictif |
| F12 reproductibilité | versions figées, `style-dictionary` retirée, lock régénéré |
| F13 soft-404 SEO | `robots.txt` et `sitemap.xml` réels |

### Infra / exploitation

| Constat | Correctif |
|---|---|
| S1 identité S3 API | **rotation effectuée le 2026-10-24** : identité `aura-api` (`Read/Write/List`) générée avec des clés distinctes, `s3.json` régénéré, `seaweed-filer` et `api` recréés ; repli Compose conservé pour les déploiements non migrés |
| S3 logs présignés | `--accesslog.fields.queryparameters.defaultmode=drop` |
| S4 en-têtes landing | `entrypoint.sh` installe `landing/nginx.conf` dans `conf.d/default.conf` ; routeur `HEAD` dédié (le matcher `Method` de Traefik n'accepte qu'une valeur) |
| S5 HSTS dashboard | `aura-hsts` ajouté au routeur du dashboard |
| S6 conteneurs | API : `read_only`, `tmpfs /tmp`, `cap_drop ALL`, `no-new-privileges`, limites ; app/landing : limites + `no-new-privileges` |
| S7 socket Docker | **testé puis annulé** : avec un endpoint distant, Traefik v3.7 ne charge plus les middlewares et tous les routeurs tombent en 404. Montage direct du socket restauré, décision documentée dans le Compose |
| S8 proxies de confiance | sous-réseaux explicites `172.30/31/32.0.0/24`, plus de RFC1918 entier |
| S9/S10 en-têtes | `Permissions-Policy`, COOP, `server_tokens off` (la version n'est plus exposée ; l'en-tête `Server` reste `nginx`, sans version) |
| S13 actions GitHub | épinglées par SHA ; `appleboy/ssh-action` → v1.2.5 épinglée |
| D1 release immuable | `deploy.sh` compare le hash du bundle servi à `web/dist` et échoue sinon |
| D2 compression/cache | gzip + `expires 1y` sur `/assets/`, `no-cache` sur l'index |
| D3 healthchecks | app + `depends_on: service_healthy` |
| D4 cron | `EOF` parasite supprimé |
| DOC1-DOC10 | docs de sécurité/autorisation/backup/déploiement restaurés et corrigés, statuts multipart, gates, branche `main`, chemins de tests, bandeaux « superseded », audit de routes régénéré (63 routes) |

## 3. Déploiement effectué le 2026-10-24

Le stack a été recréé (`docker compose up -d --force-recreate`), puis Traefik
redémarré après stabilisation des healthchecks. Constats et incidents :

- **25 sessions** de plus de 8 h ont été révoquées au démarrage de l'API (effet
  attendu du nouveau TTL).
- **Incident évité** : la recréation des réseaux avec sous-réseaux explicites a
  reconnecté les anciens conteneurs sans leurs alias Compose (`postgres`,
  `seaweed-filer`) → l'API ne résolvait plus la base. Un `--force-recreate`
  complet a rétabli les alias. `deploy.sh` fait désormais `up --wait` puis
  redémarre Traefik pour éviter la course des healthchecks.
- **Traefik v3.7** filtre les conteneurs dont la santé est `starting` et
  n'applique pas les labels de son propre conteneur : les middlewares et le
  routeur du dashboard ont été déplacés sur le service `app` (commenté dans le
  Compose).
- **Rotation S3 effectuée** : clés `S3_API_*` générées (24/64 caractères), identité
  `aura-api` sans `Admin` ajoutée à `s3.json`, `seaweed-filer` et `api` recréés.
  Vérifié : `list_buckets` OK, `/health/ready` 200, URL présignée acceptée
  (404 `NoSuchKey` et non `SignatureDoesNotMatch`), API toujours `401` sans session.
- **Vérifié en production** : app `200` avec CSP/Permissions-Policy/COOP/HSTS,
  landing `200` avec CSP/X-Frame-Options/Referrer-Policy/HSTS, dashboard et docs
  `403` (allowlist), gzip actif (462 kB → ~144 kB), `Cache-Control: max-age=1 an`
  sur `/assets/`, hash du bundle servi identique à `web/dist`, `/api/v1/me` → 401.

## 4. Reste à faire (hors dépôt)

1. **S11 — CAA** : ajouter côté DNS `CAA 0 issue "letsencrypt.org"` et
   `issuewild ";"`.
2. **S14** : supprimer `DASHBOARD_PASSWORD` du `.env` (non consommé ; seul le
   hash `DASHBOARD_AUTH` sert).
3. Conserver l'identité `aura-bootstrap-admin` uniquement pour l'administration
   et les sauvegardes ; ne plus l'utiliser pour le trafic applicatif.
4. Rejouer l'audit visuel/a11y et les e2e Playwright sur un poste avec navigateur.

## 5. Non corrigé (assumé)

- **S15** : le host S3 répond encore la landing à `?list-type=2` (comportement
  non-S3 mais sans fuite) ; la restriction des méthodes/en-têtes CORS dépend de
  la configuration SeaweedFS, non modifiée ici.
- **A3/A7/A8/A14** : les garde-fous restent **par processus** (verrou en
  mémoire, `flock` local). Corrects pour le déploiement mono-worker actuel ; un
  passage multi-instances demandera un store partagé.
- **S16 (diag)** : `/api/v1/diag/download` reste plafonné à 25 Mo par appel mais
  sans quota par identité.
- **Tests non exécutables ici** : e2e Playwright, audit visuel/axe (navigateur
  indisponible : `libatk` manquant), parité PostgreSQL réelle, restore, couche
  hôte (SSH/pare-feu/reboot).
- **Anciens logs datés** : conservés comme archives avec bandeau quand ils sont
  contredits par l'état courant.

## 6. Rollback

Chaque lot est indépendant :

- frontend : `git checkout -- web/ && npm run build` (le `dist` est servi en
  direct) ;
- API : redéployer l'image précédente (`docker compose up -d --build api`) ;
- infra : `git checkout -- docker-compose.yml app/ landing/` puis
  `docker compose up -d` ;
- docs : `git checkout -- docs/ README.md`.

Aucun commit n'a été créé : `git diff` reste la source de vérité de la revue.
