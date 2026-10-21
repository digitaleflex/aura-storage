# Moteur de transfert AURA — ce qui manque et algorithmes à développer (booster)

**Date :** 2026-10-21 · **Complément de** `transfer-engine-audit.md` et `transfer-engine-audit-2026-market.md`.

Objectif : lister **tout** ce qui manque, avec pour chaque point l'**algorithme cible** à développer, dans l'ordre de priorité. Aucun code n'est modifié par ce document.

---

## A. P0 — Intégrité et cohérence (à faire avant tout)

### A.1 G1 — Contrôle d'intégrité post-publication (invariant S10)

**Problème** : après `available`, la PUT URL reste valide jusqu'au TTL, `commit` short-circuite sans toucher le stockage, et aucun versioning/object-lock n'existe. Les octets peuvent être remplacés silencieusement.

**Algorithmes à développer** :

1. **Révocation de capability après publication** — au moment de `mark_available`, invalider la PUT capability :
   - soit supprimer l'objet puis re-le mettre sous une clé versionnée (coût),
   - soit signer la PUT URL avec une condition `x-amz-meta-aura-state=pending` et refuser tout PUT dont le header diffère (condition S3 `If-Match`/`If-None-Match`).
   - Recommandé : utiliser `If-None-Match: *` sur le PUT initial (empêche l'écrasement) + rotation de clé par version (`aura/<space>/<actor>/<uuid4>/v2`) si re-upload voulu.

2. **Re-vérification paresseuse** — à chaque `download-intent` ou `commit` répété, comparer `HEAD` (taille + ETag/SSE) à la ligne ; si divergence → marquer `suspect` et bloquer le téléchargement jusqu'à re-vérification complète (re-hash). Algorithme :
   ```
   def verify_available(row, s3ops):
       head = s3ops.head(row.bucket, row.key)
       if head is None or head.size != row.size_bytes or head.sse != "AES256":
           raise IntegrityError("head mismatch")
       # optionnel, coûteux : re-hash complet si last_verified_at > N jours
       if row.last_verified_at is None or age(row.last_verified_at) > VERIFY_TTL:
           digest = s3ops.stream_sha256(row.bucket, row.key, max_bytes=row.size_bytes)
           if digest != row.checksum_sha256: raise IntegrityError("hash mismatch")
           row.last_verified_at = now()
   ```

3. **Object-lock / retention** — activer le versioning SeaweedFS sur le bucket + object-lock en mode `GOVERNANCE` avec retention courte (ex. 1 jour) pour empêcher l'écrasement par un tiers qui aurait la PUT URL. Gate : vérifier que SeaweedFS 4.48 supporte `x-amz-object-lock-mode` (probe).

### A.2 G2 — Réconciliation automatique + balayage inverse

**Problème** : rien ne déclenche `reconcile_pending` ; les octets des statuts `failed`/`aborted`/`deleted`/replay-retiré ne sont sélectionnés par aucun sweep ; `/admin/orphans` ne scanne que `available`.

**Algorithmes à développer** :

1. **Scheduler intégré** (option A) — thread daemon dans l'API FastAPI (`@app.on_event("startup")`) qui exécute toutes les `AURA_RECONCILE_INTERVAL_S` secondes :
   ```
   while running:
       try: reconcile_pending(limit=AURA_RECONCILE_BATCH)
       except Exception: log, backoff (exponential, cap 5 min)
       sleep(interval)
   ```
   Option B (recommandée pour pilot) : timer systemd/cron externe appelant `POST /admin/reconcile` — plus simple à auditer, pas de thread dans le processus API.

2. **Balayage inverse (storage → catalogue)** — lister les objets du bucket (SeaweedFS `ListObjectsV2` paginé) et comparer à `repo.list_all_keys()` :
   ```
   def reverse_sweep(bucket, repo, s3ops, dry_run=True):
       orphans = []
       for obj in s3ops.list_objects(bucket, prefix="aura/"):
           if repo.get_by_bucket_key(bucket, obj.key) is None:
               orphans.append(obj)
               if not dry_run: s3ops.delete_object(bucket, obj.key)
       return orphans
   ```
   Garde-fous : ne jamais supprimer un objet dont la ligne est `pending` récente (< grace) ; dry-run par défaut ; pagination avec continuation token ; rate-limit pour ne pas saturer SeaweedFS.

3. **Couverture des statuts terminaux** — étendre `reconcile_pending` pour accepter un filtre de statuts :
   ```
   def reconcile_terminal(statuses=["failed","aborted","deleted"], limit=N):
       rows = repo.list_by_status(statuses, older_than=now()-RETENTION, limit=N)
       for row in rows:
           try: s3ops.delete_object(row.bucket, row.key)
           except: continue  # retry au prochain sweep
           repo.delete_object_row(row.id)  # ou set_status purged
   ```
   Politique de rétention : `failed`/`aborted` gardés 7 j (debug), `deleted` gardés selon la politique de corbeille, puis purge automatique.

### A.3 G3 — Contrat de taille + timeouts

**Algorithmes à développer** :

1. **Comparaison `expected_size_bytes` au commit** :
   ```
   if row.expected_size_bytes is not None and head.size != row.expected_size_bytes:
       repo.set_status(row.id, "failed")
       s3ops.delete_object(...)  # best-effort, comme la branche SSE
       raise HTTPException(422, "size mismatch with declared size")
   ```
   Ajouter aussi la vérification `streamed_total == head.size` (déjà fait) et `streamed_total == row.expected_size_bytes`.

2. **Timeouts client S3** (`api/s3.py`) :
   ```
   Config(
     connect_timeout=10,
     read_timeout=60,        # par objet, pas par chunk
     retries={"max_attempts": 3, "mode": "adaptive"},
   )
   ```
   + deadline globale par commit (`AURA_COMMIT_DEADLINE_S`, défaut 300 s) avec `asyncio.wait_for` ou `signal` ; si dépassé → marquer `failed`, garder la ligne, retourner 504.

3. **Proxy app→api** (`app/nginx.conf`) : ajouter `proxy_read_timeout 300s; proxy_send_timeout 300s;` sur la route commit (ou passer par un endpoint dédié long-running).

---

## B. P1 — Concurrence et robustesse

### B.1 G4 — Compare-and-set (CAS) sur les transitions

**Algorithmes** : ajouter une colonne `version INTEGER NOT NULL DEFAULT 1` (ou utiliser `status` comme précondition) et modifier les requêtes :

```sql
-- mark_available (SQLite + PG)
UPDATE objects SET status='available', size_bytes=?, checksum_sha256=?, version=version+1
WHERE id=? AND status='pending' AND version=?;
-- retourne rowcount ; 0 = conflit → 409
```

```sql
-- set_status (abort/delete/expire)
UPDATE objects SET status=?, version=version+1
WHERE id=? AND status IN (allowed_from) AND version=?;
```

Côté API :
```
def mark_available(repo, oid, size, sha, expected_version):
    n = repo.mark_available_cas(oid, size, sha, expected_version)
    if n == 0:
        # relire pour savoir si déjà available (idempotence) ou conflit
        row = repo.get(oid)
        if row.status == "available" and row.checksum_sha256 == sha:
            return row  # idempotent success
        raise ConflictError("concurrent transition")
```

### B.2 G5 — Nettoyage automatique des statuts terminaux

Voir A.2 point 3 (balayage par statut avec rétention). Ajouter une colonne `terminal_since TIMESTAMPTZ` mise à jour par `set_status` pour les statuts terminaux.

### B.3 G6 — Correction du replay à la limite de la grâce

**Algorithme** : au replay, si `now > expires_at + grace - REFRESH_MARGIN` (ex. 60 s), ne pas réutiliser l'intent : créer une nouvelle ligne `pending` (retirer l'ancienne comme `expired` + supprimer ses octets) et signer une URL avec un `expires_at` frais. Sinon, signer une URL mais avec `expires_at` = `min(original_expires_at, now + TTL)` et documenter la fenêtre.

```
if now + AURA_REPLAY_REFRESH_MARGIN > row.expires_at:
    # retire l'ancien intent
    s3ops.delete_object(row.bucket, row.key)  # best-effort
    repo.set_status(row.id, "expired")
    # crée un nouvel intent (chemin normal upload-intent)
    return create_new_intent(...)
else:
    url = s3ops.presign_put(..., expires_in=min(TTL, row.expires_at-now))
    return {row, url, expires_at: row.expires_at}  # cohérent
```

---

## C. P2 — Grande taille, reprise, performance

### C.1 G8 — Multipart upload (le plus gros chantier)

**Pré-requis** : exécuter `scripts/seaweedfs-compat-probe.py` contre 4.48 pour valider :
- `CreateMultipartUpload` / `UploadPart` / `CompleteMultipartUpload` / `AbortMultipartUpload` / `ListParts`
- présignature d'URL par partie (headers autorisés)
- taille min des parties (AWS = 5 MiB sauf la dernière), nombre max (10 000)
- ETag de partie = MD5 (pas SHA-256) ; ETag composite ≠ hash fichier
- SSE héritée côté serveur (pas de header par partie)
- Range GET

**Algorithme côté serveur (nouveau module `api/multipart.py`)** :

1. **Session multipart liée à l'intent** :
   ```
   class MultipartSession:
       upload_id: str          # fourni par SeaweedFS
       object_id: str          # FK catalogue
       part_size: int          # choisi serveur (ex. 8 MiB)
       expected_size: int
       parts: dict[int, PartRecord]  # part_number -> {etag, size, uploaded_at}
       status: "open" | "completing" | "completed" | "aborted"
       expires_at: datetime
   ```
   Persistée dans une nouvelle table `multipart_sessions` + `multipart_parts`.

2. **Création** : `POST /objects/{oid}/multipart` (ré-auth, scope write) → appelle `CreateMultipartUpload` (bucket/key, SSE AES256, ContentType) → stocke `upload_id` → retourne `part_size`, `num_parts = ceil(expected_size / part_size)`.

3. **Présignature par partie** : `GET /objects/{oid}/multipart/{part_number}/url` → `presign_upload_part(bucket, key, upload_id, part_number, expires_in=TTL)` → URL + headers. Rate-limited et borné (`max 3 refresh`).

4. **Enregistrement de partie** : après PUT réussi, le client appelle `POST .../parts` avec `{part_number, etag, size}` ; le serveur vérifie `size <= part_size` (sauf dernière), `etag` non vide, et persiste. Pas de confiance dans l'ETag pour le hash final.

5. **Complete** : `POST .../complete` → serveur reconstruit la liste des parties (toutes présentes, dans l'ordre, tailles cohérentes avec `expected_size`) → appelle `CompleteMultipartUpload` → puis **réutilise le commit existant** : HEAD + stream_sha256 sur l'objet complet → `mark_available`. Si le hash ne matche pas → Abort + `failed`.

6. **Abort** : `DELETE .../multipart` → `AbortMultipartUpload` + purge des parties + `status=aborted`. Idempotent.

7. **Nettoyage** : balayage des sessions `open` expirées → abort automatique (réutilise le scheduler de A.2).

8. **Reprise** : au chargement de la page, `GET /objects/{oid}/multipart` retourne les parties déjà uploadées ; le client reprend aux parties manquantes (pas de re-upload des parties OK). Idempotence par `part_number`.

**Frontend** (`web/src/lib/transfer.ts`) :
- Nouvelle phase `uploading-parts` avec progression par partie.
- Concurrence bornée (ex. 4 parties en parallèle), retry par partie (pas par fichier), refresh d'URL par partie.
- Adaptive parallelism déjà présent (réutiliser `startStaggerMs`).
- Journal (`uploadJournal.ts`) persiste `{object_id, upload_id, completed_parts}` pour survivre au reload (métadonnées seulement, pas les octets).

### C.2 Range GET / téléchargement reprenable

**Algorithme** : le download-intent retourne déjà une presigned GET ; pour le Range, le navigateur peut envoyer `Range: bytes=start-end` directement à l'URL présignée (S3 supporte Range sur GET). Côté AURA :
- Exposer `download-intent` avec un flag `range_supported: true` (documenté) + `accept_ranges: bytes`.
- Pour les gros fichiers, proposer un téléchargement par chunks côté client (fetch + Range + écriture via File System Access API ou concaténation en mémoire) avec reprise sur erreur réseau.
- Vérifier l'intégrité du fichier téléchargé via le `checksum_sha256` stocké (hash côté client, Web Crypto `crypto.subtle.digest`).
- Gate : vérifier que SeaweedFS 4.48 honore Range sur URL présignée (probe).

### C.3 Compression streaming (zstd) — optionnel

Conforme à `SECURE-BULK-TRANSFERS.md` §5 : compression uniquement si bénéfique, jamais transparente. Algorithme :
- À l'upload-intent, le client peut envoyer `Content-Encoding: zstd` + `X-Aura-Original-Size` ; le serveur stocke les deux dans les métadonnées.
- Commit re-hash l'objet tel quel (compressé) ; `checksum_sha256` porte sur les octets stockés.
- Download-intent renvoie `Content-Encoding` pour que le navigateur décompresse, ou `?encoding=identity` pour récupérer les octets bruts.
- Refuser la compression pour les types déjà compressés (PDF, JPEG, MP4, ZIP) via une liste noire + détection par magic bytes (les 4 premiers octets).

### C.4 Benchmarks (G11)

**Harness à développer** (`tests/transfer-bench.py` + `tests/transfer-bench.sh`) :
- Scénarios : 1 MiB, 10 MiB, 100 MiB, 1 GiB, 5 GiB ; connexions 1/4/8 ; part sizes 4/8/16 MiB (multipart).
- Métriques : throughput (MiB/s), latence commit (p50/p95/p99), taux d'échec, mémoire API (peak RSS), temps de hash.
- Sortie : JSON + tableau Markdown, stocké dans `docs/verification-log-*.md`.
- Comparaison à un baseline committé (`docs/benchmarks/baseline.json`) pour détecter les régressions.

---

## D. P3 — Observabilité et hygiène

### D.1 G10 — Déduplication `SSE_ALGORITHM`/`SSE_HEADER` dans `s3.py`

Définir une seule fois dans un bloc `constants` en tête de module.

### D.2 G9 — Retry/idempotence côté serveur

- Ajouter un middleware FastAPI qui, pour les routes idempotentes (commit, abort), rejoue la réponse mise en cache si le client renvoie la même `Idempotency-Key` dans les 5 min (cache en mémoire ou Redis). Évite les doubles exécutions lors d'un retry client.
- Backoff exponentiel avec jitter côté serveur pour les appels SeaweedFS (botocore adaptive retry déjà partiel).

### D.3 Quotas et rate limiting

- Token bucket par espace (octets/jour, fichiers/jour) dans `api/ratelimit.py`.
- Rejeter avec 429 + `Retry-After` avant la création d'intent.

### D.4 Quarantaine / AV

- Hook `AURA_AV_SCAN_CMD` appelé entre `pending` et `available` ; statut intermédiaire `scanning` ; si infecté → `quarantined` (téléchargement bloqué, admin peut purger).

---

## E. Ordre d'implémentation recommandé (sprints)

| Sprint | Items | Effort | Gate |
|---|---|---|---|
| S1 | G10, G3 (comparaison taille + timeouts) | 2-3 j | aucun |
| S2 | G4 (CAS), G6 (replay), G5 (nettoyage) | 1 sem | tests de concurrence |
| S3 | A.1 (integrity post-pub), A.2 (scheduler + reverse sweep) | 1-2 sem | probe SSE |
| S4 | C.1 (multipart) — gate #84 d'abord | 3-4 sem | probe 4.48 + benchmark |
| S5 | C.2 (Range), C.3 (zstd optionnel), C.4 (bench) | 2 sem | benchmark baseline |
| S6 | D.2-D.4 (retry serveur, quotas, AV) | 2 sem | décision produit |

## F. Ce qui ne doit PAS être fait

- Ne pas simuler la reprise (faking resume) — explicitement interdit par le contrat.
- Ne pas traiter l'ETag multipart comme SHA-256.
- Ne pas compresser automatiquement (préserver les octets originaux par défaut).
- Ne pas contacter le pilote sans approval gate VPS.
- Ne pas déployer sans HTTPS + SSE smoke + backup restore.

---

**Prochaine action concrète** : démarrer S1 (G10 + G3) en TDD, branche `feat/transfer-booster-s1`, sans approval gate (scope repo, tests offline).
