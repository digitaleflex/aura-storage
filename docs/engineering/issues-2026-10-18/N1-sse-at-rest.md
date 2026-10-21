## Contexte
Constat du 2026-10-18 (test local, SeaweedFS 4.48, même version que le pilote) : `WEED_S3_SSE_KEK` **active** SSE-S3 mais ne l'**applique** pas. SeaweedFS ne chiffre une écriture que si elle envoie `x-amz-server-side-encryption: AES256`. L'URL présignée d'upload d'AURA ne le demandait pas : les fichiers envoyés par l'application étaient stockés **en clair** (chaîne témoin retrouvée dans les fichiers `.dat`).

`tests/sse-s3-smoke-test.sh` passait quand même, parce qu'il envoie l'en-tête lui-même.

## État vérifié dans le code
- `api/s3.py:presigned_put` — pas de `ServerSideEncryption` (sur `main`).
- Aucun `put_bucket_encryption` dans le dépôt.

## Travail (branche `fix/sse-at-rest`)
- [x] L'URL présignée signe `ServerSideEncryption=AES256` ; un PUT sans l'en-tête est refusé (403).
- [x] L'intent renvoie l'en-tête dans `headers` (le front le transmet déjà).
- [x] Le commit refuse (422, statut `failed`) un objet non rapporté `AES256` (`AURA_REQUIRE_SSE=1`).
- [x] `python -m api.reencrypt` (dry-run / `--apply`) pour l'existant + étape `volume.vacuum`.
- [x] Tests : `tests/test_sse_at_rest.py` (8).

## Critères code
- [x] Suite verte ; vérification live locale (PUT sans en-tête 403, avec 200, commit d'un objet en clair 422, rechiffrement 6/6, texte témoin absent après vacuum).

## Critères pilote
- [ ] Sauvegarde faite (#9) avant toute opération.
- [ ] Déployé ; un upload via l'app renvoie `ServerSideEncryption=AES256` au `HEAD`.
- [ ] `api.reencrypt` : dry-run, `--apply`, puis dry-run à 0 ; `volume.vacuum` exécuté.
- [ ] `tests/sse-s3-smoke-test.sh` relancé, résultat consigné dans #8.

## Hors périmètre
Chiffrement côté client ; rotation de la KEK.
