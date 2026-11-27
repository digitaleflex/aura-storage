# AURA verification log — 2026-11-27 (preuves multipart SeaweedFS 4.48)

> Instance de [verification-log-template.md](verification-log-template.md). Aucun secret, credential S3, KEK SSE-S3, nom de fichier client ou contenu privé : toutes les stacks sont jetables, avec credentials générés puis détruits.

## Métadonnées

- Date (UTC) : 2026-11-27
- Opérateur : session automatisée (workspace `aura-storage`)
- Dépôt : `aura-storage`, HEAD local `0db6a2a`
- Image : `chrislusf/seaweedfs:4.48` (épinglée), Docker 29.9.0
- Objectif : lever les deux UNKNOWN du plan de preuve multipart (`docs/MULTIPART-ROLLOUT-AND-PROOF-PLAN.md` §4) : #316 réclamation disque après abort, #317 complétion réelle de ~10 000 parties.
- Complément : `docs/verification-log-2026-11-16-multipart-proofs-4.48.md` (nettoyage API déjà vérifié, mesures alors non attribuables).

## #316 — Reclaim disque après abort (preuve attribuable)

- **Campagne** : `reclaim3-proof-4.48.sh`, run `20261127T074213Z-355362`, log `/tmp/opencode/reclaim3-proof-4.48-20261127T074213Z-355362.log`.
- **Stack** : `recl3-proof-4-48-*` (master/volume/filer), bucket jetable `reclaim3-a7962b508fea`, données sous `/tmp/opencode/reclaim3-proof-4-48-*`, teardown confirmé.
- **Charge** : 200 parties × 5 MiB = **1 048 576 000 bytes**, contenu **unique** par partie (`shake_256`) afin d'exclure la déduplication comme explication de la réclamation.

### Mesures (octets du bind mount de volume, `du -sb`)

| Moment | Octets volume (hôte) | Volume island |
|---|---:|---|
| Avant création de l'upload | 36 | aucune |
| Après upload des 200 parties, avant abort | 1 048 602 058 | 2 volumes en écriture |
| Juste après abort | 1 048 602 058 | identique |
| +10 s après abort | 1 048 621 258 | identique |
| 10 s après `lock → volume.vacuum -garbageThreshold=0.0001 → unlock` | **458** | 2 volumes |
| +40 s après vacuum | **458** | stable |

- `vacuum_rc=0` ; la séquence `weed shell` a été envoyée avec `lock` avant `volume.vacuum` et `unlock` après, ce qui corrige l'échec `need to run "lock" first` de la campagne du 2026-11-16.
- API après abort : `ListMultipartUploads=[]`, `ListParts=NoSuchUpload`.
- Attribution : la remontée à ~1,049 Go après upload puis la retombée à 458 octets **uniquement après vacuum** établit que les bytes sont bien libérés par la compaction, sans déduplication.
- **Mécanisme et délai** : l'abort retire la session côté API immédiatement, mais ne libère pas les octets sur le volume tout de suite ; le reclaim disque est observé dans les **10 s suivant un vacuum explicite** (`garbageThreshold=0.0001`). En l'absence de vacuum automatique configurable dans cette version, la mitigation opérationnelle reste : plafond de sessions multipart, surveillance capacité et marge de disque libre, puis vacuum planifié hors charge.

### Verdict #316

- **UNKNOWN #1 levé** : réclamation disque attribuable confirmée sur 1 GiB de données uniques, avec mécanisme (vacuum) et fenêtre de délai documentés.
- Le plafond opérationnel de sessions et la surveillance capacité restent recommandés : la libération n'est pas instantanée à l'abort.

## #317 — Complétion réelle ~10 000 parties

- **Campagne** : `tenk3-proof-4.48.sh`, run `20261127T075901Z-371461`, log `/tmp/opencode/10kparts-proof-4.48-20261127T075901Z-371461.log`.
- **Stack** : `tenk3-proof-4-48-*` (master, filer S3, 2 volumes `-max=60`), bucket jetable `tenk-b278738282ce`, données sous `/home/aura-admin/aura-proofs/tenk3-proof-4-48-20261127T075901Z-371461`, teardown confirmé.
- **Assainissement** : collection `.system` pré-créée pour éviter la starvation des volumes système des tentatives du 2026-11-16 ; topology `Max=120`, `Free=113`, 7 volumes writeables.
- **Charge** : 10 000 parties × 5 MiB, dernière partie 3 B, soit **52 423 557 123 octets (~48,8 GiB)** ; contenu **unique** par partie (`shake_256`) afin d'exclure la déduplication.

### Résultats

| Étape | Observation |
|---|---|
| Création de session | `UPLOAD_ID_PRESENT True` |
| Upload des 10 000 parties | progression soutenue, aucune starvation ; `UPLOAD_DONE` à **1 275,03 s** (~21 min) |
| Complétion | `COMPLETE_ETAG "ae2ed9815b60997be78a1a6522d7d8de-10000"` |
| `HEAD` | taille `52 423 557 123`, ETag identique à la complétion |
| `Range` | `bytes=0-99` → HTTP 206, 100 octets ; `bytes=5242878-5242898` (frontière de part) → HTTP 206, 21 octets |
| SHA-256 | calculé client : `850dc743ea665379727da35b8575d9028dd374f40b4fb60d98956738714810e2` ; relu en streaming de l'objet complet : identique ; `SHA_MATCH True` |
| Verdict | `RESULT PASS` |

### Verdict #317

- **UNKNOWN #2 levé** : `CompleteMultipartUpload` réel à 10 000 parties aboutit sur SeaweedFS 4.48, avec lecture intégrale et Range conformes. L'échec des campagnes précédentes était bien une condition de setup (volumes système saturés), non une limite de SeaweedFS.
- **Décision plafond** : le maximum S3 strict reste `MAX_PARTS=10 000`, mais le plafond opérationnel de **5 000 parties** est **conservé** (`MAX_OPERATIONAL_PARTS`, `api/s3.py`) : `plan_parts` élargit automatiquement la taille de part pour rester sous ce seuil, avec un plafond matériel de 5 GiB/part et un objet plafonné à ~24,4 TiB. La preuve démontre la faisabilité, pas un coût acceptable en production (21 min et 48,8 GiB pour un seul objet).
- Aucun secret, credential S3, KEK SSE-S3, nom de fichier client ou contenu privé ; stack et répertoires de preuve détruits en fin de campagne.
