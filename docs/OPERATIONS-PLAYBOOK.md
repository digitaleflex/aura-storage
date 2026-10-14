# AURA Operations Playbook

> Référence d'exploitation détaillée : [RUNBOOK.md](RUNBOOK.md) (démarrage/arrêt,
> mise à jour/retour arrière, rotation des secrets, seuils de capacité, findings du
> pilote, risques résiduels — dossier préparé pour l'issue #11). Ce playbook reste
> l'aide-mémoire synthétique ; en cas de divergence, le RUNBOOK prévaut et l'écart doit
> être signalé puis corrigé.

## Before first start

- Confirm disk is mounted at the expected path and has sufficient free space.
- Verify all sample values have been replaced in local-only files.
- Verify DNS and HTTPS plan.
- Verify firewall and port exposure.
- Validate Compose configuration and image versions.
- Confirm a recovery path from the provider console.

## Routine operation

Check:
- `docker compose ps`
- `docker compose logs --since=30m traefik seaweed-master seaweed-volume seaweed-filer`
- filesystem usage with `df -h` and inode usage with `df -i`
- provider transfer usage
- certificate issuance/renewal messages
- backup freshness and destination capacity.

## Disk pressure

1. Stop new bulk imports if free space reaches the alert threshold.
2. Identify usage with read-only inspection tools.
3. Confirm recent independent backups and available expansion path.
4. Do not delete volume files manually or remove Docker volumes to reclaim space.
5. Resume imports only after capacity and integrity checks.

## S3/API incident

1. Determine whether failure is DNS/TLS, Traefik routing, S3 auth, SeaweedFS health, or disk exhaustion.
2. Inspect relevant logs and status without printing secrets.
3. Avoid restarting all services simultaneously unless required.
4. Preserve logs and record incident timeline.
5. Test read/write with a dedicated non-production object after recovery.

## Upgrade and rollback

- Read release notes and pin a reviewed image tag/digest.
- Test with representative data in an isolated environment.
- Confirm the documented backup/restore approach for the version transition.
- Capture current image tags and config before change.
- Do not assume downgrade compatibility for storage metadata.
