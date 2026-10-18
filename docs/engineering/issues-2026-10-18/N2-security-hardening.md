## Contexte
Revue de sécurité du 2026-10-18. Points non couverts par les issues existantes.

## Travail (branche `fix/security-hardening`)
- [x] **Sessions** : le cookie porte un jeton aléatoire de 256 bits, la base ne stocke que son SHA-256 (comme les jetons machine). Une fuite de la base ou d'une sauvegarde ne donne plus de sessions valides. Les sessions expirées sont purgées. *Effet du déploiement : tout le monde se reconnecte une fois.*
- [x] **Login** : un identifiant inconnu fait quand même une vérification argon2 (plus d'énumération des comptes par le temps de réponse).
- [x] **CSP** sur l'application (`app/nginx.conf` rendu en template pour autoriser l'hôte S3 en `connect-src`).
- [x] **HSTS** sur tous les routeurs publics (middleware Traefik).
- [x] **Dashboard Traefik** : liste d'IP autorisées avant BasicAuth (`DASHBOARD_ALLOWED_IPS`, fermé par défaut) — aligne le Compose sur le README.
- [x] **Journal d'audit** sur un volume nommé (il était perdu à chaque recréation du conteneur).

## Critères code
- [x] `tests/test_session_hardening.py` (5) ; suite complète verte ; parité PostgreSQL vérifiée.
- [x] `docker compose config`, `nginx -t` sur le template rendu, chargement du front sous CSP sans violation (Chromium headless).

## Critères pilote
- [ ] `DASHBOARD_ALLOWED_IPS` renseigné (plage VPN) avant déploiement, sinon le dashboard devient inaccessible.
- [ ] Après déploiement : en-têtes `Strict-Transport-Security` et `Content-Security-Policy` présents ; upload/téléchargement OK dans le navigateur ; le fichier d'audit survit à `docker compose up -d --force-recreate api`.

## Hors périmètre
Renouvellement glissant des sessions, « déconnecter toutes les sessions » (à ouvrir si besoin).
