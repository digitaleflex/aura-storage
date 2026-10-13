# AURA Storage

**AURA** is an independently operated storage service for private files. The initial deployment target is one Ubuntu Server LTS VPS with Docker Compose, Traefik, and SeaweedFS exposing an S3-compatible endpoint.

> **Status:** preparation stage. The InterServer VPS has not yet been purchased. Files in this repository are an implementation baseline and detailed plan; the stack has not yet been validated on the real provider VPS.

## Architecture and documentation

- [Rendered architecture diagram](docs/ARCHITECTURE-DIAGRAM.md)
- [Mermaid source](docs/ARCHITECTURE.mmd)
- [Architecture decisions and boundaries](docs/ARCHITECTURE.md)
- [Detailed deployment runbook](docs/DEPLOYMENT.md)
- [Security baseline](docs/SECURITY.md)
- [API specification (proposal, not implemented)](docs/API-SPECIFICATION.md)
- [OpenAPI contract draft](docs/openapi.yaml)
- [Proposed catalogue data model](docs/DATA-MODEL.md)
- [Operations playbook](docs/OPERATIONS-PLAYBOOK.md)
- [Backup and restore](docs/BACKUP-RESTORE.md)
- [Traefik configuration notes](config/traefik/README.md)

## Intended topology

- **Traefik** publishes ports 80/443, routes HTTPS, and manages Let's Encrypt certificates through the HTTP-01 challenge.
- **SeaweedFS master, volume and filer/S3 gateway** run as separate containers on a private storage network.
- Only the S3 hostname is routed by the initial Traefik configuration. SeaweedFS administrative endpoints are not published on host ports.
- Persistent data is mounted from the host filesystem.
- **AURA Management API + PostgreSQL catalogue** are planned components. They are not implemented or included in the current Compose stack.
- Independent backups and a successful restore test are mandatory before production imports.

A single VPS is a single point of failure, not high availability. An S3-compatible endpoint does not itself provide redundancy.

## Before deployment

1. Provision the VPS and verify actual OS, disk layout/mount, IP, transfer quota and renewal terms.
2. Point the selected S3 DNS hostname at the VPS and configure firewall rules.
3. Copy .env.example to .env and replace every example value locally.
4. Create config/seaweedfs/s3.json from config/seaweedfs/s3.json.example, using the same generated credentials and a policy syntax verified for the chosen SeaweedFS release.
5. Review and validate image versions, command flags, healthchecks, persistence behavior and Traefik labels.
6. Run authenticated S3 upload/download, large-file/Range, restart persistence, independent backup and restore tests.

## Quick start after provisioning

Do not run this as a blind copy/paste. Complete and review the deployment runbook first.

```bash
git clone https://github.com/digitaleflex/aura-storage.git
cd aura-storage
cp .env.example .env
# Edit .env locally: real hostname, email, pinned image versions, generated secrets.
# Create config/seaweedfs/s3.json from the example; keep it local and chmod 600.
docker compose config --quiet
```

The initial Compose stack is not production-certified until its exact flags and S3 policy have been tested against the selected releases and actual VPS.

## Security rules

- Never commit .env, config/seaweedfs/s3.json, secrets, keys, certificates, user files, or backups.
- Only Traefik publishes ports 80 and 443 in the baseline.
- Keep SeaweedFS master, volume, filer UI/admin, metrics, and other internal ports private.
- Traefik's dashboard is not a file-management interface and has no public router by default.
- Use separate least-privilege credentials per application.
- The VPS is not a backup; use a separate destination and test restoration.

No repository license has been selected. Do not assume reuse rights until a license is deliberately chosen.