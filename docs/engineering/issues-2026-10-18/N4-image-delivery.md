## Contexte
`scripts/deploy.sh` fait `npm ci && npm run build` et `docker compose build` **sur le VPS**. Conséquences : outils de build sur le serveur de production, builds non reproductibles, pas de retour arrière simple vers la version précédente.

## Proposition
- La CI construit deux images à chaque tag `v*` : `ghcr.io/digitaleflex/aura-api` et `ghcr.io/digitaleflex/aura-app` (nginx + `web/dist` intégré).
- Les images sont référencées par **digest** dans `.env` (`AURA_API_IMAGE`, `AURA_APP_IMAGE`).
- `deploy.sh <tag>` : pull + `up -d` ; `rollback.sh` : revient au digest précédent (consigné dans `deploy-history.log`).
- Option : signature (cosign) et SBOM.

## Critères
- [ ] Le VPS n'a plus besoin de Node ni de build Docker.
- [ ] Retour arrière démontré en moins de 2 minutes sur l'environnement de test.
- [ ] Doc DEPLOYMENT.md mise à jour.

## Décision requise
Visibilité des images (GHCR privé + token de lecture sur le VPS, ou public).
