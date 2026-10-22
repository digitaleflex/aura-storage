# Mesurer la vitesse des envois (avant / après un déploiement)

Procédure **lecture seule**. Elle ne modifie rien sur le serveur ; le déploiement,
lui, reste une décision humaine.

## 1. Avant de déployer (référence)

1. Notez la date, la version déployée (`git rev-parse --short HEAD` sur le serveur) et
   votre débit montant réel (test de débit depuis le poste qui envoie).
2. Importez un lot test représentatif : par exemple 20 fichiers de 5 à 50 Mo et
   2 fichiers de plus de 300 Mo. **Pas d'original PDF/audio** tant que la restauration
   indépendante n'a pas été testée.
3. Notez le temps total, du clic à « tout disponible ».
4. Enregistrez les journaux :
   ```bash
   docker logs aura-001-api     > api-avant.log 2>&1
   docker logs aura-001-traefik > traefik-avant.log 2>&1
   python3 scripts/transfer-baseline.py --api-log api-avant.log --traefik-log traefik-avant.log
   ```

## 2. Après le déploiement

Mêmes étapes avec le même lot, fichiers `*-apres.log`.

## 3. Lire le résultat

| Mesure | Signification | Bon signe |
|---|---|---|
| `Commit re-read` MiB/s, p95 `hash_ms` | coût de la relecture d'intégrité | p95 en baisse, débit stable quand 4 envois tournent |
| `Proxy PUTs … cut or >= 1100s` | envois coupés par Traefik (`readTimeout` 1200 s) | 0 |
| `Storage throttling lines` | SlowDown/Throttling du stockage | 0 |
| Temps total du lot | ce que l'utilisateur ressent | en baisse à débit montant égal |

Si le temps total ne baisse pas alors que ces trois mesures sont bonnes, le goulot est
ailleurs (débit montant, disque) : envoyez-moi les deux sorties pour la suite.

## 4. Banc isolé (sans toucher au pilote)

`tests/commit-latency-bench.sh` mesure le coût de la relecture dans un environnement
jetable (voir `docs/engineering/commit-latency-bench.md`).
