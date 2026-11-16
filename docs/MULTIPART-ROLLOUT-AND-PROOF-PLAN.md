# Multipart — Durcissement, activation progressive et plan de preuve (Lot 3 C)

> **Date :** 2026-11-16  
> **Portée :** finaliser le multipart (`AURA_MULTIPART_ENABLED`) et préparer son activation progressive en production pilote, en s’appuyant sur l’implémentation existante et les gates déjà mesurées.  
> **Sources :** `docs/MULTIPART-UPLOAD-PLAN.md`, `docs/verification-log-2026-10-25-multipart-compat-4.48.md`, `docs/verification-log-2026-10-25-multipart-proxy-4.48.md`, `api/config.py`, `api/s3.py`, `api/main.py`, `api/lifecycle.py`, `api/transfer.py`, `web/src/lib/transfer.ts`, `tests/test_multipart.py`, `tests/multipart-compat-4.48.sh`.

## 1. État actuel (constaté)

- **Implémentation complète derrière flag** (défaut `AURA_MULTIPART_ENABLED=0`) : intent multipart (seuil/taille), session S3 `Create/UploadPart/Complete/Abort/ListParts`, presign de parts borné, complétion serveur depuis `ListParts` puis vérification SHA-256 full-object, abort/reconcile/suppression qui libèrent la session, client web avec concurrence bornée, retry par part, reprise (parts déjà tenues), annulation.
  - Backend : `api/main.py` (`_multipart_intent_response`, `_pending_multipart`, `_uploaded_parts`, `_complete_multipart_session`, `_abort_multipart_session`, routes `/objects/{oid}/multipart*`, commit/abort/purge), `api/s3.py` (`plan_parts`, `MIN_PART_BYTES=5 MiB`, `MAX_PARTS=10000`, presign avec `ContentLength` signé), `api/lifecycle.py` (reconcile/expire/purge abort la session, best-effort), `api/transfer.py`.
  - Frontend : `web/src/lib/transfer.ts` (`runMultipart`, batch URLs, renouvellement, reprise).
- **Gate compat SeaweedFS 4.48 (items 1–6) couverte** sur stack jetable (direct + via Traefik) avec 47 passes / 0 échecs signalés dans les logs ; deux **UNKNOWN** documentés (voir §4).
- **Garde-fous déjà en place** : `plan_parts` impose ≥5 MiB et ≤10 000 parts ; `presigned_upload_part` signe `ContentLength` (borne d’intégrité, à ne jamais retirer) ; liste de complétion construite depuis `ListParts` filtrée au plan (évite le cas `NoSuchUpload` sur part hors plage observé) ; `AbortMultipartUpload` idempotent/best-effort côté S3 ; reconcile n’expire pas avant la fenêtre de grâce/sécurité.
- **Pilotage taille/proxy** : `readTimeout` Traefik dimensionné (7200s sur le pilote selon plan) ; la taille de part doit rester très inférieure au budget `readTimeout` au pire débit client supporté.

## 2. Durcissement (garde-fous à respecter / vérifier)

### 2.1 Invariants à ne pas régresser (bloquants)
1. **Presign de part = longueur signée** : `presigned_upload_part` doit continuer à signer `ContentLength` (`api/s3.py`). Sans cela, le gateway n’enforce pas la taille (validé en gate item 2) — c’est la seule borne d’intégrité par part.
2. **Complétion = liste issue de `ListParts`** : `_complete_multipart_session` doit assembler les parts depuis le backend, filtrées `1..count` avec taille exacte du plan (`api/main.py`). Ne jamais accepter une liste fournie par le client ; ne jamais référencer une part hors plage (risque `NoSuchUpload`).
3. **Intégrité finale inchangée** : après `CompleteMultipartUpload`, vérification SHA-256 full-object (stream, bornée mémoire) avant `available` ; l’ETag multipart n’est jamais traité comme SHA-256.

### 2.2 Garde-fous opérationnels
- **Bornes de plan** : conserver `MIN_PART_BYTES`/`MAX_PARTS` ; `AURA_MULTIPART_PART_BYTES` ≥ 5 MiB ; `AURA_MULTIPART_MAX_OBJECT_BYTES` ≥ seuil et cohérent avec capacité/quota.
- **Dimensionnement part vs réseau** : garantir `part_size_bytes / débit_client_min_supporté` ≪ `readTimeout` proxy (marge confortable, pas la limite absolue). Règle pratique : viser < ~20–30% du budget au débit cible ; le défaut 16 MiB est très sûr à bas débit (cf. log proxy).
- **Session/TTL** : `AURA_MULTIPART_SESSION_TTL` (défaut 7 j) et fenêtre de grâce de reconcile (`intent_grace_s` / `multipart_expired_before`) doivent éviter d’interrompre un upload lent légitime tout en nettoyant les abandons.
- **Abort/expiration** : `abort_intent` et `purge/reconcile_pending` doivent continuer à appeler `AbortMultipartUpload` (best-effort) puis nettoyer l’état ; une erreur transitoire ne doit pas perdre la référence catalogue (retry par sweep). Vérifier que les bytes partiels ne fuient pas après le TTL (cf. UNKNOWN #1).
- **Idempotence** : commit répété sûr (session déjà complétée → chemin de vérification objet) ; reprise = n’envoyer que les parts manquantes selon `ListParts`.
- **Exposition/autorisation** : routes multipart limitées au scope/propriétaire de l’objet, identifiants canoniques, pas de fuite d’`upload_id`/clés hors besoin serveur, URLs de part courtes et par part.

### 2.3 Observabilité & sûreté au rollout
- Auditer/mesurer : taux d’échec commit multipart, parts en échec/renouvelées, sessions expirées/abortées, durée, et erreurs stockage (`NoSuchUpload`, timeouts proxy).
- Alertes sur croissance anormale d’usage stockage/capacité pendant la fenêtre d’activation (détection indirecte de fuite de parts).
- Garder un **kill-switch** : `AURA_MULTIPART_ENABLED=0` ramène au chemin single-PUT (dans les limites `AURA_MAX_OBJECT_BYTES`) sans migration de données.

## 3. Activation progressive (procédure recommandée)

1. **Pré-requis** : Lot 0/1 suffisamment stabilisés (déploiement maîtrisé, capacité/quotas, supervision de base). Proxy `readTimeout` confirmé ≥ budget parts au débit cible.
2. **Environnement jetable / staging** : activer le flag, exécuter la campagne de preuve (§4) et les scénarios §5 ; consigner un log daté dans `docs/`.
3. **Pilote contrôlé** :
   - Activer avec **seuil élevé** (ex. conserver `AURA_MULTIPART_THRESHOLD_BYTES` élevé, ex. 100 MiB ou plus) pour ne capter que les gros objets.
   - Limiter l’exposition (groupe d’utilisateurs/espace de test) si possible ; surveiller erreurs, expirations, capacité.
4. **Élargissement** : baisser progressivement le seuil (ex. 64–100 MiB selon mesures) si les taux d’échec/retry et la capacité restent nominaux ; conserver la possibilité de remonter le seuil ou couper le flag.
5. **Généralisation** : flag à l’échelle souhaitée uniquement après preuves §4 closes ou explicitement acceptées avec mitigations.
6. **Rollback** : remettre `AURA_MULTIPART_ENABLED=0` (les sessions en cours doivent être laissées expirer/s’annuler proprement ; ne pas purger de données catalogue). Les nouveaux uploads retombent en single-PUT.

**Paramètres de référence (code, ajustables par env)** : `AURA_MULTIPART_ENABLED`, `AURA_MULTIPART_THRESHOLD_BYTES` (100 MiB), `AURA_MULTIPART_PART_BYTES` (16 MiB, ≥5 MiB), `AURA_MULTIPART_SESSION_TTL` (7 j), `AURA_MULTIPART_MAX_OBJECT_BYTES` (1 TiB). Ne pas modifier sans réévaluer §2.2.

## 4. Plan de preuve des 2 UNKNOWNs (SeaweedFS 4.48)

> Exécuter **uniquement** sur stack **jetable** (bucket isolé, image `chrislusf/seaweedfs:4.48` épinglée), jamais sur le pilote de données réelles. Archiver chaque campagne dans un `docs/verification-log-YYYY-MM-DD-multipart-*.md` (commandes, versions, résultats, limites).

### UNKNOWN #1 — Reclaim disque après abort
**Question** : les bytes des parts d’une session abortée sont-ils effectivement libérés sur le volume (et quand) ?

**Méthode proposée (preuve pratique)**
1. Mesurer l’usage volume avant (stats fs/volume du service volume SeaweedFS, et si dispo métriques filer/volume) sur un volume dédié au test.
2. Uploader un objet multipart de taille connue (plusieurs GiB si possible) en complétant suffisamment de parts pour matérialiser le volume, **sans compléter** puis appeler `AbortMultipartUpload` (ou passer par l’API abort) ; alternativement laisser expirer au-delà du TTL pour tester le chemin reconcile.
3. Confirmer côté S3 API : `ListParts`/`ListMultipartUploads` ne listent plus la session (garantie déjà vérifiée).
4. Observer le retour de l’usage volume : immédiatement, après compaction/vacuum/maintenance si applicable à SeaweedFS 4.48, et après un délai (ex. fenêtre documentée ou plusieurs heures). Noter l’écart résiduel éventuel.
5. Répéter (abort explicite vs expiration/reconcile) pour comparer.

**Critère d’acceptation** : baisse mesurable et durable ≈ taille des parts envoyées (à tolérance métadonnées près) dans une fenêtre opérable, ou documentation précise du mécanisme/délai requis. **Mitigation si non prouvé** : plafonner la taille/nombre de sessions simultanées, surveiller capacité, alerter, et ne pas activer largement sans marge disque.

**Limite connue** : les compteurs globaux de volume ne peuvent pas attribuer une suppression à un upload précis — isoler le test sur un volume/bucket dédié et contrôler les écritures concurrentes.

### UNKNOWN #2 — Complétion réelle ~10 000 parts
**Question** : un `CompleteMultipartUpload` réel avec ~10 000 parts aboutit-il correctement de bout en bout (assemblage, HEAD/taille, lecture/Range, SHA-256) ?

**Méthode proposée**
1. Calculer une taille/part réalisable : avec `MIN_PART_BYTES=5 MiB`, 10 000 parts ≈ **48.8 GiB** (dernier part potentiellement plus petit selon plan) — prévoir temps réseau/disque et capacité suffisante sur stack jetable.
2. Générer et uploader 10 000 parts (contenu déterministe ou motif reproductible) en respectant la taille exacte signée par part ; vérifier `ListParts` complet.
3. Appeler `CompleteMultipartUpload` avec la liste ordonnée complète ; mesurer durée et succès.
4. Vérifier : `HeadObject` taille/ETag attendus, `GetObject` intégral et **Range** (dont à cheval sur frontière de part), et SHA-256 du flux égal au SHA-256 calculé côté client.
5. (Optionnel mais recommandé) Refaire via le chemin API AURA (intent→parts→commit→available) pour valider l’assemblage serveur + vérif, pas seulement le gateway brut.

**Critère d’acceptation** : complétion réussie, objet lisible et intègre (SHA-256 conforme), sans erreur de gateway aux bornes (on sait déjà que 10001 est rejeté). **Mitigation si non exercé** : plafonner le nombre de parts effectif en production via politique de taille de part/objet (ex. maintenir un maximum opérationnel << 10 000) jusqu’à preuve.

## 5. Scénarios de validation (hors CI lourde, avant activation élargie)

- **Interruption/reprise** : coupure réseau en cours de parts → reprise n’envoie que les parts manquantes ; commit final OK.
- **Part expirée/renouvelée** : URL de part expirée → re-presign et succès.
- **Commit avec part manquante** : 409 puis résolution après upload manquant ; retry de commit idempotent.
- **Abort explicite** et **expiration/reconcile** : session libérée côté S3, état catalogue cohérent, pas de blocage d’objets.
- **Gros objet proche des bornes** (selon capacité test) : hash/vérification dans les délais, pas de dépassement mémoire API.
- **Dégradations** : `NoSuchUpload` au complete/abort géré sans 500 non maîtrisé ; stockage indisponible → échec explicite/retry selon chemin.

Compléter avec : `tests/test_multipart.py` (offline), e2e multipart web, et les scripts/logs de compat existants.

## 6. Décision d’activation (résumé)

| Condition | Statut / action |
|---|---|
| Items 1–6 compat 4.48 | Mesurés (logs 2026-10-25/26) — invariants §2.1 verrouillés |
| UNKNOWN #1 reclaim | Campagne §4.1 à exécuter & consigner, ou activer avec mitigations capacité |
| UNKNOWN #2 10k parts | Campagne §4.2 à exécuter & consigner, ou plafonner parts/objets en prod |
| Proxy `readTimeout` vs part size | Vérifié au dimensionnement (§2.2) avant activation |
| Observabilité & rollback | Kill-switch flag + seuil + alertes en place |

**Recommandation** : activation **progressive** (seuil haut, périmètre restreint) après staging concluant ; n’élargir qu’avec métriques stables et, idéalement, preuves §4 closes.
