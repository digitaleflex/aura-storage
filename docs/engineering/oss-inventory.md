# Inventaire des projets open source réutilisables (AURA)

**Date :** 2026-10-21 · **Branche :** `docs/oss-inventory` · **Statut :** inventaire de veille, pas une preuve d'intégration.

Toutes les métriques ci-dessous (étoiles, licence, dernière activité, archivage) ont été
relevées le 2026-10-21 via l'API GitHub. Les étoiles ne mesurent pas la qualité : elles
indiquent seulement l'ampleur de la relecture communautaire. Une date de dernière activité
ancienne ou un dépôt archivé est un signal à examiner avant de bâtir dessus.

**Règle de décision (ADR-006) :** aucune licence AGPL dans l'arbre. Les composants AGPL
tournent en service séparé, non modifié. Les composants GPL (ClamAV) restent des process
isolés, jamais liés dans `api/`. Les composants LGPL (psycopg) restent des dépendances
dynamiques non vendoriées.

**Règle d'or :** si la brique ne connaît pas le catalogue AURA, on la réutilise. Si elle doit
connaître le catalogue, on l'écrit nous-mêmes.

---

## 1. Ce qu'on clone en priorité (P0)

| Projet | Licence | Activité | Ce qu'on prend | Mode | Pourquoi maintenant |
|---|---|---|---|---|---|
| [ceph/s3-tests](https://github.com/ceph/s3-tests) | MIT | **archivé** 2026-10-12 | Sous-ensemble multipart / Range / presign / SSE | tests hors ligne | **Ferme le gate #84** sans écrire de harnais maison. Archiver = figé, pas cassé : on épingle un commit. |
| [tus/tusd](https://github.com/tus/tusd) | MIT | actif 2026-10-14 | Sémantique de reprise, hooks `pre-create`/`post-finish`, backend S3 | service séparé (si interop client tiers) | Référence du protocole resumable ; ne pas réécrire la reprise si on veut l'interopérabilité. |
| [tus/tus-js-client](https://github.com/tus/tus-js-client) | MIT | actif 2026-10-21 | Machine de reprise côté navigateur | référence de conception | Comparer avec `web/src/lib/transfer.ts` avant d'ajouter des états. |
| [restic/restic](https://github.com/restic/restic) | BSD-2-Clause | actif 2026-10-18 | Sauvegarde chiffrée, dédup CDC, snapshots S3 | binaire séparé | Remplace l'idée d'implémenter FastCDC et le backup maison. |
| [rclone/rclone](https://github.com/rclone/rclone) | MIT | actif 2026-10-20 | Copie hors site, sync différentiel, backend S3 | binaire séparé | Copie de survie et restauration ; ne pas coder de sync. |
| [Cisco-Talos/clamav](https://github.com/Cisco-Talos/clamav) | GPL-2.0 | actif 2026-08-27 | `clamd` + `clamdscan --fdpass` | sidecar + socket | Donne un contenu réel à `AURA_AV_SCAN_CMD`, qui est aujourd'hui un hook vide. |
| [authelia/authelia](https://github.com/authelia/authelia) | Apache-2.0 | actif 2026-10-21 | Forward-auth Traefik, TOTP/WebAuthn | conteneur séparé | Protège `/admin` et `/docs` mieux qu'un filtre IP. |
| [apache/casbin](https://github.com/apache/casbin) | Apache-2.0 | actif 2026-10-21 | Modèle RBAC avec domaines (tenant/espace) | lib Python (`pycasbin`) | Formalise les règles aujourd'hui dispersées dans `api/authz.py`. |
| [schemathesis/schemathesis](https://github.com/schemathesis/schemathesis) | MIT | actif 2026-10-21 | Tests property-based depuis `docs/openapi.yaml` | outil CI | Trouve les 4xx/5xx non prévus sans écrire de cas à la main. |
| [google/magika](https://github.com/google/magika) | Apache-2.0 | actif 2026-10-21 | Détection de type par contenu (magic bytes) | lib Python | Remplace la liste noire maison de `api/main.py:790` par une détection fiable. |
| [trallnag/prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator) | ISC | actif 2026-09-18 | Métriques HTTP FastAPI | lib Python | Observabilité sans instrumentation maison. |

---

## 2. Ce qu'on lit et adapte (P1)

| Projet | Licence | Activité | Ce qu'on en tire | Pourquoi pas en dépendance |
|---|---|---|---|---|
| [opencloud-eu/opencloud](https://github.com/opencloud-eu/opencloud) | Apache-2.0 | actif 2026-10-21 | Modèle partages/versions/quotas en Go, API HTTP | Stack Go complète, disproportionnée pour un VPS ; on lit, on ne greffe pas. |
| [scality/cloudserver](https://github.com/scality/cloudserver) | Apache-2.0 | actif 2026-10-21 | Modèle métadonnées S3 (bucket/objet/ACL) | Serveur S3 complet concurrent de SeaweedFS. |
| [seaweedfs/seaweedfs](https://github.com/seaweedfs/seaweedfs) | Apache-2.0 | actif 2026-10-21 | `s3api` : multipart, SSE, Range | Déjà en production chez nous : lire le code pour les gates. |
| [kopia/kopia](https://github.com/kopia/kopia) | Apache-2.0 | actif 2026-10-20 | Politiques de rétention, dédup, chiffrement | Doublon fonctionnel de restic. |
| [openfga/openfga](https://github.com/openfga/openfga) | Apache-2.0 | actif 2026-10-20 | Modèle ReBAC (Zanzibar) pour partages imbriqués | Service supplémentaire ; Casbin suffit tant que les partages restent simples. |
| [transloadit/uppy](https://github.com/transloadit/uppy) | MIT | actif 2026-10-21 | UX d'upload, états, accessibilité | React lourd ; on garde notre machine à états « never fake success ». |
| [pqina/filepond](https://github.com/pqina/filepond) | MIT | actif 2026-10-02 | Upload chunké côté navigateur | Même raison. |
| [grafana/loki](https://github.com/grafana/loki) | AGPL-3.0 | actif 2026-10-21 | Logs structurés, rétention | Service séparé uniquement. |
| [grafana/grafana](https://github.com/grafana/grafana) | AGPL-3.0 | actif 2026-10-21 | Tableaux de bord | Service séparé uniquement. |
| [prometheus/prometheus](https://github.com/prometheus/prometheus) | Apache-2.0 | actif 2026-10-21 | Collecte métriques | Service séparé. |
| [pgbackrest/pgbackrest](https://github.com/pgbackrest/pgbackrest) | MIT (fichier `LICENSE` mixte) | actif 2026-10-20 | Backup PostgreSQL vers S3, PITR | Binaire séparé ; complète restic pour la base. |
| [wal-g/wal-g](https://github.com/wal-g/wal-g) | Apache-2.0 | actif 2026-10-21 | WAL shipping PostgreSQL vers S3 | Alternative à pgBackRest. |
| [gitleaks/gitleaks](https://github.com/gitleaks/gitleaks) | MIT | actif 2026-09-30 | Détection de secrets dans l'historique Git | Outil CI. |
| [aquasecurity/trivy](https://github.com/aquasecurity/trivy) | Apache-2.0 | actif 2026-10-21 | Scan images/CVE | Outil CI. |
| [pypa/pip-audit](https://github.com/pypa/pip-audit) | Apache-2.0 | actif 2026-10-19 | CVE dépendances Python | Outil CI. |
| [semgrep/semgrep](https://github.com/semgrep/semgrep) | LGPL-2.1 | actif 2026-10-21 | Analyse statique Python/TS | Outil CI ; ne pas vendorer. |
| [agronholm/apscheduler](https://github.com/agronholm/apscheduler) | MIT | actif 2026-10-12 | Ordonnancement des réconciliations | Déjà couvert par un timer systemd ; utile seulement si on veut du in-process. |

---

## 3. Ce qu'on garde pour plus tard (P2)

| Projet | Licence | Activité | Cas d'usage futur |
|---|---|---|---|
| [deuxfleurs-org/garage](https://github.com/deuxfleurs-org/garage) | AGPL-3.0 | actif 2026-10-16 | Data plane multi-nœuds, géo-distribué, faible empreinte. Remplacerait SeaweedFS au 2ᵉ VPS. |
| [drakkan/sftpgo](https://github.com/drakkan/sftpgo) | AGPL-3.0 | actif 2026-10-03 | Accès SFTP/WebDAV multi-tenant, quotas, permissions. |
| [pydio/cells](https://github.com/pydio/cells) | AGPL-3.0 | actif 2026-10-21 | Référence partages/workspaces (trop lourd à héberger). |
| [nextcloud/server](https://github.com/nextcloud/server) | AGPL-3.0 | actif 2026-10-21 | Référence chunking/versions/AV (PHP, non greffable). |
| [haiwen/seafile](https://github.com/haiwen/seafile) | AGPL-3.0 + composants propriétaires | actif 2026-10-16 | Référence CDC/dédup à l'échelle d'une bibliothèque. |
| [ory/kratos](https://github.com/ory/kratos) | Apache-2.0 | actif 2026-07-29 | Identité OIDC si le besoin multi-utilisateur dépasse Authelia. |
| [goauthentik/authentik](https://github.com/goauthentik/authentik) | MIT + composants entreprise | actif 2026-10-21 | Alternative à Authelia si SSO complet nécessaire. |
| [VirusTotal/yara](https://github.com/VirusTotal/yara) | BSD-3-Clause | actif 2026-10-21 | Règles de détection personnalisées, après ClamAV. |
| [OpenAPITools/openapi-generator](https://github.com/OpenAPITools/openapi-generator) | Apache-2.0 | actif 2026-10-21 | Génération de clients depuis `docs/openapi.yaml`. |

---

## 4. Ce qu'on ne clone pas

| Projet | Licence | Activité | Raison |
|---|---|---|---|
| [minio/minio](https://github.com/minio/minio) | AGPL-3.0 | **archivé** 2026-04-24 | Le dépôt communautaire est archivé : ne pas démarrer un chantier dessus. De plus AGPL, incompatible avec l'arbre. |
| [minio/mc](https://github.com/minio/mc) | AGPL-3.0 | **archivé** 2025-11-20 | Même raison. |
| [minio/mint](https://github.com/minio/mint) | Apache-2.0 | **archivé** 2026-01-08 | Suite de conformité abandonnée ; préférer `ceph/s3-tests` épinglé. |
| [filebrowser/filebrowser](https://github.com/filebrowser/filebrowser) | Apache-2.0 | **archivé** 2026-07-31 | Trop simple, archivé. |
| [ceph/ceph](https://github.com/ceph/ceph) | LGPL-2.1/GPL | actif | Complexité d'exploitation hors de portée d'un mono-VPS. |
| [keycloak/keycloak](https://github.com/keycloak/keycloak) | Apache-2.0 | actif | Java, ~1 Go de RAM : disproportionné. |
| [zitadel/zitadel](https://github.com/zitadel/zitadel) | AGPL-3.0 | actif | AGPL + stack lourde. |
| [peak/s5cmd](https://github.com/peak/s5cmd) | MIT | 2025-06-13 | Utile en CLI, mais rclone couvre déjà le besoin et reste actif. |

---

## 5. Carte d'extraction (quoi lire, où ça atterrit)

Chemins indicatifs, à confirmer au moment du clone : les dépôts bougent.

| Source | Zone à lire | Ce qu'on en sort | Destination AURA |
|---|---|---|---|
| `ceph/s3-tests` | cas multipart, range, presign | Cas de test et attentes de comportement | `tests/` (harnais de conformité) |
| `tusd` | handlers, hooks, store S3 | Sémantique de reprise et d'idempotence | `docs/TRANSFER-ENGINE.md`, tests |
| `tus-js-client` | machine d'états | États de reprise navigateur | `web/src/lib/transfer.ts` |
| `rclone` | backend S3, mode `crypt` | Gestion des erreurs S3, modèle de chiffrement | `api/s3.py`, docs |
| `restic` | chunker, repository | Choix CDC et politique de rétention | `docs/BACKUP-RESTORE.md` |
| `clamav` | `clamd`, `clamdscan` | Invocation et timeouts | `AURA_AV_SCAN_CMD` |
| `authelia` | forward-auth Traefik | Labels et politique d'accès | `docker-compose.yml`, `app/` |
| `casbin` | modèles RBAC avec domaines | Matrice de permissions | `api/authz.py`, `docs/AUTHORIZATION-MATRIX.md` |
| `magika` | API Python | Détection de type | politique de types dans `api/main.py` |
| `opencloud` | partages, versions, quotas | Modèle de données | `docs/DATA-MODEL.md` |
| `seaweedfs` | `s3api` | Comportement réel du backend | gates #84, tests |

---

## 6. Procédure de clone

Les dépôts se clonent **hors du dépôt AURA**, dans un répertoire de travail jetable, en
superficiel. Le script `scripts/oss-clone.sh` a été **retiré du dépôt le 2026-10-26**
(c'est une pratique de recherche, pas une opération de service) ; les commandes
équivalentes :

```bash
mkdir -p /tmp/opencode/oss && cd /tmp/opencode/oss
git clone --depth 1 <url-du-depot>
```

`--depth 1` suffit pour lire le code, ignore les répertoires déjà présents, ne supprime
rien et ne fait aucun `pull` destructif.

---

## 7. Ce qu'aucun de ces projets ne fera à notre place

La frontière est stable et c'est elle qui protège le produit :

- vérification au commit (`HEAD` + taille + `AES256` + SHA-256 streaming) ;
- machine à états `pending → available/failed/expired/aborted` ;
- idempotence persistée en catalogue et CAS sur les transitions ;
- autorisation par scope et journal d'audit sur chaque transition ;
- réconciliation inverse stockage → catalogue.

Aucun projet listé ici ne connaît la notion d'objet `available` prouvé. C'est le cœur d'AURA,
et c'est ce qu'on continue d'écrire.

---

## 8. Prochaines actions

1. Cloner le sous-ensemble `s3-tests` dans `/tmp/opencode/oss` (voir §6) puis le brancher sur un bucket jetable (gate #84).
2. ClamAV en sidecar + test EICAR : un fichier infecté ne doit jamais atteindre `available`.
3. restic vers une destination S3 séparée + restauration réelle avec vérification de hash.
4. `schemathesis` contre `docs/openapi.yaml` en CI.
5. Mettre à jour ce document quand une brique est adoptée, rejetée ou remplacée.
