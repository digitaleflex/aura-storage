# Recherche avancée — algorithmes et outils open source pour booster le moteur de transfert AURA

**Date :** 2026-10-21 · **Sources** : web (AWS docs, GitHub, USENIX, rclone, s5cmd, FastCDC).

## 1. Synthèse des découvertes

### 1.1 Ce que font les grands (AWS/Azure/GCP)
- **Multipart upload** : standard de fait pour > 100 MiB. Chaque part est un PUT indépendant, parallélisable, reprenable. AWS recommande ≥ 5 MiB par part (sauf la dernière), max 10 000 parties, taille max 5 TiB par objet.
- **Transfer Acceleration** (AWS) : routage via CloudFront edge, gain ~61% sur les longues distances. Pas applicable à un single-VPS, mais la technique (edge caching + routage) est réutilisable.
- **Checksums par partie** : AWS supporte `x-amz-checksum-sha256` par part + composite checksum au Complete. C'est la norme 2026 pour l'intégrité fine.
- **Erasure coding** (Azure) : tolérance aux pannes sans réplication brute (Reed-Solomon), gain d'espace ~50%.
- **GCP Storage Transfer Service** : orchestration server-side, parallélisme massif, retry automatique.

### 1.2 Outils open source de référence
| Outil | Forces | Leçon pour AURA |
|---|---|---|
| **s5cmd** (Go) | 12-32x plus rapide que aws-cli ; parallélisme extrême ; sync intelligent (taille+timestamp+ETag) | Parallélisme massif + sync différentiel |
| **rclone** | Multi-cloud, crypt client-side (AES-CTR + Poly1305), resume, chunked uploads | E2E crypto + resume + backend abstraction |
| **rclone crypt** | Chiffrement streaming, noms de fichiers chiffrés, zero-knowledge | Modèle de référence pour l'E2E crypto |
| **FastCDC** | Content-Defined Chunking, Gear hash, normalized chunking, ~10x plus rapide que Rabin | Déduplication par bloc pour sauvegardes incrémentales |
| **MinIO** | Erasure coding, versioning, object lock, multipart, S3-compatible | Référence complète d'implémentation S3 |

### 1.3 Algorithmes avancés pertinents
- **FastCDC** (USENIX ATC'16) : chunking basé sur le contenu, Gear hash, normalized chunking. Permet la déduplication et la reprise fine (seuls les blocs modifiés sont renvoyés).
- **Rabin fingerprinting** : rolling hash pour le CDC, mais plus lent que FastCDC.
- **Erasure coding (Reed-Solomon)** : tolérance aux pannes avec moins d'espace que la réplication.
- **BLAKE3** : hachage parallélisable, plus rapide que SHA-256, mais SHA-256 reste le standard interop.
- **Content-Defined Chunking (CDC)** : découpage variable basé sur le contenu, utilisé par Dropbox, Restic, Borg.
- **Adaptive chunk sizing** : ajustement dynamique de la taille de chunk selon le débit mesuré (EMA).
- **Bloom filter / Count-Min Sketch** : détection rapide de doublons et rate limiting à grande échelle.
- **HyperLogLog** : comptage distinct d'objets par espace (observabilité).

## 2. Ce qui boosterait le plus AURA (priorité)

1. **Multipart + checksum par partie + resume par partie** (s5cmd/rclone) — débloque les > 5 GiB et la reprise fine.
2. **FastCDC** (Rick Winfrey 2026, USENIX) — déduplication par bloc pour les sauvegardes incrémentales.
3. **rclone crypt modèle** (AES-CTR + Poly1305, noms chiffrés) — E2E crypto zero-knowledge.
4. **Adaptive chunk size** (EMA sur le débit) — gain immédiat, faible effort.
5. **Erasure coding** (MinIO/Reed-Solomon) — tolérance aux pannes sans réplication brute.
6. **Sync différentiel** (s5cmd : taille+timestamp+ETag) — éviter les transferts inutiles.

## 3. Issues créées

Voir le milestone **Transfer S7** (#138-#145) + nouvelles issues ci-dessous.

## 4. Sources
- AWS S3 Multipart Upload docs (2026)
- AWS S3 Transfer Acceleration docs
- s5cmd GitHub (peak/s5cmd) + benchmarks
- rclone crypt docs (rclone.org)
- FastCDC USENIX ATC'16 (Wen Xia et al.)
- Content-Defined Chunking Part 3 (Rick Winfrey, Feb 2026)
- MinIO erasure coding docs
- simplyblock.io open source S3 tools (2026)
