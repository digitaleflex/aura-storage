# Lot 0 — Accès média unifiés

- **Date :** 24 novembre 2026
- **Périmètre :** `/m/{slug}`, `/a/{token}`, HLS et sous-titres WebVTT
- **Statut :** corrections appliquées et tests ciblés validés ; déploiement VPS non exécuté

## Objectif

Empêcher qu'une playlist HLS, un segment vidéo ou un fichier de sous-titres contourne la politique appliquée au média principal. Rendre également accessible le mécanisme de grant révocable `/a/{token}` via les points d'entrée configurés.

## Corrections appliquées

1. **Policies centralisées**
   - `/m/{slug}`, `/hls/{slug}.m3u8`, `/hls/{slug}/{segment}` et `/m/{slug}/subtitles.vtt` partagent `_guard_public_media_slug`.
   - L'authentification ou le contrôle premium a lieu avant toute recherche dans le catalogue.
   - Les slugs restreints répondent `404` avant même le contrôle de session, sans consultation du catalogue, présignature ou événement de vue.
   - Les listes de slugs sont normalisées en minuscules au chargement de la configuration.

2. **Grants**
   - L'émission et la révocation d'un grant exigent `objects:read` **et** `objects:write` ; une identité en écriture seule ne peut plus obtenir une lecture publique.
   - Traefik n'enregistre plus le chemin des requêtes, uvicorn désactive son access log et nginx désactive l'access log de `/a/`. Les jetons ne sont pas journalisés par les logs d'accès applicatifs.

3. **Routage**
   - `/a/` est routé vers l'API par Traefik sur `APP_DOMAIN` et `PUBLIC_DOMAIN`.
   - `/hls/` est routé vers l'API sur `PUBLIC_DOMAIN`.
   - nginx possède un fallback `/a/` si le routeur Traefik de partage est absent.
   - `/api/v1/*` reste absent du routeur public.

4. **Durées de validité**
   - La durée par défaut d'un grant `/a/{token}` passe de 12 h à **15 min**.
   - L'URL S3 émise lors de l'utilisation du grant ne peut pas dépasser la durée restante du grant.
   - Le TTL long de `/m/{slug}` reste inchangé pour la lecture de livres longs.

5. **En-têtes**
   - Les playlists et redirections HLS/sous-titres ajoutent `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` et `X-Robots-Tag: noindex, nofollow`.
   - Les playlists HLS restent en `Cache-Control: no-store`.

## Configuration

| Variable | Défaut | Effet |
|---|---:|---|
| `AURA_PUBLIC_MEDIA_REQUIRE_AUTH` | `1` | Exige une session publique pour les médias et leurs dérivés |
| `AURA_PUBLIC_REQUIRE_PREMIUM` | `1` | Exige un compte premium pour les médias et leurs dérivés |
| `AURA_PUBLIC_MEDIA_OPEN_SLUGS` | vide | Liste de slugs explicitement publics |
| `AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS` | vide | Liste de slugs interdits sur toutes les routes publiques de média |
| `AURA_PUBLIC_ACCESS_GRANT_TTL` | `900` | Durée d'un grant service `/a/{token}` |
| `AURA_PUBLIC_MEDIA_TTL` | `43200` | Durée de l'URL S3 émise par `/m/{slug}` |

Un environnement existant qui définit encore `AURA_PUBLIC_ACCESS_GRANT_TTL=43200` conserve volontairement l'ancienne valeur. Pour appliquer le nouveau défaut, retirer cette variable du `.env` ou la régler sur `900`.

## Migration avant déploiement

- Inventorier les lecteurs HLS/WebVTT anonymes existants. Les embeds légitimes doivent être ajoutés à `AURA_PUBLIC_MEDIA_OPEN_SLUGS` ou utiliser une session publique.
- Vérifier la valeur de `AURA_PUBLIC_ACCESS_GRANT_TTL` dans le `.env` du VPS ; une valeur explicite `43200` remplace le nouveau défaut.
- Pour une lecture longue avec `/a/{token}`, prévoir le renouvellement du grant avant expiration. Le client ne doit pas supposer qu'une URL de 15 minutes suffit pour un livre entier.
- Purger ou faire tourner les historiques de logs qui pourraient déjà contenir d'anciens jetons `/a/`.

## Validation effectuée

```bash
.venv/bin/python -m pytest -q \
  tests/test_public_portal_security.py \
  tests/test_hls.py \
  tests/test_compose_traefik_wiring.py \
  tests/test_public_portal.py \
  tests/test_publication.py \
  tests/test_security_isolation.py

docker compose config --quiet
```

Résultat : **111 tests ciblés réussis** et configuration Compose valide.

Les tests couvrent notamment :

- refus `401` anonyme sur le média et tous ses dérivés ;
- accès premium cohérent sur le média et tous ses dérivés ;
- slug explicitement public ;
- slug restreint bloqué avant consultation du catalogue ;
- grant révocable, expiré et TTL de redirection borné ;
- refus d'une identité machine en écriture seule ;
- absence des chemins de grants dans les logs d'accès configurés ;
- présence des routes `/a/` et `/hls/` dans Traefik ;
- fallback nginx `/a/` sans access log.

## Déploiement

Après revue du diff et sauvegarde de la configuration :

```bash
docker compose config --quiet
docker compose up -d --build traefik api app
```

Vérifier ensuite, avec un slug publié et restreint :

- `/m/{slug}` répond `404` ;
- `/hls/{slug}.m3u8` répond `404` ;
- `/m/{slug}/subtitles.vtt` répond `404` ;
- un visiteur anonyme reçoit `401` lorsque le média exige une session ;
- un compte premium reçoit la playlist ou la redirection attendue.

Vérifier aussi qu'un token de test `/a/...` n'apparaît dans aucun log Traefik, API ou nginx après une requête. Les logs historiques doivent être traités séparément.

## Limites résiduelles

- Une URL S3 déjà émise reste valide jusqu'à son expiration, même après révocation du grant.
- Les logs historiques antérieurs à cette correction peuvent encore contenir des jetons ; ils doivent être purgés ou archivés avec des droits restrictifs.
- Les segments HLS déjà présignés restent valides jusqu'à 300 secondes.
- Le cache hors ligne du portail peut conserver un fichier après déconnexion ou suppression du compte.
- `/m/{slug}` conserve un TTL par défaut de 12 h pour ne pas couper la lecture de livres longs.
- L'intégration de l'adaptateur audiobook avec `/a/{token}` doit être validée séparément.
- Plesk n'est pas utilisé : le routage livré dans ce lot concerne l'infrastructure custom Traefik + nginx.

## Prochaines actions du Lot 0

1. Valider une restauration indépendante hors site sur le VPS.
2. Tester la persistance après redémarrage réel.
3. Remplacer le worker d'import stub par un traitement effectif.
4. Définir le rapprochement des identités publiques et auditeur.
5. Mettre à jour les documents de statut qui ne correspondent plus au code.
