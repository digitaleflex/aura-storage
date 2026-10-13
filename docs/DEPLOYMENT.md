# Detailed Deployment Runbook

## Status and scope

This runbook describes the planned initial single-VPS deployment. The provider VPS is not provisioned yet. Verify the actual OS, disk layout, network quota and supported image releases before executing commands. A successful Compose parse is not production certification.

## Target topology

- Docker Engine + Docker Compose.
- Traefik publishes TCP 80/443 and routes the S3 hostname to the SeaweedFS S3 gateway.
- SeaweedFS master, volume and filer/S3 gateway are separate containers on a private storage network.
- Persistent host directories hold SeaweedFS state/data.
- AURA Management API and PostgreSQL catalogue are future work; they are not in the current Compose stack.
- A separate backup target is required before important data is imported.

## 1. Provider and OS checklist

- [ ] Verify price, renewal terms, advertised storage, disk type, monthly transfer quota, backup policy and upgrade path.
- [ ] Provision a supported Ubuntu Server LTS if offered.
- [ ] Record VPS IP, region, hostname, disk device/mount, rescue console and support route in a private inventory.
- [ ] Confirm the full advertised capacity using lsblk, df -h, and df -i.
- [ ] Verify SSH key access in a second session before changing SSH configuration.
- [ ] Apply OS security updates.
- [ ] Configure default-deny inbound firewall: SSH from restricted sources when feasible, plus TCP 80/443 for Traefik. Do not open SeaweedFS ports.
- [ ] Install Docker Engine and the Compose plugin using official Docker instructions for the selected Ubuntu release.
- [ ] Confirm Docker starts after reboot and only trusted administrators can control the Docker daemon.

## 2. DNS and TLS prerequisites

1. Choose a dedicated hostname, for example storage.example.com.
2. Set S3_DOMAIN in the local .env to that hostname and ACME_EMAIL to a monitored email address.
3. Create an A record pointing to the VPS public IPv4. Add AAAA only if IPv6 is correctly configured end-to-end.
4. Ensure inbound TCP 80 and 443 reach Traefik directly or through a correctly configured upstream proxy.
5. The Compose baseline uses Let's Encrypt HTTP-01. Certificate issuance fails if DNS is wrong, port 80 is blocked, or another service intercepts the challenge.
6. Never publish the Traefik dashboard publicly without explicit authentication and network restrictions. The current baseline defines no public dashboard route.

## 3. Prepare local configuration

Clone the repository and inspect all scripts/configuration before running them:

```bash
git clone https://github.com/digitaleflex/aura-storage.git
cd aura-storage
cp .env.example .env
```

Edit .env locally:
- Replace the example hostname and email.
- Confirm exact pinned Traefik and SeaweedFS image versions.
- Set the intended data directory on the verified large filesystem.
- Generate unique random S3 credentials using a cryptographically secure generator.

Create the local S3 configuration:

```bash
cp config/seaweedfs/s3.json.example config/seaweedfs/s3.json
chmod 600 .env config/seaweedfs/s3.json
```

Replace every placeholder in both files. The S3 access key and secret in s3.json must match the intended generated values. Confirm identity policy syntax and action names against the selected SeaweedFS release. The example is a bootstrap template, not a recommended long-term all-powerful application identity.

Confirm the local file is ignored by Git:

```bash
git check-ignore .env config/seaweedfs/s3.json
```

Do not paste secrets into issues, chat, shell history, logs, or committed files.

## 4. Validate Compose before start

```bash
docker compose config --quiet
docker compose config
```

Review rendered configuration privately before sharing output; it can contain sensitive environment values. Validate:
- Only Traefik publishes host ports 80 and 443.
- SeaweedFS master, volume and filer administration ports have no host port mappings.
- The S3 hostname rule matches S3_DOMAIN.
- Traefik and SeaweedFS share the intended edge network; SeaweedFS components share the private storage network.
- Host directories map to the intended persistent filesystem.
- Image versions, command flags and healthchecks match the selected releases.
- The local S3 config exists and is readable by the container.
- No placeholder values remain.

The helper scripts are conveniences, not substitutes for this review.

## 5. First start

After reviewing the stack:

```bash
./scripts/bootstrap.sh
./scripts/deploy.sh
docker compose ps
docker compose logs --tail=150 traefik seaweed-master seaweed-volume seaweed-filer
```

Check that Traefik starts, ACME can reach Let's Encrypt, the S3 hostname receives a valid certificate, SeaweedFS services remain healthy, no unexpected port is public, the data directory is on the intended filesystem, and services survive a controlled container restart.

A running container is not proof that S3 authentication or durability works.

## 6. Acceptance tests before important imports

- [ ] HTTPS certificate validates externally.
- [ ] Unauthenticated S3 requests are rejected as expected.
- [ ] Authenticated test upload/download passes using a restricted test identity.
- [ ] Downloaded bytes match the original test file.
- [ ] Large-file and multipart behavior is tested with the intended client.
- [ ] Audio/video Range requests are tested if streaming is required.
- [ ] A test object remains readable after a controlled container restart.
- [ ] Internal SeaweedFS ports are not publicly reachable.
- [ ] Disk, RAM, CPU and monthly transfer usage can be observed.
- [ ] An independent backup exists and a restore has succeeded in an isolated environment.

## 7. Rollback and recovery

- Do not delete persistent data directories or Docker volumes as a troubleshooting shortcut.
- Before upgrades, record image versions and follow SeaweedFS release-specific backup guidance.
- If TLS fails, inspect DNS, firewall, port 80 reachability and Traefik ACME logs.
- If S3 fails, isolate DNS/TLS/routing/authentication/SeaweedFS/disk causes before restarting all services.
- If the disk is near full, pause bulk imports and inspect capacity; never delete SeaweedFS files manually.
- Follow Backup and Restore for recovery.

## Known limitations

- Single VPS means a single point of failure.
- Management API and PostgreSQL catalogue are not implemented in this initial stack.
- S3 policy, healthcheck commands, SeaweedFS persistence semantics and image flags require validation against exact releases.
- Independent backup, restore and production security review remain deployment gates.