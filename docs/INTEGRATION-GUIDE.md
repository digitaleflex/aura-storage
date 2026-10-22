# Guide d'intégration — récupérer l'URL d'un fichier depuis un autre service

Pour un service (backend, tâche planifiée, autre application) qui doit lire des
fichiers stockés dans AURA. Les étapes marquées « vérifié » ont été exécutées
contre l'API locale (voir *Ce qui a été testé*).

## Le principe

* **Il n'y a pas d'URL permanente.** Le service demande à l'API une URL
  **présignée, de courte durée** (15 minutes par défaut), puis lit les octets
  **directement dans le stockage** : ils ne passent jamais par l'API.
* L'authentification se fait avec un **jeton d'identité de service**
  (`Authorization: Bearer …`). L'URL obtenue porte sa propre signature : on ne
  lui ajoute **aucun** en-tête d'authentification.
* Une URL est un secret tant qu'elle n'a pas expiré : ne la journalisez pas, ne
  la mettez pas dans un ticket ou un message.

## 1. Créer l'identité de service (une fois, par un administrateur)

Dans l'application : **Administration → Identités de service**. Ou en API, avec
une session administrateur (cookie + jeton CSRF) :

```bash
curl -X POST https://app.<domaine>/api/v1/admin/identities \
  -b "aura_session=$SESSION" -H "X-CSRF-Token: $CSRF" -H 'content-type: application/json' \
  -d '{"space_id": "<id de l’espace>", "name": "service-lecture",
       "scopes": ["objects:read"], "ttl_seconds": 7776000}'
# -> { "id": …, "scopes": […], "expires_at": …, "token": "aura_…" }   (vérifié)
```

* Le **jeton n'est affiché qu'une fois** : rangez-le dans le gestionnaire de
  secrets du service. Perdu → faire tourner le jeton (*rotate*) ; compromis →
  révoquer (*revoke*), depuis la même page.
* **Scopes** : `objects:read` pour lire ; ajoutez `objects:write` seulement si le
  service doit aussi envoyer des fichiers. Le moins possible.
* **Espace** : une identité voit **tous les fichiers de son espace**, y compris
  ceux importés par des utilisateurs (un utilisateur humain, lui, ne voit que les
  siens). Donnez-lui un espace dédié si les fichiers ne doivent pas tous lui être
  accessibles.
* `ttl_seconds` : durée de vie du jeton lui-même (optionnel).

## 2. Obtenir l'URL d'un fichier

```bash
export AURA_API=https://app.<domaine>      # l'hôte de l'application, pas celui du S3
export AURA_TOKEN=aura_…

curl -X POST "$AURA_API/api/v1/objects/$OID/download-intent" \
  -H "Authorization: Bearer $AURA_TOKEN"
```

Réponse (vérifié) :

```json
{ "id": "…", "download_url": "https://s3.<domaine>/…?X-Amz-…", "method": "GET",
  "expires_in": 900, "expires_at": 1792689634,
  "display_name": "video-demo.mp4", "content_type": "video/mp4", "size_bytes": 1048576,
  "checksum_sha256": "…", "checksum_algorithm": "sha256",
  "range_supported": true, "accept_ranges": "bytes", "content_encoding": null }
```

Ensuite : un simple `GET download_url`, sans en-tête d'authentification.
`preview-intent` fonctionne de la même façon et renvoie `preview_url` (affichage
« en ligne », types de la liste blanche seulement, sinon 415).

Exemples complets, testés :

* Python (bibliothèque standard) : [`examples/get_file_url.py`](examples/get_file_url.py)
  ```bash
  python3 get_file_url.py --id "$OID"                       # affiche l'URL
  python3 get_file_url.py --search rapport --kind preview    # cherche par nom
  python3 get_file_url.py --id "$OID" --save out.bin --range 0-1048575
  ```
* Node ≥ 18 (sans dépendance) : [`examples/get-file-url.mjs`](examples/get-file-url.mjs)
  ```bash
  node get-file-url.mjs "$OID" download
  ```

## 3. Retrouver l'identifiant d'un fichier

```bash
curl "$AURA_API/api/v1/objects?q=rapport&status=available&limit=20&offset=0" \
  -H "Authorization: Bearer $AURA_TOKEN"            # (vérifié)
```

Filtres : `q` (sous-chaîne du nom), `status` (`available`, `pending`, `verifying`,
…), `content_type`, `folder_id` (`root` = hors dossier), `min_size`/`max_size`,
`created_after`/`created_before` (secondes epoch), `sort` (`created_at`,
`display_name`, `size_bytes`), `order`. `limit` : 100 au plus ; paginez avec
`offset`. Chaque élément porte `id`, `display_name`, `content_type`,
`size_bytes`, `checksum_sha256`, `status`.

## 4. Vidéo et audio (lecture en continu, avance rapide)

* Le champ `range_supported: true` / `accept_ranges: "bytes"` indique que l'API
  annonce les requêtes partielles. Le lecteur d'un navigateur ou un `GET` avec
  `Range: bytes=a-b` (voir `--range`) lit une portion sans tout télécharger.
  **Non vérifié sur le SeaweedFS réel** (seul le comportement de l'API l'a été).
* **Dans une page web d'un autre site**, `<video src="URL">` et `<img src="URL">`
  fonctionnent sans CORS. Un `fetch()` depuis le navigateur, lui, exige le CORS du
  stockage, qui n'autorise que l'origine de l'application : faites l'appel côté
  serveur.
* **Expiration en cours de lecture** : l'URL dure 15 minutes
  (`AURA_INTENT_TTL`, la même valeur sert aux envois). Pour une vidéo plus longue,
  redemandez une URL avant l'échéance (`expires_at`) ou après un 403 du stockage.
* Formats : l'API ne transcode pas ; un codec que le lecteur ne connaît pas
  (par exemple HEVC) ne se lira pas.

## 5. Erreurs

| Code | Sens | Que faire |
|---|---|---|
| 401 | jeton absent, faux ou expiré | vérifier / faire tourner le jeton |
| 403 | il manque le scope (`objects:read`), ou la route est réservée aux humains | corriger les scopes de l'identité |
| 404 | objet inexistant **ou d'un autre espace** (indiscernables) | vérifier l'id et l'espace |
| 409 | l'objet n'est pas `available` (envoi ou vérification en cours) | réessayer plus tard |
| 415 | pas d'aperçu en ligne pour ce type | utiliser `download-intent` |
| 429 | trop d'**échecs d'authentification** depuis cette adresse IP (`AURA_M2M_RATE_LIMIT`, 60 par minute) | attendre `Retry-After` secondes |
| 403 du stockage | URL expirée | redemander une URL |

Le 429 ne limite **pas** les appels valides : 70 appels valides consécutifs ont
tous répondu 200 lors du test local. Un jeton erroné qui boucle, en revanche,
finit par bloquer l'adresse IP.

## 6. Envoyer un fichier depuis un service (scope `objects:write`)

1. `POST /api/v1/objects/upload-intents` avec `{"display_name", "size_bytes",
   "content_type"}` → réponse avec `upload_url` et `headers` (vérifié).
2. `PUT upload_url` avec **exactement** ces `headers` (`Content-Type`,
   `x-amz-server-side-encryption`, `If-None-Match`) et le contenu.
3. `POST /api/v1/objects/{id}/commit` : le serveur vérifie la taille et le
   SHA-256 ; le fichier passe `available`, ou `202 verifying` s'il est gros
   (interroger l'objet jusqu'à `available`). Ajoutez un `Idempotency-Key` pour
   pouvoir rejouer sans doublon.

Les étapes 2 et 3 n'ont pas été exécutées ici (pas de stockage réel).

## 7. Pour une personne sans compte

Un service **ne peut pas** créer de lien de partage (création réservée à un
humain, pour qu'un jeton volé ne produise pas de liens qui survivent à sa
révocation). Un utilisateur crée le lien depuis l'application ; voir
[OBJECT-SHARING.md](OBJECT-SHARING.md).

## Ce qui a été testé

* Contre une API locale avec base de fichiers et secrets jetables : création
  d'une identité, `upload-intents` avec son jeton, `409` tant que l'objet est en
  attente, liste filtrée, `download-intent` et `preview-intent` (`range_supported`
  présent), `401` sans jeton ou avec un faux, `404` pour un id inconnu, `403`
  sans le scope, `403` d'une route d'administration, 70 appels valides sans `429`.
* Le script Python : `tests/test_integration_examples.py` (URL, recherche,
  `--save`, `--range`, messages d'erreur ; stockage simulé par un serveur local
  qui respecte `Range` et vérifie qu'aucun jeton n'est envoyé au stockage).
* Le script Node : exécuté à la main (succès et jeton invalide), sans test automatique.
* **Non testé** : la lecture d'octets sur un vrai SeaweedFS (signature, `Range`,
  expiration), l'envoi (étapes 2 et 3), le déclenchement du `429`.
