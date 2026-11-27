# Portail public (livres audio)

Direction visuelle et décisions de l'interface : [PUBLIC-PORTAL-UI.md](PUBLIC-PORTAL-UI.md).

Le portail public est un sous-domaine dédié, `PUBLIC_DOMAIN` (pilote :
`public.aura-storage.eurinhash.com`). Il permet à un visiteur connecté avec son
compte Google de parcourir les packs publiés et d'écouter leurs pistes audio.
Il ne donne **aucun** accès aux objets, dossiers ou routes d'administration.

## Ce qui est exposé

| Chemin (sur `PUBLIC_DOMAIN`) | Rôle |
|---|---|
| `GET /` | **anonyme** : vitrine du catalogue publié (recherche, filtre par auteur, bouton Google) ; **connecté** : catalogue avec lecteur `<audio>`. Avec `AURA_PUBLIC_BROWSE=0`, les anonymes voient seulement la page de connexion |
| `GET /livre/{id}` | page d'un livre, lisible sans compte : couverture, durée, chapitres, extrait gratuit, partage (WhatsApp, copier le lien), balises Open Graph/Twitter et JSON-LD `Audiobook` |
| `GET /extrait/{id}` | extrait gratuit : **1 minute** d'un **MP3** publié, découpée côté serveur (`AURA_PUBLIC_PREVIEW_SECONDS`, 60 par défaut, 0 = désactivé), sans compte et sans téléchargement (`controlsList="nodownload"`, `Accept-Ranges: none`) |
| `GET /sitemap.xml`, `GET /robots.txt` | référencement : accueil et pages livre uniquement |
| `GET /api/public/auth/google` | démarre le flux Google (state + PKCE) |
| `GET /api/public/auth/callback` | vérifie Google, crée la session, redirige vers `/` |
| `GET /api/public/me` | identité + plan (`free`/`premium`) + jeton CSRF de la session publique |
| `POST /api/public/logout` | détruit la session (CSRF requis) |
| `GET /api/public/library` | catalogue publié (JSON), avec position d'écoute par visiteur |
| `PUT/DELETE /api/public/favorites/{id}` | ajoute/retire un livre publié des favoris du visiteur (CSRF, idempotent ; table `listen_favorites`, migration `0022`) |
| `POST /api/public/progress` | enregistre la position de lecture (CSRF, session publique) |
| `GET /m/{slug}` | redirection média **du livre entier** : compte **premium** requis par défaut (`AURA_PUBLIC_REQUIRE_PREMIUM=1`) ; sans session → 401, compte gratuit → 403 ; slugs d'intégration de confiance via `AURA_PUBLIC_MEDIA_OPEN_SLUGS` |
| `GET /s/{token}` | lien de partage : ouvert pour les fichiers ordinaires, mais un objet **publié** (livre du portail) exige aussi un compte premium ; sinon 404 uniforme |
| `GET /portal-assets/{nom}` | feuille de style et scripts du portail (empreinte dans l'URL, cache immuable) |
| `GET /profil` | page de profil du visiteur (nom affiché, suppression du compte) |

**Navigation sans compte.** Les pages anonymes n'affichent jamais le lien `/m/{slug}` : les
livres s'ouvrent par leur identifiant (`/livre/{id}`) et l'extrait d'une minute est coupé
côté serveur. Le bouton « Continuer avec Google » concerne **la suite du livre** : l'extrait
lui-même ne demande aucun compte. La session publique dure 7 jours (`AURA_PUBLIC_SESSION_TTL`) ;
une reconnexion après ce délai — ou si le navigateur refuse les cookies — est normale.

**Plans.** Le compte gratuit lit l'extrait d'une minute et consulte le catalogue ; il ne reçoit
jamais d'URL de fichier complet. Le compte **premium** ouvre `/m/{slug}`, le lecteur complet
et le bouton « Télécharger » (cache hors-ligne). Le plan est stocké dans `users.plan`
(`free`/`premium`, migration `ADDED_COLUMNS`) ; `AURA_PREMIUM_EMAILS=adresse@exemple.fr,…`
promote les comptes vérifiés à la connexion, sans jamais rétrograder un compte déjà premium.
Un opérateur peut aussi poser le plan directement en base.

Sans session, `/m/{slug}` renvoie **401** ; avec un compte gratuit, **403**. Les liens de
partage `/s/{token}` portant sur un objet publié appliquent la même règle mais répondent
**404** comme toute autre erreur de partage, pour ne pas révéler l'existence du lien. Les
intégrations de confiance (sites de cours) peuvent être exemptées nommément avec
`AURA_PUBLIC_MEDIA_OPEN_SLUGS=slug-1,slug-2`. Leurs URLs redeviennent alors publiques par
décision explicite de l'opérateur.

Le script `preview.js` empêche le menu « Enregistrer sous » sur l'extrait ; ce n'est pas une
protection contre l'inspection réseau, mais le fichier complet n'est délivré que sur
autorisation serveur. `offline.js` envoie désormais le cookie de session (`same-origin`)
et n'est chargé que pour les comptes premium.

**Décision (issue #295) :** le contenu payant ne passe jamais par `/m/{slug}`. L'API
audiobook prend la décision d'accès puis demande une URL courte à AURA avec son
identité de service. En attendant, `AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS` permet de
bloquer nommément les slugs concernés (404). Voir `docs/audiobook/README.md` §2.3.

Les fichiers eux-mêmes sont servis par les liens `/m/{slug}` déjà existants :
une redirection 302 vers une URL S3 présignée de courte durée, avec `Range`
(seek). Aucun octet ne traverse l'API. Le lecteur HTML pointe directement sur
ces URL. Les pages du portail (connexion, catalogue, profil) portent une **Content-Security-Policy
stricte** : `default-src 'none'; script-src 'self'; style-src 'self'`, `connect-src 'self'`,
`form-action 'self'`, `frame-ancestors 'none'`, et `media-src`/`img-src` limités à l'origine
et au stockage S3 (vers lequel `/m/` et `/covers/` redirigent). Aucun script ni `<style>`
inline : le CSS et le JS vivent dans `api/portal_assets/` (`portal.css`, `common.js`,
`player.js`, `shelf.js`), servis par `GET /portal-assets/{nom}?v=<empreinte>` en
`immutable` (cache d'un an, l'empreinte change avec le fichier). Seuls les attributs
`style="--cover-h:…"` / `width:…%` calculés par le serveur restent autorisés
(`style-src-attr`). Le jeton CSRF n'est jamais écrit dans un fichier mis en cache : il passe par
`data-csrf` sur `#player-bar`. Ajouter un fichier : le déposer dans `api/portal_assets/`
(`.css` ou `.js`) et le référencer avec `asset_url("nom")` ; Traefik route déjà
`/portal-assets/` et `/profil` vers l'API sur le domaine public.

`/api/v1/*`, `/s/*`, `/f/*`, `/p/*` et la console React restent sur `APP_DOMAIN`.

## Thème clair et favoris

Le portail public reste toujours clair, quelle que soit la préférence système du visiteur :
`portal.css` force `color-scheme: light` et ne contient pas de variante
`prefers-color-scheme: dark`. La barre d'adresse de l'application installable utilise la même
couleur claire (`theme-color`). Un cœur sur chaque livre (catalogue et page livre) alimente
l'étagère « Mes favoris » ; l'état est privé, supprimé avec le compte, et le clic est annulé côté
page si le serveur refuse.

## Marque-pages et reprise depuis un autre appareil

- **Marque-pages** : bouton « + Ici » dans le panneau Chapitres du lecteur (note facultative de 200
  caractères), liste triée par position, clic = se placer à cet endroit, × = supprimer. 50 maximum
  par livre et par visiteur ; privés, supprimés avec le compte (table `listen_bookmarks`, migration
  `0024`). API : `GET/POST /api/public/bookmarks`, `DELETE /api/public/bookmarks/{id}` (CSRF).
- **Reprise** : au retour sur l'onglet, si le serveur connaît une position plus avancée de plus de
  20 s (écoute faite sur un autre appareil) et que le lecteur est en pause, une bulle propose
  « Vous en étiez à 0:40 sur un autre appareil. Reprendre ». API : `GET /api/public/progress?object_id=`.

## Statistiques (administration)

`GET /api/v1/admin/portal-stats` (`admin:read`) et la carte **Portail public** de l'onglet Vue
d'ensemble de la console : comptes visiteurs, livres publiés, et pour chaque livre (50 premiers,
classés par auditeurs) : auditeurs, livres **terminés** (≥ 90 % de la durée), favoris, ouvertures du
mois. Ce sont des **comptages agrégés** calculés à partir de `listen_progress`, `listen_favorites` et
`object_usage_monthly` : aucune table de suivi n'a été ajoutée, aucun visiteur, e-mail ou historique
individuel n'est renvoyé. Les ouvertures comptent les redirections `/m/` et les extraits.

## Recherche, tri et recommandations

- **Recherche** (`?q=`) : insensible aux accents et à la casse, tous les mots doivent correspondre
  (titre ou auteur) : « eleonore depart » trouve « Éléonore Dupré — Le Grand Départ ».
- **Tri** (`?tri=titre|auteur|recent|duree`) : valeur inconnue ignorée ; les vues triées ou filtrées
  ne sont pas indexées.
- **Pour vous** : livres non écoutés des auteurs que le visiteur met en favori (poids 3) ou
  a déjà commencés (poids 1). N'utilise que les données du visiteur ; aucun signal = pas d'étagère.
- Page livre : « Du même auteur » et « À écouter ensuite » (suite de la collection).
- Une adresse inconnue du portail renvoie une **page 404** (le JSON reste pour `/api/*` et pour les
  clients qui n'acceptent pas le HTML). AirPlay est autorisé sur le lecteur (Safari/iOS).

## Connexion par e-mail (lien magique)

Pour les visiteurs sans compte Google. **Désactivée tant qu'aucun serveur de messagerie n'est
configuré** : renseigner `AURA_SMTP_HOST` et `AURA_SMTP_FROM` (+ `AURA_SMTP_PORT`, `AURA_SMTP_USER`,
`AURA_SMTP_PASSWORD`, `AURA_SMTP_STARTTLS`, `AURA_EMAIL_LINK_TTL`) dans `.env`. Le formulaire
« Recevoir le lien » apparaît alors sur la page de connexion et sur la vitrine.

| Chemin | Rôle |
|---|---|
| `POST /api/public/auth/email` | demande un lien ; **même réponse** que l'adresse soit valide, inconnue ou refusée (pas d'énumération) ; envoi en tâche de fond |
| `GET /connexion/lien?token=` | page avec un bouton « Me connecter » : ouvrir le lien ne le consomme pas (les scanners de messagerie qui préchargent les liens ne le brûlent pas) |
| `POST /api/public/auth/email/confirm` | consomme le jeton (usage unique) et ouvre la session |

Jeton aléatoire, **seul son SHA-256 est stocké** (`login_links`, migration `0023`), valable 15 min
par défaut. Limites : 10 demandes/heure/client et 3 mails/heure/adresse ; les mauvais jetons
comptent dans le budget d'échecs de connexion publique. Un POST venu d'un autre site est refusé.
`GOOGLE_ALLOWED_EMAIL_DOMAINS` s'applique aussi. Un lien envoyé à l'adresse d'un compte Google
existant ouvre ce compte ; un compte créé par lien est réutilisé si la personne passe ensuite par
Google avec la même adresse. Deux identités Google différentes ne sont jamais fusionnées.

## Application installable et écoute hors connexion

Le portail est une **PWA** : manifeste (`/portal-assets/manifest.webmanifest`, icônes 192/512 px
dont une « maskable »), couleurs de barre claire/sombre, service worker `GET /sw.js` (à la racine,
`Service-Worker-Allowed: /`, jamais mis en cache pour que les mises à jour passent) et page
`GET /hors-ligne`. Le navigateur propose « Installer l'application » ; sur iPhone : Partager →
« Sur l'écran d'accueil ».

- **Pages** (accueil, fiches livre) : réseau d'abord ; hors connexion, la dernière copie
  vue est servie, sinon la page « Vous êtes hors connexion ».
- **Livres** : le bouton **Télécharger** du lecteur copie le livre en cours dans le cache
  `aura-audio` de l'appareil (indicateur ⤓ dans les listes, livres non téléchargés grisés hors
  connexion). Le service worker les sert avec la prise en charge de `Range` : lecture et
  déplacement dans le livre sans réseau. Le même bouton retire le livre de l'appareil.
- **Déconnexion** : les pages mises en cache (progression, favoris) sont effacées ; les livres
  téléchargés restent (contenu public choisi par le visiteur).
- **Prérequis côté stockage** : le téléchargement suit la redirection de `/m/{slug}` vers S3 avec
  `fetch` ; le stockage doit donc répondre avec `Access-Control-Allow-Origin` pour le domaine du
  portail. Sans CORS, le bouton affiche « Téléchargement impossible » et rien n'est enregistré
  (l'écoute en ligne n'est pas affectée). **À vérifier sur le vrai stockage** (non testable hors
  production).
- La CSP autorise `manifest-src`, `worker-src` et `connect-src` vers l'origine S3.

## Lecteur et confort d'écoute

La page du catalogue affiche une seule barre de lecture persistante au lieu de
97 lecteurs natifs empilés. Contrôles : lecture/pause, titre précédent/suivant,
recule et avance de 15 s, barre de progression à glisser, vitesse de 0,75× à 2×,
volume (0,5× à 3×), **minuteur de sommeil** (5/15/30/60 min), **file d'attente**
cliquable, **panneau de chapitres**, **lecteur plein écran**, reprise automatique
du dernier livre écouté, reconnexion jusqu'à 3 fois en cas de coupure réseau,
raccourcis clavier (Espace, ←/→, Échap) et Media Session (contrôles
système/mobile). Un seul `<audio preload="none">` existe dans la page : plus de
97 requêtes `Range` au chargement.

Les chapitres et la durée sont extraits **localement** avec ffprobe par
`scripts/extract_audio_chapters.py` (dry-run puis `--apply`, lot borné), stockés
dans `audio_chapters` et `objects.duration_seconds` (migration `0020`), puis
exposés dans `/api/public/library`.

Trois modes d'affichage sont disponibles via `?vue=liste|grille|immersif` :
liste compacte, grille de cartes avec pochettes, et vue immersive avec une
grande couverture et un bouton « Lancer l'écoute ». Les auteurs sont extraits
des noms `Auteur - Titre` et proposés comme filtres (`?auteur=`). Des boutons
de découverte mènent à « Reprendre l'écoute », « Nouveautés », « À découvrir »
et « Toute la bibliothèque ».

Les couvertures sont d'abord cherchées **localement** : tous les flux d'artwork
intégrés au fichier, puis une image stockée à côté de l'audio dans le même bucket
(`cover.jpg`, `folder.jpg`, image de même stem). L'image retenue est redimensionnée
par ffmpeg et servie par `/covers/{oid}.jpg`. Sans image locale, une **jaquette
typographique AURA** reste affichée : titre en serif, auteur, monogramme, tranche
et teinte stable choisie dans une palette bronze/vert/bleu/violet. La même
jaquette sert dans le hero, la vue liste et l'administration lorsqu'une image
est absente ou invalide.
Deux voies optionnelles permettent d'enrichir les livres récalcitrants : des
**candidats externes à valider** et l'**ajout manuel** d'une image (voir ci-dessous).
Aucun service externe n'est contacté par le déploiement ni par le cron de
rafraîchissement : les deux voies sont des commandes d'exploitation explicites.

Après mise à jour du script, une passe unique de rattrapage des livres déjà
sondés par l'ancienne version (premier flux seulement) se fait avec :

```bash
docker compose exec -T -e AURA_REPO_ROOT=/srv/api \
  api python - --reprobe --apply --limit 100 \
  < scripts/generate_audiobook_covers.py
```

Le timestamp de probe est rafraîchi, donc le cron quotidien ne retire pas ces
livres indéfiniment.

#### Candidats externes (validation obligatoire)

`scripts/cover_candidates.sh [limite] [itunes|openlibrary|all]` interroge des API
publiques (iTunes Search, Open Library) et écrit le fichier de revue canonique
dans `$AURA_DATA_DIR/cover-review/cover-candidates.json`, monté en lecture-écriture
dans le conteneur API. **Aucune image n'est publiée** : le fichier
liste les candidats par livre. Une régénération bornée conserve les livres déjà
appliqués, leurs choix et les entrées hors limite. Les résultats peuvent être
erronés (mauvaise édition) et les droits d'image doivent être vérifiés avant
publication.

Une fois un candidat retenu :

```bash
scripts/apply_cover.sh OBJECT_ID https://.../couverture.jpg
# ou, depuis un fichier local :
scripts/apply_cover.sh OBJECT_ID /chemin/couverture.jpg
```

Les deux formes redimensionnent l'image avec ffmpeg, la stockent en S3 avec SSE et
renseignent `cover_key`. Le fichier de revue marque le livre comme `applied`.

#### Validation et application en lot

La page **Administration → Couvertures** (`/admin/covers`) affiche les
propositions par livre. Le bouton **« Rechercher une couverture »** interroge
Google Books en priorité (par ISBN si fourni, sinon titre + auteur), puis Open
Library et iTunes en repli. Une clé `AURA_GOOGLE_BOOKS_API_KEY` évite le quota
limité de l'API publique. Chaque proposition conserve sa source, sa taille et
son URL d'origine ; la validation d'un choix ne publie rien, seule l'action de
lot explicitement confirmée écrit la couverture dans le catalogue. La lecture
exige `admin:read`, la recherche, la validation et l'application `admin:write`
avec CSRF.

Une page HTML locale reste disponible pour une revue hors ligne :

```bash
python3 scripts/render_cover_review.py \
  /srv/aura-storage/cover-review/cover-candidates.json \
  --output /srv/aura-storage/cover-review.html
```

Elle affiche les images, signale les concordances de titre/auteur et exporte un
`cover-selections.json` horodaté. Cette page ne contacte pas l'API AURA et ne
publie rien. Seuls les livres explicitement sélectionnés sont marqués `selected`
dans l'export ; les autres restent `pending`. L'export est ensuite fusionné avec
la revue courante : un export ancien est refusé, les livres appliqués sont
conservés et aucune entrée canonique ne peut disparaître.

Le lot se vérifie d'abord sans téléchargement ni écriture :

```bash
scripts/apply_cover_candidates.sh /chemin/cover-selections.json --dry-run
```

Après contrôle, la publication se lance sans `--dry-run` :

```bash
scripts/apply_cover_candidates.sh /chemin/cover-selections.json
# optionnel : traiter seulement les N premiers livres sélectionnés
scripts/apply_cover_candidates.sh /chemin/cover-selections.json --selected-limit 10
```

Le traitement n'accepte que des URL HTTPS déjà présentes dans la liste des
candidats et provenant d'Open Library Covers ou d'iTunes/Apple (`mzstatic.com`),
sans suivre les redirections. Les commandes sont verrouillées contre les
exécutions concurrentes et écrivent la revue de façon atomique. Il enregistre
l'avancement après chaque livre ; un échec est marqué `error` dans le fichier de
revue sans empêcher le traitement des suivants. Le mode `--dry-run` laisse le
fichier canonique inchangé.

La position est enregistrée via `/api/public/progress` (table `listen_progress`,
ajoutée par la migration cumulative `0018`, aujourd'hui `0020_audio_chapters`)
et restaurée à la sélection du livre. Le filtre `?q=` permet de rechercher un
titre ou un auteur côté serveur.

Les URL `/m/{slug}` utilisent un TTL dédié (`AURA_PUBLIC_MEDIA_TTL`, 12 h par
défaut) : le TTL de 15 min des intentions d'upload coupait la lecture d'un livre
long. Le lecteur tente jusqu'à **trois fois** de renouveler l'URL en cas d'erreur,
avec un message d'état dans la barre de lecture.

## Modèle d'identité

- Le visiteur s'authentifie avec **Google OAuth 2.0 Authorization Code + PKCE**
  (`api/google_oauth.py`). Le jeton d'identité est vérifié via `tokeninfo` :
  `aud`, `iss`, `exp`, `email_verified`, `email`, `sub`.
- Aucun secret ni jeton Google n'est conservé. La table `users` reçoit trois
  colonnes additives : `oauth_provider`, `oauth_sub`, `email`. Le `username` est
  dérivé du `sub` (hash SHA-256 tronqué), jamais de l'e-mail.
- Le role est `public`, absent de `ROLE_SCOPES` : capacités effectives = vide.
  Le cookie est distinct de celui de l'admin (`aura_public_session`),
  `HttpOnly`, `Secure`, `SameSite=Lax`, host-only.
- `GOOGLE_ALLOWED_EMAIL_DOMAINS` permet de restreindre l'accès à certains
  domaines e-mail (vide = tous les comptes Google vérifiés).

## Mise en place

### 1. Google Cloud Console
1. Créer/ouvrir le projet → **APIs & Services → OAuth consent screen**.
2. Type **External**, renseigner les infos requises, ajouter les scopes
   `openid`, `email`, `profile`, puis **publier** l'application. Tant qu'elle est
   en « Testing », seuls les comptes test peuvent se connecter.
3. **Credentials → Create Credentials → OAuth client ID → Web application**.
4. Dans **Authorized redirect URIs** (le seul champ obligatoire ici), ajouter
   exactement :
   `https://public.aura-storage.eurinhash.com/api/public/auth/callback`
   **Authorized JavaScript origins** peut rester vide : le navigateur n'appelle
   jamais Google directement, c'est l'API qui échange le code côté serveur. Si
   le formulaire exige une valeur, mettre uniquement l'origine du portail :
   `https://public.aura-storage.eurinhash.com` (pas de chemin, pas de `/` final,
   pas de domaine `app.*` ni S3).
5. Copier le Client ID et le Client Secret dans `.env` (jamais dans Git).

### 2. DNS et environnement
- Créer l'enregistrement DNS de `public.aura-storage.eurinhash.com` vers le VPS.
- Dans `.env` : `PUBLIC_DOMAIN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  optionnellement `GOOGLE_ALLOWED_EMAIL_DOMAINS` et `AURA_PUBLIC_SESSION_TTL`.
  `PUBLIC_DOMAIN` est obligatoire pour Compose : sans elle,
  `docker compose config --quiet` échoue (comme `APP_DOMAIN`).
- Traefik obtient le certificat Let's Encrypt via `certresolver=le` ; aucun port
  supplémentaire n'est ouvert.
- `docker compose config --quiet` puis déploiement selon `docs/DEPLOYMENT.md`.

### 3. Publier des livres
Le portail n'affiche que les **packs publiés** dont les pistes sont elles-mêmes
publiées. Depuis la console privée : sélectionner les fichiers audio →
`PacksDialog` → **Publier le manifest**. Chaque piste doit aussi avoir une URL
stable `/m/{slug}` (`PUT /api/v1/objects/{oid}/publication`).

### 3bis. Mise à jour périodique (cron contrôlé)

Le portail **ne publie rien automatiquement** : ajouter un fichier au bucket ou
même l'uploader via AURA ne le rend pas visible. La publication reste une
décision manuelle (`PacksDialog` ou `scripts/publish_audiobooks.py --apply`).

En revanche, l'enrichissement des livres **déjà publiés** est planifié :
`scripts/refresh_public_library.sh` relance les extractions de couvertures locales,
durées et chapitres avec une limite de 20 objets par passe, sous `flock`, et
marque chaque tentative (`cover_probe_at` / `chapters_probe_at`, migration
`0021`) pour ne jamais retraiter indéfiniment un fichier sans art intégré.
Une entrée cron est installée à 03:17 chaque jour et écrit dans
`/srv/aura-storage/audit/public-refresh.log` :

```
17 3 * * * cd /home/aura-admin/aura-storage && ./scripts/refresh_public_library.sh >> /srv/aura-storage/audit/public-refresh.log 2>&1
```

Un livre publié manuellement apparaît donc dès le rechargement suivant ; sa
pochette, sa durée et ses chapitres arrivent au plus tard au passage suivant
du cron.

### 4. Fichiers déjà présents dans le bucket
Les clés S3 sont des UUID générés par l'API : un préfixe de bucket ne permet pas
de reconnaître des livres audio. Le catalogue est la source de vérité. Pour
finaliser des intentions abandonnées, normaliser les types `audio/x-m4a` en
`audio/mp4` (seuls les types inline sont lisibles), attribuer les slugs et
publier un pack en une seule opération :

```bash
# aperçu, aucune écriture
AURA_REPO_ROOT=/srv/api docker compose exec -T -e AURA_REPO_ROOT=/srv/api \
  api python - --limit 50 < scripts/publish_audiobooks.py
# publication
AURA_REPO_ROOT=/srv/api docker compose exec -T -e AURA_REPO_ROOT=/srv/api \
  api python - --apply --limit 50 < scripts/publish_audiobooks.py
```

Le script ignore les objets dont les octets sont absents de S3 et exige SSE-S3
quand `AURA_REQUIRE_SSE=1`. Le manifeste JSON reste servi sur `APP_DOMAIN`
(`/p/<slug>.json`) ; le portail lit son propre catalogue via `/api/public/library`.
L'opérateur doit s'assurer des droits de diffusion des œuvres avant publication.

## Sécurité et limites connues

- `state` aléatoire lié à un cookie courte durée et supprimé après succès ;
  le code Google est à usage unique et le PKCE S256 empêche son échange sans le
  verifier d'origine. Pas de compteur serveur pour le `state` : un `state` volé
  seul ne suffit pas à obtenir une session. Échecs comptés dans le rate-limit
  de login, audit `google-login`.
- La page de connexion ne contient aucun JavaScript. La page du catalogue, elle,
  embarque un script inline pour le lecteur (pas de framework, pas de CDN) ; le
  token CSRF est injecté dans le formulaire de déconnexion et lu par le script
  pour `/api/public/progress` (le backend accepte champ de formulaire ou en-tête
  `X-CSRF-Token`). Aucune CSP dédiée n'est posée sur ces pages aujourd'hui.
- Pas d'upload public dans cette version. Le dépôt de fichiers par les visiteurs
  reste une phase ultérieure, avec quarantaine, quota et antivirus.
- Le portail dépend des gates de production du README (notamment le test de
  restauration de sauvegarde) avant une ouverture au grand public.
- L'échange du code et la vérification du jeton appellent Google depuis le
  conteneur API. Les réseaux `docs` et `storage` étant `internal: true` (aucune
  route par défaut), l'API rejoint un **réseau de sortie dédié**
  (`aura-oauth-egress`, 172.33.0.0/24). Elle n'est pas attachée au réseau
  public `edge` : SeaweedFS, `app` et `s3-landing` ne peuvent toujours pas
  l'appeler directement. Sans ce réseau, le callback échoue avec
  `token endpoint unavailable`.

## Tests

`pytest tests/test_public_portal.py tests/test_repository_parity.py
tests/test_compose_traefik_wiring.py` vérifient l'authentification, la parité
SQLite/PostgreSQL des nouvelles méthodes et le routage Traefik. Les appels
Google sont simulés : aucun test n'accède au réseau.
