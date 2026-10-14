# Detailed Deployment Runbook

## Status and scope

This runbook describes the planned initial single-VPS deployment. The InterServer pilot VPS is provisioned. See [Server Profile](SERVER-PROFILE.md) for observed host details and [Host Bootstrap Checklist](HOST-BOOTSTRAP-CHECKLIST.md) for the phased setup sequence. The OS update reported that a reboot was required; verify the live kernel and SSH access before installing Docker. Verify the actual disk allocation, network quota and supported image releases before executing commands. A successful Compose parse is not production certification.

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
- [ ] Confirm the full advertised capacity using `lsblk`, `df -h`, and `df -i`.
- [ ] Verify SSH key access in a second session before changing SSH configuration.
- [ ] Apply OS security updates.
- [ ] Configure default-deny inbound firewall: SSH from restricted sources when feasible, plus TCP 80/443 for Traefik. Do not open SeaweedFS ports.
- [ ] Install Docker Engine and the Compose plugin using official Docker instructions for the selected Ubuntu release.
- [ ] Confirm Docker starts after reboot and only trusted administrators can control the Docker daemon.

## 2. DNS and TLS prerequisites

1. Use `aura-storage.eurinhash.com` for the pilot if you control the `eurinhash.com` DNS zone (verified resolving to the VPS on 2026-10-14), or set another hostname you control.
2. Set `S3_DOMAIN` in the local `.env` to that hostname and `ACME_EMAIL` to a monitored email address.
3. Create an A record pointing to the VPS public IPv4. Add AAAA only if IPv6 is correctly configured end-to-end.
4. Ensure inbound TCP 80 and 443 reach Traefik directly or through a correctly configured upstream proxy.
5. The Compose baseline uses Let's Encrypt HTTP-01. Certificate issuance fails if DNS is wrong, port 80 is blocked, or another service intercepts the challenge.
6. Never publish the Traefik dashboard publicly without explicit authentication and network restrictions. The current baseline defines no public dashboard route.
7. Opening `https://<S3_DOMAIN>/` in a browser returns XML `AccessDenied` by design; the Compose baseline answers that single unsigned root request with a static page pointing to the app (`docs/S3-ROOT-LANDING.md`).

## 3. Prepare local configuration

Clone the repository and inspect all scripts/configuration before running them:

```bash
git clone https://github.com/digitaleflex/aura-storage.git
cd aura-storage
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally:

- Set the real S3 hostname and monitored ACME email.
- Confirm exact pinned Traefik and SeaweedFS image versions.
- Set `AURA_DATA_DIR` to the intended directory on the verified large filesystem.
- Generate unique random S3 credentials. Prefer alphanumeric/hex values so they can safely be read by the shell-based environment scripts; never reuse production credentials elsewhere.
- Never commit or share `.env`.

The current sample uses `/srv/aura-storage`. Before running bootstrap as a non-root Docker administrator, create the directory and grant ownership to the chosen deployment user, for example after verifying the actual username and mounted filesystem:

```bash
sudo mkdir -p /srv/aura-storage
sudo chown "$USER":"$USER" /srv/aura-storage
chmod 700 /srv/aura-storage
```

Do not run those ownership commands blindly if the directory already contains data or is shared with another service.

Generate the local SeaweedFS S3 configuration from `.env`:

```bash
bash ./scripts/generate-config.sh
chmod 600 config/seaweedfs/s3.json
```

The generator creates `config/seaweedfs/s3.json` from the tracked example and injects the S3 credentials. Review the identity's permissions and validate policy/action names against the exact SeaweedFS release. Do not use a broad Admin identity for routine application traffic.

Confirm both sensitive files are ignored by Git:

```bash
git check-ignore .env config/seaweedfs/s3.json
```

Do not paste secrets into issues, chat, shell history, logs, or committed files.

## 4. Validate Compose before start

```bash
docker compose config --quiet
```

If detailed inspection is necessary, review `docker compose config` locally and do not share its output publicly; it may contain resolved configuration values. Validate:

- Only Traefik publishes host ports 80 and 443.
- SeaweedFS master, volume and filer administration ports have no host port mappings.
- The S3 hostname rule matches `S3_DOMAIN`.
- Traefik and SeaweedFS share the intended edge network; SeaweedFS components share the private storage network.
- Host directories map to the intended persistent filesystem.
- Image versions, command flags and healthchecks match the selected releases.
- The generated S3 config exists and is readable by the container.
- No placeholder values remain.

The helper scripts are conveniences, not substitutes for this review.

## 5. First start

After reviewing the stack:

```bash
bash ./scripts/bootstrap.sh
bash ./scripts/deploy.sh
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
- Changing `AURA_DATA_DIR` points to another location; it does not move existing data.
- Changing `S3_DOMAIN` does not update DNS or endpoint configuration in external clients.
- Independent backup, restore and production security review remain deployment gates.


## SSE-S3 encryption gate for the one-month pilot

The sample now pins SeaweedFS 4.48, which is newer than the previous 3.80 pin and aligns with the documented SSE-S3 configuration. Review the official release notes before deployment; do not silently downgrade to a version whose support is unverified.

1. Generate a 256-bit key locally with openssl rand -hex 32.
2. Put it in WEED_S3_SSE_KEK in the private .env file and keep a separate protected offline copy of the exact key.
3. Run bootstrap and deploy only after reviewing the rendered Compose configuration locally.
4. Run bash tests/sse-s3-smoke-test.sh with AWS CLI v2. It must report ServerSideEncryption=AES256 and a matching SHA-256 after download.
5. If the test fails, do not import the actual PDF/audio collection. Inspect logs and image support; never assume encryption is active merely because the environment variable exists.
6. Keep all originals locally. This test is not a backup test; no original may be deleted until an independent backup has been restored successfully.

The smoke test uses the configured bootstrap S3 identity, which currently has broad permissions. Treat it as a controlled deployment test only; implement and verify a least-privilege runtime identity before multi-user production use.
