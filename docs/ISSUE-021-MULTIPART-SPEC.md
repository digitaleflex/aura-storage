# Spécification — Multipart upload complet (ISSUE-021)

**Statut :** partiellement implémenté (P3, planifié).  
**Source :** `docs/MULTIPART-UPLOAD-PLAN.md`, `docs/FONCTIONNALITES.md` §8.

## État actuel

Le multipart upload est **planifié et partiellement implémenté** :

| Élément | État |
|---------|------|
| Routes API | `GET /api/v1/objects/{oid}/multipart`, `POST /api/v1/objects/{oid}/multipart/parts` |
| Condition | Actif uniquement quand `AURA_MULTIPART_ENABLED=1` crée la session |
| Limite actuelle | Upload en une requête, plafonné à 5 GiB (`AURA_MAX_OBJECT_BYTES`) |
| Compatibilité SeaweedFS 4.48 | Gate fermé pour items 1-6 (trois runs 2026-10-25/26) |

## Inconnues documentées (à résoudre avant mise en production)

1. **Disk reclaim après abort** : vérifier que l'espace disque est libéré après un abort multipart
2. **10 000-part completion** : tester la complétion d'un upload avec 10 000 parties

## Comment activer le multipart

```bash
# Dans .env
AURA_MULTIPART_ENABLED=1
```

Puis redémarrer la stack :
```bash
docker compose up -d
```

## Tâches restantes

| Tâche | Description |
|-------|-------------|
| Tester disk reclaim après abort | Vérifier que l'espace disque est libéré |
| Tester 10 000-part completion | Complétion d'un upload avec 10 000 parties |
| Lever `AURA_MULTIPART_ENABLED=0` | Passer par défaut à `1` après validation |
| Mettre à jour `docs/MULTIPART-UPLOAD-PLAN.md` | Documenter les résultats des tests |

## Fichiers concernés

- `api/main.py` — routes multipart (déjà implémentées)
- `api/s3.py` — gestion des parties S3 (déjà implémenté)
- `api/transfer.py` — constante `VERIFYING` (à utiliser pour le flux multipart)
- `docs/MULTIPART-UPLOAD-PLAN.md` — plan existant
- `.env.example` — ajouter `AURA_MULTIPART_ENABLED` (futur)
