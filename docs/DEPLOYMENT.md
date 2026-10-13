# Deployment Runbook

## Status

Checklist for after VPS provisioning. Confirm real provider settings and OS before executing commands.

## Provisioning

- [ ] Confirm monthly transfer quota, disk type/capacity, backups, upgrade path, and renewal price.
- [ ] Install a supported Ubuntu Server LTS if available.
- [ ] Record IP, region, disk layout, hostname and rescue-console process in a private inventory.
- [ ] Verify advertised storage is mounted and inspect filesystem capacity/inodes.
- [ ] Configure SSH keys; verify a second session before changing SSH settings.
- [ ] Configure default-deny firewall. Allow SSH and HTTPS; allow HTTP only if needed for certificate issuance.
- [ ] Install Docker Engine and Compose from trusted vendor instructions.
- [ ] Configure storage DNS and select the HTTPS reverse-proxy path.

## Prepare

Clone the repository and review scripts. Copy `.env.example` to `.env`, generate unique secrets using a cryptographically secure generator, and keep the file out of Git. Create `config/seaweedfs/s3.json` from the example, replace placeholders, verify policy syntax for the pinned release, and restrict file permissions. Never start while placeholders remain.

## Validate

- [ ] Confirm image tag, command flags, S3 policy and healthcheck against selected release.
- [ ] Review `docker compose config` output for unexpected ports, mounts or environment values.
- [ ] Verify only intended ports are host-published.
- [ ] Verify persistent data directory is on the intended filesystem and has sufficient free capacity.
- [ ] Validate the HTTPS edge and firewall.

## Start and acceptance

Run `./scripts/bootstrap.sh`, review its output, then `./scripts/deploy.sh`. Inspect logs, listening sockets, health and restart behavior. Test authenticated upload/download with a non-production object, large-file handling, credential isolation and persistence after container restart. The baseline is not production-certified until all these checks pass.

Do not import important content before HTTPS, authenticated S3 smoke tests, an independent backup and a successful restore test.