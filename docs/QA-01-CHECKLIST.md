# Checklist de validation complète et release gate AURA Storage (QA-01)

## Pré-requis
- [ ] `AURA_API_DB` pointe vers PostgreSQL réel (`AURA_TEST_PG_DSN`) pour parity.
- [ ] SSE-S3 vérifié (`ServerSideEncryption: AES256` sur GET HeadObject).
- [ ] `WEED_S3_SSE_KEK` sauvegardé hors VPS.

## Validation fonctionnelle
- [ ] Login admin + session cookie + CSRF.
- [ ] Upload simple (single PUT) : taille, checksum, statut available.
- [ ] Upload multipart : parties, reprise, complete, abort.
- [ ] Download : Range, Content-Range, reprise.
- [ ] Suppression soft + purge two-phase + restauration.
- [ ] Partage public (token, expiration, révocation).
- [ ] Administration : espaces, applications, identités, audit, usage.

## Sécurité
- [ ] Isolation cross-tenant (tests/test_security_isolation.py, test_m06_isolation_matrix.py).
- [ ] Pas de secrets dans les logs.
- [ ] HTTPS + CSP servie (postflight deploy.sh).

## Performance
- [ ] Benchmarks reproductibles (scripts/bench_transfer.py).
- [ ] Pas de création non bornée de tâches.

## Release gate
- [ ] Suite complète `pytest tests/` verte (343+ passed).
- [ ] `npm run build` vert.
- [ ] `docker compose config --quiet` OK avec .env local.
- [ ] Vérification host (docs/DEPLOYMENT.md) — gate d'approbation requise.

## Statut
Document de préparation. Exécution finale sur déploiement de validation (gate d'approbation).
