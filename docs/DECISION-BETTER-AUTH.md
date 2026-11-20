# Décision — Better Auth + Google OAuth (#59)

## Décision initiale (2026-10-21)
**Différer** l'intégration de Better Auth + Google OAuth.

### Justification initiale
- Le pilote utilisait l'authentification admin-only (session cookie + CSRF) via `/api/v1/login`.
- Aucun besoin utilisateur externe à ce stade.
- Intégrer Better Auth augmentait la surface d'attaque et la complexité sans valeur immédiate.

## Réévaluation (2026-11-20)
Les conditions de reprise sont réunies : besoin d'authentification du grand public
confirmé, périmètre documenté dans [PUBLIC-PORTAL.md](PUBLIC-PORTAL.md), et
identifiants Google OAuth fournis par l'opérateur.

**Nouvelle décision :** intégrer **Google OAuth 2.0 (Authorization Code + PKCE)
directement dans l'API FastAPI**, sans Better Auth pour l'instant.

### Justification
- L'API possède déjà le magasin de sessions, les jetons CSRF, le rate-limit et
  l'audit. Un serveur d'identité supplémentaire dupliquerait ces responsabilités.
- Le flux OAuth est petit et isolé dans `api/google_oauth.py` ; aucune dépendance
  Python supplémentaire n'est nécessaire (vérification via `tokeninfo` de Google).
- Aucun secret Google n'est stocké : seul le `sub` (identifiant stable) et l'e-mail
  sont conservés, dans des colonnes additives de `users`.
- Le rôle `public` n'a **aucune** capacité objet : l'accès au catalogue n'est pas
  une élévation de privilèges.

### Ce qui reste différé
Better Auth reste différé. Il redevient pertinent si le portail doit gérer
plusieurs fournisseurs sociaux, la récupération de compte, ou une gestion
d'utilisateurs auto-hébergée. La décision sera alors à réécrire ici.

### Périmètre de sécurité
- Cookie dédié `aura_public_session`, `HttpOnly`, `Secure`, `SameSite=Lax`
  (obligatoire pour le retour depuis Google), host-only sur `PUBLIC_DOMAIN`.
- `state` à usage unique + PKCE S256 ; échecs comptés dans le rate-limit de login.
- Redirection fixe vers `/` sur l'hôte public (aucune redirection fournie par
  le client, donc pas d'open redirect).
- `/api/v1/*` n'est pas routé sur l'hôte public ; voir `docker-compose.yml`.
