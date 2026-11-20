# AURA verification log — 2026-11-16 (multipart proofs SeaweedFS 4.48: reclaim & 10k parts)

> Instance of [verification-log-template.md](verification-log-template.md). No credentials, private keys, SSE-S3 keys, full environment dumps, customer filenames or document contents. All S3 credentials/SSE KEKs used were generated for throwaway stacks and destroyed with them.

## Run metadata

- Date (UTC): 2026-11-16
- Operator: automated session (aura-admin workspace)
- Repository: `aura-storage`, HEAD at run start: `d66bfc2` (working tree had untracked `output/` only)
- Purpose: prepare/execute disposable-stack proof campaigns for multipart UNKNOWNs per `docs/MULTIPART-ROLLOUT-AND-PROOF-PLAN.md` §4 (UNKNOWN #1 disk reclaim after abort; UNKNOWN #2 real completion ~10,000 parts) and record evidence/limits.
- Image: `chrislusf/seaweedfs:4.48` (pinned). Docker: 29.9.0.

## Baseline — compat gate rerun (disposable)

- Command: `sg docker -c 'bash tests/multipart-compat-4.48.sh'`
- Harness: `tests/multipart-compat-4.48.sh` + `tests/multipart_compat_client.py` (isolated `compat-4-48-*` containers/network, data under `/tmp/opencode/compat-4-48-*`, teardown confirmed).
- Result: **`SUMMARY: failures=0 findings=0 unknowns=2 passes=47`**, exit code 0.
- Confirms (same as prior logs): core lifecycle, min part size enforcement at Complete, presigned part PUT, SSE-S3 inheritance, Range GET behavior, CORS, ETag/MD5 semantics, signed ContentLength enforcement, part boundary 10000 accepted / 10001 rejected.
- UNKNOWNs carried forward by harness:
  - **#1**: disk-level removal after abort not provable from volume stats (S3 API cleanup verified: ListParts/ListMultipartUploads gone; volume bytes unchanged immediately).
  - **#2**: 10,000-part completion path not exercised (only boundary/arithmetic verified).

## UNKNOWN #1 — Reclaim disque après abort (campagne)

- **Status:** IN PROGRESS / PENDING EXECUTION IN THIS SESSION
- **Method:** disposable isolated stack; measure volume usage; upload multipart parts (materialized bytes) without completing; abort via S3 API; confirm session gone; observe volume usage immediately and after compaction/vacuum attempt and/or delay.
- **Acceptance target:** measurable durable reclaim ≈ uploaded part bytes in operable window, or precise documented mechanism/delay; else mitigations.

### Evidence
(pending)

### Verdict
- S3 API cleanup: (pending)
- Disk/volume reclaim: (pending)

## UNKNOWN #2 — Complétion réelle ~10 000 parts (campagne)

- **Status:** IN PROGRESS / PENDING EXECUTION IN THIS SESSION
- **Method:** disposable isolated stack; 10,000 parts at minimum viable size/plan, deterministic content, upload all parts, CompleteMultipartUpload, verify HeadObject size/ETag, GetObject/Range integrity, and SHA-256 of stream vs expected.
- **Note:** ~48.8 GiB minimum at 5 MiB/part; requires sufficient time and disk on disposable volume.

### Evidence
(pending)

### Verdict
(pending)

## Limits / follow-ups
- (to be completed)

## UNKNOWN #1 — Reclaim disque après abort (campagne exécutée)

- **Date/heure (UTC):** 2026-11-16T18:42:31Z (run `20261116T184231Z-2597415`)
- **Commande:** `sg docker -c 'bash /tmp/opencode/reclaim-proof-4.48.sh'` (script ad hoc, jetable, dérivé du harness compat)
- **Stack:** isolée `reclaim-proof-4-48-*` (master/volume/filer, image `chrislusf/seaweedfs:4.48`, réseau/data sous `/tmp/opencode/reclaim-proof-4-48-20261116T184231Z-2597415`, credentials/KEK générés, teardown confirmé). Bucket jetable `reclaim-b3be063b2122`.
- **Scénario:** `CreateMultipartUpload` puis upload de **20 parts × 5 MiB = 104 857 600 bytes (100 MiB)** sans `Complete`, puis `AbortMultipartUpload`.
- **Mesures volume (`docker exec <volume> du/find /data`)** :
  - **Avant upload :** `files=1 bytes=96` (`vol_dir.uuid`)
  - **Après upload (avant abort, upload terminé côté client) :** non mesuré séparément ; mesure suivante prise immédiatement après abort.
  - **Immédiatement après abort :** `files=7 bytes=136478` (`reclaim-b3be063b2122_1.dat=95200`, `*_1.idx=832`, `*_1.vif=203`, `*_2.dat=39376`, `*_2.idx=448`, `*_2.vif=203`, `vol_dir.uuid=36`)
  - **Tentative vacuum (`weed shell -master=...` via stdin, `volume.vacuum -garbageThreshold=0.0001`) :** commande non interactive échouée (`vacuum_rc=1`, sortie `error: need to run "lock" first to continue` ; séquence lock/vacuum/unlock envoyée mais exécution non concluante).
  - **Après tentative vacuum + ~5s :** `files=7 bytes=638` (`*_1.dat=8`, `*_1.idx=0`, `*_2.dat=8`, `*_2.idx=0`, `.vif`/uuid inchangés)
  - **Après ~30s :** `files=7 bytes=638` (identique)

### Evidence (S3 API)
- `ListMultipartUploads` avant abort: upload présent.
- `AbortMultipartUpload`: accepté.
- `ListParts` après abort: `NoSuchUpload` (`The specified multipart upload does not exist...`).
- `ListMultipartUploads` après abort: `[]`.

### Verdict
- **Nettoyage API S3 (session/parts) : VÉRIFIÉ** (abort effectif, plus de listing parts/uploads).
- **Reclaim disque/volume : PARTIELLEMENT OBSERVÉ, NON CONCLUSIF comme preuve stricte d’attribution**
  - Les compteurs `du` montrent ~136 KB immédiatement après abort (très inférieur aux 100 MiB envoyés) puis ~638 B après quelques secondes malgré une tentative de vacuum non concluante — ce qui ne permet pas d’attribuer formellement la libération à l’abort/compaction et peut refléter le mode de stockage/commit des chunks/volumes SeaweedFS dans cette configuration.
  - Aucune réclamation “avant/après” clairement égale aux bytes de parts n’a été mesurée de façon attribuable ; la campagne ne prouve pas (ni n’infirme définitivement) une fuite durable, mais confirme l’absence de résidu exposé par l’API.
- **Statut UNKNOWN #1 :** reste **ouvert** (preuve disque attribuable non établie). Mitigations recommandées : plafond sessions/taille, surveillance capacité, activation progressive avec marge, et campagne complémentaire avec instrumentation volume plus fine (métriques SeaweedFS/volume, suivi sur fenêtre longue, vacuum correctement orchestré via `weed shell`).


## UNKNOWN #2 — Complétion réelle ~10 000 parts (tentatives, non concluantes)

### Tentative A
- **Date/heure (UTC) :** 2026-11-16T18:47:10Z (run `20261116T184710Z-2599902`, lancée en arrière-plan ; vérifiée vers ~18:53Z ; arrêt/nettoyage vers ~18:55Z)
- **Commande :** `nohup sg docker -c 'bash /tmp/opencode/10kparts-proof-4.48.sh'`
- **Stack :** `tenk-proof-4-48-*`, bucket `tenk-dc103f8ea379`, endpoint `http://127.0.0.1:32798`. Plan : 10 000 parts (5 MiB, dernière 3 B, ~48.8 GiB), `Complete` + `HEAD`/`Range` + SHA-256 stream.
- **Progression :** gateway prête (`http=403`) puis **aucune progression fonctionnelle loguée** (pas de `PLAN`/`UPLOAD_ID_PRESENT`/`UPLOADED`) ; client Python actif mais bloqué sur appel S3 initial.
- **Indices :** erreurs filer répétées `metadata log write failed ... No writable volumes and no free volumes left` (`.system/log`, `replication:000`) ; volumes de données collection présents (~33 Mo cumulés observés) ; endpoint répondant.
- **Résultat :** interrompue/nettoyée sans preuve de complétion.

### Tentative B (après smoke test réduit PASS)
- **Date/heure (UTC) :** 2026-11-16T19:42:22Z (run `20261116T194222Z-2615629`, vérifiée vers ~19:44Z ; arrêt/nettoyage après constat de blocage)
- **Commande :** `nohup sg docker -c 'bash /tmp/opencode/10kparts-proof-4.48.sh'` (log `/tmp/opencode/10kparts-proof-4.48-20261116T194222Z-2615629.log`)
- **Stack :** `tenk-proof-4-48-*`, bucket `tenk-adf2c1c46554`, endpoint `http://127.0.0.1:32800`. Même plan ~48.8 GiB.
- **Progression :** gateway prête puis **aucune progression fonctionnelle loguée** pendant >2 min ; client Python actif mais bloqué sur appel S3 initial.
- **Indices :** même symptôme côté filer — erreurs répétées `No writable volumes and no free volumes left` pour `.system/log` (`replication:000`) ; volumes de données collection créés ; endpoint répondant.
- **Résultat :** interrompue/nettoyée sans preuve de complétion.

- **Verdict UNKNOWN #2 :** **reste ouvert (non exercé)**. Les tentatives n’établissent pas une défaillance de `CompleteMultipartUpload` à ~10 000 parts ; elles révèlent une **condition d’environnement/stack récurrente** (starvation/indisponibilité d’écriture des volumes système de logs) empêchant la progression fiable du flux de preuve à grande échelle, malgré un smoke test réduit PASS sur stack saine.
- **Action recommandée :** fiabiliser la configuration de la stack de preuve (allocation/writability des volumes, y compris système/logs ; validation de progression soutenue) avant toute relance du run ~48.8 GiB ; consigner le résultat définitif (succès ou échec avéré de complétion/intégrité) une fois exécuté.

## État de clôture intermédiaire (2026-11-16)

- UNKNOWN #1 : **ouvert** — nettoyage API vérifié, reclaim disque attribuable non prouvé (campagne complémentaire avec vacuum correctement orchestré + mesures attribuables requise).
- UNKNOWN #2 : **ouvert** — complétion réelle ~10k parts non exercée (tentative bloquée côté setup/progression, non concluante). Boundary 10000/10001 et arithmetic restent vérifiés par le harness compat.
- Décision : conserver `AURA_MULTIPART_ENABLED=0` hors périmètre contrôlé ; activation seulement progressive avec mitigations (§ plan) tant que les preuves ne sont pas closes.


## Smoke test multipart réduit (stack saine, post-blocage)

- **Date/heure (UTC):** 2026-11-16T19:33:00Z (run `20261116T193300Z-2612594`, log `/tmp/opencode/multipart-smoke-4.48-20261116T193300Z-2612594.log`)
- **Commande :** `sg docker -c 'bash /tmp/opencode/multipart-smoke-4.48.sh'` (script ad hoc jetable)
- **Stack :** isolée `mp-smoke-4-48-*` (`chrislusf/seaweedfs:4.48`, master/volume/filer, credentials/KEK générés, teardown confirmé). Bucket `mpsmoke-8bc58313285a`.
- **Scénario :** multipart **20 parts** (19 × 5 MiB + dernière 1 KiB, total 99 615 744 bytes), contenu déterministe, upload → `CompleteMultipartUpload` → `HeadObject` → `Range` (préfixe + frontière de part) → vérification **SHA-256 stream**.
- **Résultat : PASS**
  - Upload/complete/progression OK (`UPLOADED 1/5/10/20`), `COMPLETE_ETAG "3fce599ddbfccc90df3efc4ebc82a097-20"`, `HEAD_SIZE == expected`, Range OK, `SHA_MATCH True`, durée totale ~5.33 s.
  - **Santé stack :** pas d’erreurs « No writable volumes / no free volumes left » observées dans la queue de logs filer (tail capturé au teardown) ; comportement nominal.
- **Conclusion :** l’environnement de preuve jetable (pattern compat harness) est fonctionnel pour un flux multipart complet à échelle réduite. Le blocage de la tentative ~10k parts précédente n’a pas été reproduit ; un run 10k parts (~48.8 GiB) reste à effectuer sur cette base saine si l’on souhaite clore UNKNOWN #2 (coût temps/disque à prévoir), après confirmation de progression soutenue.

