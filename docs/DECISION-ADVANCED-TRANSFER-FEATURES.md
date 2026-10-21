# Decisions — Fonctionnalites avancees du Transfer Engine (#138-#149)

## Contexte
Ces fonctionnalites sont des optimisations et capacites avancees non implementees.
Elles necessitent des decisions d'architecture et des gates d'approbation.

## Decisions proposees

| # | Fonctionnalite | Decision | Justification |
|---|---|---|---|
| 138 | Multipart par partie avec retry/checksum | Differer | Multipart de base deja implemente. Optimisation. |
| 139 | Taille de chunk adaptive (RTT+debit) | Differer | Optimisation performance, pas bloquant. |
| 140 | Compression automatique (magic bytes) | Differer | Risque de corruption si mal implemente. |
| 141 | Chiffrement E2E AES-GCM client | Differer (decision humaine) | Perte de cle = perte de donnees. |
| 142 | Content-Defined Chunking (CDC) | Differer | Deduplication avancee, cout eleve. |
| 143 | Object Lock / WORM | Differer (decision legale) | Retention legale, conformite. |
| 146 | FastCDC | Differer | Optimisation de #142. |
| 147 | rclone crypt | Differer | Complexite. |
| 148 | Chunk adaptive (EMA) | Differer | Optimisation de #139. |
| 149 | Sync differentiel | Differer | Fonctionnalite avancee. |

## Recommandation
Implementer maintenant : rien (toutes sont des optimisations/avancees).
Differer : toutes, jusqu'a validation du pilote en production.
Decision humaine requise : #141 (crypto E2E), #143 (Object Lock/WORM).

## Statut
Document de decision. Issues #138-#149 restent ouvertes pour planification future.
EOF