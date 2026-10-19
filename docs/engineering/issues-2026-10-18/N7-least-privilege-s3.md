## Contexte
L'API, et maintenant la sauvegarde, utilisent `S3_ACCESS_KEY`, l'identité **Admin** de SeaweedFS. #22 le demandait ; #22 est proposée en fusion, ce point unique est repris ici.

## Proposition
`scripts/generate-config.sh` génère trois identités à partir de `.env` :
| Identité | Actions | Utilisée par |
|---|---|---|
| `aura-api` | Read, Write, List, Tagging sur les buckets AURA | API (presign + commit + purge) |
| `aura-backup` | Read, List | `scripts/backup.sh` |
| `aura-admin` | Admin | opérations manuelles, restauration |

Vérifier avec `scripts/seaweedfs-compat-probe.py` que SeaweedFS 4.48 applique bien ces restrictions (refus d'un `DeleteObject` par `aura-backup`, etc.).

## Critères
- [ ] Tests de refus par identité sur la version épinglée.
- [ ] Rotation documentée.
