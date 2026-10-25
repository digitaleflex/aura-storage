# AURA Storage

**AURA** is an independently operated storage service for private files. The initial deployment target is one Ubuntu Server LTS VPS with Docker Compose, Traefik, and SeaweedFS exposing an S3-compatible endpoint.

> **Status:** the AURA stack is deployed on the real pilot VPS with dated, partial verification evidence ([2026-10-15 canonical-ids](docs/verification-log-2026-10-15-canonical-ids.md), [2026-10-16 S16 deploy](docs/verification-log-2026-10-16-s16-deploy.md): bootstrap OK, live PostgreSQL migration, SSE-S3 smoke PASS). It is **not accepted** for production: external HTTPS validation, non-publication of internal ports, persistence across a host reboot and an independent backup/restore test remain open gates. Host details are in [Server Profile](docs/SERVER-PROFILE.md) and [Host Bootstrap Checklist](docs/HOST-BOOTSTRAP-CHECKLIST.md).

## Architecture and documentation

- [Rendered architecture diagram](docs/ARCHITECTURE-DIAGRAM.md)
- [Mermaid source](docs/ARCHITECTURE.mmd)
- [Architecture decisions and boundaries](docs/ARCHITECTURE.md)
- [File transfer contract: API + presigned S3 URLs, FTPS boundaries](docs/FILE-TRANSFER.md)
- [Vault transfer engine: upload state machine, progress, retries, cancellation, integrity](docs/TRANSFER-ENGINE.md)
- [S3 multipart upload for large objects (implemented, `AURA_MULTIPART_ENABLED=0` by default; 4.48 compatibility gate partly recorded 2026-10-25 — disk-reclaim UNKNOWN, checksums measured, edge-proxy path proven, gateway part-size/count limits unprobed but mitigated in code)](docs/MULTIPART-UPLOAD-PLAN.md)
- [Secure and efficient bulk transfers: security, resumability, multipart, compression and benchmarks](docs/SECURE-BULK-TRANSFERS.md)
- [Storage platform problem landscape: common failures, proven solutions, trade-offs and AURA priorities](docs/STORAGE-PLATFORM-PROBLEM-LANDSCAPE.md)
- [Detailed deployment runbook](docs/DEPLOYMENT.md)
- [Reproducible VPS setup and recovery guide](docs/REPRODUCIBLE-SETUP.md)
- [SSH access and per-device key management (no private keys)](docs/SSH-ACCESS-AND-KEY-MANAGEMENT.md)
- [Network architecture and throughput test plan (documentation only)](docs/NETWORK-AND-THROUGHPUT-PLAN.md)
- [Read-only host preflight diagnostic](scripts/host-preflight.sh)
- [Deployment verification log template](docs/verification-log-template.md)
- [Multipart compatibility verification log — SeaweedFS 4.48, 2026-10-25](docs/verification-log-2026-10-25-multipart-compat-4.48.md)
- [Multipart part PUT through the edge proxy verification log — Traefik, 2026-10-25](docs/verification-log-2026-10-25-multipart-proxy-4.48.md)
- [VPS server profile](docs/SERVER-PROFILE.md)
- [Host bootstrap and hardening checklist](docs/HOST-BOOTSTRAP-CHECKLIST.md)
- [Environment configuration and domain migration](docs/ENVIRONMENT-CONFIGURATION.md)
- [Security baseline](docs/SECURITY.md)
- [Authorization matrix and identity model](docs/AUTHORIZATION-MATRIX.md)
- [API specification (partially implemented — object/folder routes shipped, import-jobs and multipart proposed)](docs/API-SPECIFICATION.md)
- [OpenAPI contract draft](docs/openapi.yaml)
- [Catalogue data model (partially implemented; proposals marked inline)](docs/DATA-MODEL.md)
- [Operations playbook](docs/OPERATIONS-PLAYBOOK.md)
- [Backup and restore](docs/BACKUP-RESTORE.md)
- [Traefik configuration notes](config/traefik/README.md)
- [API routes audit (real routes vs OpenAPI)](docs/API-ROUTES-AUDIT.md)
- [Transfer engine formal audit](docs/TRANSFER-ENGINE-AUDIT.md)
- [QA-01 validation checklist and release gate](docs/QA-01-CHECKLIST.md)
- [Decision: defer Better Auth + Google OAuth](docs/DECISION-BETTER-AUTH.md)
- [Decision: defer independent backup](docs/DECISION-BACKUP-DEFERRED.md)
- [Decision: advanced transfer features deferred](docs/DECISION-ADVANCED-TRANSFER-FEATURES.md)
- [Padding audit report](docs/DESIGN-PADDING-AUDIT.md)

## Intended topology

- **Traefik** publishes ports 80/443, routes HTTPS, and manages Let's Encrypt certificates through the HTTP-01 challenge.
- **SeaweedFS master, volume and filer/S3 gateway** run as separate containers on a private storage network.
- Traefik routes the S3 hostname, the app hostname (`APP_DOMAIN`), the dashboard (`DASHBOARD_DOMAIN`, behind BasicAuth) and the S3 root landing page. SeaweedFS administrative endpoints are not published on host ports.
- Persistent data is mounted from the host filesystem.
- **AURA Management API + PostgreSQL catalogue** are implemented, included in the Compose stack (the API is reachable only through the app proxy, with no host ports) and running on the pilot with partial dated evidence; they have not passed acceptance on the pilot VPS.
- **Authorization and machine-to-machine identities** are enforced server-side; see [Authorization matrix](docs/AUTHORIZATION-MATRIX.md).
- Independent backups and a successful restore test are mandatory before production imports.

A single VPS is a single point of failure, not high availability. An S3-compatible endpoint does not itself provide redundancy.

## Environment-first configuration

Environment-specific settings are centralized in the local `.env`; see [Environment Configuration](docs/ENVIRONMENT-CONFIGURATION.md). The tracked `.env.example` documents available settings. The local S3 config is generated by `bash ./scripts/generate-config.sh` and must never be committed.

Typical setup:

```bash
git clone --branch feat/secure-storage-pilot https://github.com/digitaleflex/aura-storage.git
cd aura-storage
cp .env.example .env
chmod 600 .env
# Edit .env locally and replace every placeholder.
bash ./scripts/generate-config.sh
docker compose config --quiet
```

After the feature branch has been reviewed and merged, clone `main` instead. See [Reproducible Setup](docs/REPRODUCIBLE-SETUP.md) for the phased host preparation, SSH key verification, optional VPN, Docker, deployment, tests, backup/restore and rollback procedures.

Changing `S3_DOMAIN` changes the hostname Traefik routes; it does not automatically update DNS or endpoint settings in external clients. Changing `AURA_DATA_DIR` does not move existing data. Review the runbook before deployment.

## Security rules

- Never commit `.env`, `config/seaweedfs/s3.json`, keys, certificates, user files, or backups.
- Only Traefik publishes ports 80 and 443 in the baseline.
- Keep SeaweedFS master, volume, filer UI/admin, metrics, and other internal ports private.
- Traefik's dashboard is not a file-management interface. It is routed on `DASHBOARD_DOMAIN` (HTTPS) behind BasicAuth (`dash-auth`); keep it protected and never publish port 8080 or add an unauthenticated route.
- Use separate least-privilege credentials per application.
- The VPS is not a backup; use a separate destination and test restoration.
- Validate S3 policy syntax/actions and image flags against the exact selected SeaweedFS release.

This repository is proprietary; all rights reserved (see [LICENSE](LICENSE) and
[ADR-006](docs/DECISIONS.md)). Third-party components keep their own licenses —
see [THIRD-PARTY.md](THIRD-PARTY.md).

## Encryption gate for the pilot

The sample passes a 256-bit key through WEED_S3_SSE_KEK for SeaweedFS SSE-S3 object encryption. Generate it locally with `openssl rand -hex 32` and keep a protected offline copy outside the VPS and Git repository. Losing this key may make encrypted objects unrecoverable.

Before transferring actual PDF/audio files, run `bash tests/sse-s3-smoke-test.sh` against the deployed stack. Confirm the S3 response reports `ServerSideEncryption=AES256` and the downloaded bytes match. This smoke test PASSed on the pilot on 2026-10-15 and 2026-10-16 (see the dated verification logs) and the API runs on live PostgreSQL there. The deployment is still **not accepted**: external HTTPS validation (partially recorded), non-publication of internal ports, persistence across a host reboot, and an independent backup/restore test remain open gates. Keep the local originals until an independent backup has been restored successfully.
