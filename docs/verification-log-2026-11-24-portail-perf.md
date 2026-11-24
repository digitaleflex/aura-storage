# Journal de vérification — 2026-11-24 (portail public, moteur de transfert, perf stockage)

> Instance de [verification-log-template.md](verification-log-template.md). Aucun secret, token, clé SSE, URL signée ni contenu de fichier privé n'est reproduit ici. Les valeurs de configuration sensibles sont désignées par leur nom, jamais par leur valeur.

## 1. Métadonnées

- **Date (UTC) :** 2026-11-24
- **Opérateur :** session automatisée (aura-admin workspace) + actions sur le pilote `aura-001-*`
- **Dépôt :** `digitaleflex/aura-storage`, branche `main`
- **Périmètre :** moteur de transfert (Lots 1-3), portail public (#293-#306), configuration d'exploitation, Traefik/SeaweedFS/PostgreSQL, sauvegarde
- **Méthode :** tests offline (pytest/vitest), `docker compose config`, commandes `docker exec` en lecture, requêtes HTTP réelles sur les domaines publics

## 2. Résumé des livraisons

| Lot | Commits clés | Résultat |
|---|---|---|
| Lot 1 — intégrité du moteur | `76c1a60`, `0d840da` | Expiration multipart nettoyée, CAS sur le sweep, scrubber → `suspect`, compteurs de débit partagés, grants `/a/` révocables |
| Lot 2 — client de transfert | (voir `git log` du 2026-11-24) | Timeout d'inactivité du PUT, polling `verifying` borné, erreurs effacées sur progrès, retries cohérents, deadlines des appels de contrôle |
| Lot 3 — configuration | `0d840da` | Alias `AURA_RECONCILE_INTERVAL_S`, quotas/AV câblés, deadline du commit, réservation filtrée, plafond 5 000 parties |
| Roadmap portail #293-#306 | `84a81da`, `811fffb`, `58d9db3`, `615d2fa` | Accessibilité lecteur, perf catalogue, recommandations partagées, playlists, stats, récap, recherche naturelle, docs alignées |
| Perf infra | `5ae7cef`, `9002e7c`, `38f762e`, `615d2fa` | HTTP/3, responseHeaderTimeout, volumes 10 Gio, vacuum nocturne, index composites, backup corrigé |

## 3. Preuves exécutées

### 3.1 Tests et CI

- Suite backend locale : **661 passés, 39 skippés** (après migration `0027_perf_indexes`).
- Tests unitaires frontend : **75 passés** ; `npm run build` vert ; lint 0 erreur (18 avertissements préexistants).
- CI GitHub sur `615d2fa` : workflows `Quality` et `Validate storage configuration` **au vert**.
- Les 2 échecs PostgreSQL observés sur `a0078d6` (placeholders `?` sous psycopg dans un test, FK d'un grant révoqué) ont été corrigés dans le même commit.

### 3.2 Configuration effective sur le pilote

Relevé dans le conteneur `aura-001-api` après recréation de l'image :

```
capacity_bytes        = 1099511627776   (1 Tio, valeur d'endiguement)
reconcile_interval_s  = 300
grant_ttl             = 900
reco_engine           = audiobook
schema_migrations     = 0027_perf_indexes
```

- L'avertissement `AURA_MULTIPART_ENABLED=1 / AURA_STORAGE_CAPACITY_BYTES=0` a disparu des logs.
- `/health/live` → `{"status":"live"}` ; conteneur `healthy`.
- `volume.list` → `Topology volumeSizeLimit:10240 MB`.

### 3.3 HTTP/3, buffering et timeouts

- `docker inspect aura-001-traefik` : ports `443/tcp` **et `443/udp`** publiés.
- Traefik 3.7.14 : `--entrypoints.websecure.http3=true`, `--serverstransport.forwardingtimeouts.responseheadertimeout=120s`.
- Aucun middleware `buffering` sur le routeur S3 (`aura-s3.middlewares=aura-hsts@docker` uniquement).
- `ufw.conf` : `ENABLED=no` → UDP/443 non bloqué sur l'hôte. Si UFW est réactivé : `sudo ufw allow 443/udp`.
- Le client `curl` de la session ne supporte pas `--http3` : **handshake QUIC non vérifié de bout en bout**, seulement la configuration et l'exposition du port.

### 3.4 Range et compression

Requête réelle sur un objet publié via URL présignée générée localement (signature non journalisée) :

```
STATUS          : 206
Content-Type    : audio/mpeg
Content-Length  : 1024
Content-Range   : bytes 0-1023/4601783
Accept-Ranges   : bytes
Content-Encoding: None
```

`gzip_types` d'nginx exclut `audio/*` et `video/*` : aucune compression dynamique des flux média.

### 3.5 Vacuum SeaweedFS

- Script `scripts/seaweedfs-vacuum.sh` (lock → `volume.vacuum -garbageThreshold=0.3` → unlock).
- Cron installé sur l'hôte : `0 3 * * * … >> /srv/aura-storage/audit/seaweedfs-vacuum.log 2>&1`.
- Exécution de contrôle : **no-op attendu** (`DeletedBytes` ≈ 370 Mo sur ~62 Go, sous le seuil de 30 %) ; cluster déverrouillé, `volume.list` stable.

### 3.6 Smoke HTTP

| URL | Code |
|---|---|
| `https://public.aura-storage.eurinhash.com/` | 200 |
| `https://public.aura-storage.eurinhash.com/livre/<oid publié>` | 200 |
| `https://app.aura-storage.eurinhash.com/` | 200 |

## 4. Décisions et limites

1. **`Cache-Control: immutable` n'est pas appliqué à `/m/<slug>` ni à `/a/<token>`.** Ces URL sont mutables par design (remplacement de contenu sous un même slug, grants révocables). L'immutabilité reste sur les assets hashés (`/assets/`) ou doit être portée par un CDN/site de cours qui possède ses propres URL immuables.
2. **Cloudflare non activé en proxy orange.** Les deux enregistrements DNS sont `proxied=false`. Le domaine S3 sert des `PUT` présignés de 50 Gio qui dépasseraient la limite de corps des plans CDN courants. Un sous-domaine média dédié et un plan vérifié sont nécessaires avant activation.
3. **Capacité 1 Tio = endiguement**, pas la capacité contractuelle. Le panneau InterServer reste à confirmer (le système invité annonce 2,9 To sur un seul disque partagé).
4. **Pool de connexions PostgreSQL** non implémenté — suivi dans l'issue #325.
5. La sauvegarde locale n'est **pas** une copie hors-site ; la règle 3-2-1 impose une réplication externe (issue #9).

## 5. Gardes et suivis ouverts

- Roadmap #293-#306 : **toutes fermées**.
- Reste ouvert : #315 (déploiement complet), #316/#317 (preuves multipart), #318 (tests audiobook PostgreSQL en CI), #319-#324 (dette fonctionnelle/docs), #325 (pool DB).
- Gates historiques : #5/#9/#10/#11/#23 (profil serveur, backup/restore, reboot, E2E réel, go/no-go).

## 6. Sources

- `docs/PUBLIC-PORTAL-ROADMAP.md`, `docs/OPERATIONS.md`, `docs/ETAT-DES-FONCTIONNALITES.md`
- `docs/verification-log-2026-11-16-multipart-proofs-4.48.md` (UNKNOWNs encore ouverts)
- `git log` du 2026-11-24 et sorties CI GitHub.
