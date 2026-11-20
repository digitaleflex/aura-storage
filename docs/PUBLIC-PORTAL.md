# Portail public (livres audio)

Direction visuelle et décisions de l'interface : [PUBLIC-PORTAL-UI.md](PUBLIC-PORTAL-UI.md).

Le portail public est un sous-domaine dédié, `PUBLIC_DOMAIN` (pilote :
`public.aura-storage.eurinhash.com`). Il permet à un visiteur connecté avec son
compte Google de parcourir les packs publiés et d'écouter leurs pistes audio.
Il ne donne **aucun** accès aux objets, dossiers ou routes d'administration.

## Ce qui est exposé

| Chemin (sur `PUBLIC_DOMAIN`) | Rôle |
|---|---|
| `GET /` | page de connexion pour les anonymes, puis catalogue HTML sans JavaScript avec lecteur `<audio>` pour les sessions connectées |
| `GET /api/public/auth/google` | démarre le flux Google (state + PKCE) |
| `GET /api/public/auth/callback` | vérifie Google, crée la session, redirige vers `/` |
| `GET /api/public/me` | identité + jeton CSRF de la session publique |
| `POST /api/public/logout` | détruit la session (CSRF requis) |
| `GET /api/public/library` | catalogue publié (JSON), pour une future UI React |
| `GET /m/{slug}` | redirection média publique déjà existante, routée ici aussi pour le lecteur |

Les fichiers eux-mêmes sont servis par les liens `/m/{slug}` déjà existants :
une redirection 302 vers une URL S3 présignée de courte durée, avec `Range`
(seek). Aucun octet ne traverse l'API. Le lecteur HTML pointe directement sur
ces URL ; la CSP du bord n'impose pas de `media-src` restrictive.

`/api/v1/*`, `/s/*`, `/f/*`, `/p/*` et la console React restent sur `APP_DOMAIN`.

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

## Sécurité et limites connues

- `state` aléatoire lié à un cookie courte durée et supprimé après succès ;
  le code Google est à usage unique et le PKCE S256 empêche son échange sans le
  verifier d'origine. Pas de compteur serveur pour le `state` : un `state` volé
  seul ne suffit pas à obtenir une session. Échecs comptés dans le rate-limit
  de login, audit `google-login`.
- La page ne contient aucun JavaScript ; le token CSRF est injecté dans le
  formulaire de déconnexion (le backend l'accepte en champ de formulaire ou en
  en-tête `X-CSRF-Token`).
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
