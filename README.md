# AURA Storage

AURA is an independently deployable, S3-compatible storage service for private objects used by applications such as OpenBooks and, later, Axiom.

> Status: bootstrap repository. The VPS has not yet been provisioned. This repository is a starting baseline, not proof of production readiness.

## Architecture

- [Rendered Mermaid architecture diagram](docs/ARCHITECTURE-DIAGRAM.md)
- [Mermaid source](docs/ARCHITECTURE.mmd)
- [Architecture explanation](docs/ARCHITECTURE.md)

The diagram describes the intended single-node MVP, including the public HTTPS edge, private SeaweedFS services, persistent storage, operations, and an independent backup destination. Validate the final Compose topology against the selected SeaweedFS release before production.

## Initial design

- One Ubuntu Server LTS VPS (initial single-node deployment).
- Docker Engine and Compose.
- Traefik for HTTPS routing and automatic certificate management; its dashboard must be protected.
- SeaweedFS Filer + S3 API, with internal administration ports kept private.
- Persistent host storage, not container writable layers.
- A separate AURA Management API is planned for catalogue, logical folders, metadata and import jobs; it is not yet implemented.
- Independent encrypted backup destination and tested restore procedure.
- App-specific S3 identities with least privilege. Normal object access must not depend on Axiom or Azure.

One VPS is a single point of failure; a single node is not high availability.

## Before production

1. Verify VPS disk layout, mount, transfer quota, region, renewal terms, and backup options.
2. Secure SSH and host firewall.
3. Generate local secrets; never commit `.env` or real credentials.
4. Validate SeaweedFS image version, command flags, S3 policy syntax, and persistent data behavior.
5. Configure DNS and HTTPS.
6. Test authenticated upload/download, large files, Range requests, restart persistence, independent backup and restore.

## Quick start (after provisioning and review)

```bash
cp .env.example .env
# Generate credentials and update local configuration; never commit .env.
# Create config/seaweedfs/s3.json from its example with matching credentials.
docker compose config --quiet
```

The included deployment configuration is a draft baseline. Review `docs/DEPLOYMENT.md` before running it and do not load important data until the acceptance checklist passes.

## Repository structure

- `docker-compose.yml`: initial topology.
- `.env.example`: placeholders only.
- `config/seaweedfs/s3.json.example`: policy template, to validate against selected SeaweedFS release.
- `scripts/`: deployment validation and smoke-test helpers.
- `docs/`: architecture, security, deployment, operations, backup and restore.
- `tests/`: authenticated S3 smoke-test script.

## Security rules

- Never commit secrets, private keys, certificates, customer files, or backups.
- Do not expose SeaweedFS master, filer, volume, metrics, or admin interfaces publicly.
- Pin reviewed image versions; no `latest` in production.
- Primary VPS storage is not a backup.

No project license is selected yet. Do not assume reuse rights until one is chosen.