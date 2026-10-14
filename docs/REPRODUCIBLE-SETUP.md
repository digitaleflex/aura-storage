# Reproducible setup and recovery guide

**Project:** AURA Storage  
**Repository:** https://github.com/digitaleflex/aura-storage  
**Deployment target:** one InterServer Ubuntu VPS, initially a controlled pilot  
**Status:** instructions are documented; this guide does not mean the VPS deployment has passed acceptance.

## 1. Operating rules

- Execute commands in order and stop if a verification fails.
- Connect as `aura-admin`; use `sudo` for administrative commands. Do not operate the whole deployment as root.
- Keep one working SSH session open while testing a second session or changing SSH/firewall settings.
- Confirm that the provider panel/rescue console is available before network hardening.
- Never commit `.env`, generated S3 config, private keys, the SSE-S3 key, credentials, user files, certificates, or backups.
- Do not import original documents until encryption, HTTPS, authentication, persistence, independent backup, and isolated restore tests pass.
- Record verified outputs and timestamps in the private deployment log. Do not record secret values, tokens, private keys, or full environment dumps.
- Do not treat a CI pass or `docker compose config --quiet` as proof of a working production deployment.

## 2. Known pilot inventory (re-verify before use)

- Provider: InterServer, VPS ID 3718250
- Hostname: `vps3718250.trouble-free.net`
- IPv4 last recorded: `153.75.248.230`
- OS last recorded: Ubuntu 26.04 LTS (`resolute`)
- Plan last recorded: KVM Storage 3 Slices; 2 vCPU and approximately 5.3 GiB RAM
- Root filesystem last observed: approximately 2.9 TiB. This is unusually large relative to the plan; reconcile actual allocation, mount and quota with the provider before relying on it.
- Administrator: `aura-admin`; sudo was verified.
- At the last recorded OS check, kernel `7.0.0-28-generic` was running while `7.0.0-38-generic` was installed and a reboot was required. This may now be stale; verify the live state.
- SSH key login, firewall, Docker, VPN, AURA containers, S3 encryption, HTTPS and restore are not yet confirmed by this document.

## 3. Phase A — preflight and controlled reboot

Connect as `aura-admin` and run:

```bash
whoami
id
sudo -v
sudo id -u
cat /etc/os-release
uname -r
nproc
free -h
lsblk -f
df -hT
df -i
ip -brief address
systemctl is-active ssh
systemctl status ssh.socket --no-pager
test -e /var/run/reboot-required && echo "REBOOT REQUIRED" || echo "No reboot marker"
```

Expected: `whoami` is `aura-admin`, `sudo id -u` prints `0`, SSH is active, and the OS/disk/network values are understood. Investigate discrepancies before continuing.

If a reboot is required, first confirm you can access the provider console and that the admin account works. Then:

```bash
sudo reboot
```

Reconnect using the provider-supported method and verify:

```bash
whoami
uname -r
systemctl is-active ssh
sudo -v
```

Do not assume a reboot succeeded merely because SSH disconnected. Confirm the running kernel and access.

## 4. Phase B — SSH public key

On the trusted workstation, create a dedicated key if one does not already exist. Example for OpenSSH:

```bash
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/aura_storage_admin
```

Use a strong passphrase. Transfer **only** the public key (`aura_storage_admin.pub`) to the server using a trusted channel. On the VPS, ensure the authorized key is installed for `aura-admin` with correct ownership and permissions. Example, after safely transferring the public key to a temporary path:

```bash
install -d -m 700 -o aura-admin -g aura-admin /home/aura-admin/.ssh
install -m 600 -o aura-admin -g aura-admin /tmp/aura_storage_admin.pub /home/aura-admin/.ssh/authorized_keys
```

If `authorized_keys` already contains valid keys, append the new public key instead of overwriting the file. Remove the temporary public-key file after use. From the workstation, open a **second** terminal and test:

```bash
ssh -i ~/.ssh/aura_storage_admin aura-admin@153.75.248.230
```

Replace the IP if the provider inventory has changed. In the new session run `whoami` and `sudo -v`. Keep the original session open. Only after key login is proven and console recovery is available should SSH password/root-login policy be reviewed. Validate SSH config before reloading it. Do not blindly change `ssh.service` enablement: this host previously used `ssh.socket` activation.

## 5. Phase C — firewall and optional WireGuard administration VPN

The baseline deployment needs inbound TCP 80/443 for public HTTPS and an administrative SSH path. The firewall must not be enabled or tightened until the actual firewall manager, SSH source address, provider firewall, and console recovery path are confirmed.

WireGuard is **optional and not installed by this guide**. If chosen, use it initially for private administration only, not as a full-tunnel internet gateway. Install and configure it only after SSH key access is proven. Keep SSH reachable as a recovery path until a VPN handshake and administration through the VPN have been independently tested. Allow the chosen WireGuard UDP port at both provider and host firewall. Do not expose SeaweedFS internal ports publicly. See the [official Ubuntu WireGuard guide](https://ubuntu.com/server/docs/how-to/wireguard-vpn/).

Before applying firewall rules, capture:

```bash
sudo ufw status verbose
sudo nft list ruleset
sudo ss -lntup
```

These are inspection commands; they do not establish which firewall policy is appropriate. Document the chosen firewall and verify access from a separate client after each change.

## 6. Phase D — install Docker

Check the current [official Docker Engine installation instructions for Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and confirm support for the exact Ubuntu release before running the vendor repository setup. Do not use an old one-line installer from an unverified source.

After installation, verify:

```bash
docker --version
docker compose version
sudo systemctl is-active docker
```

Do not add `aura-admin` to the `docker` group without a deliberate decision: Docker daemon access is effectively root-equivalent. Use `sudo docker` if least privilege is preferred. Reboot verification should include `sudo systemctl is-active docker`.

## 7. Phase E — obtain the reviewed repository and configure secrets locally

Use the deployment branch until its pull request is reviewed and merged, or use `main` after merge:

```bash
git clone --branch feat/secure-storage-pilot https://github.com/digitaleflex/aura-storage.git
cd aura-storage
git status --short --branch
git log -1 --oneline
```

Review the branch and current pull request before running scripts. Create the local environment file:

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally. Set a DNS hostname you control, a monitored ACME email, unique random S3 credentials, the intended data directory, and a fresh 256-bit SSE-S3 key generated locally:

```bash
openssl rand -hex 32
```

Copy the key directly into the private `.env` file using a local editor; do not paste it into chat or GitHub. Keep an independent protected offline recovery copy. Losing the encryption key may make encrypted objects unrecoverable. Do not put secrets on a shell command line or into shell history.

Inspect the generator and configuration before running:

```bash
sed -n '1,240p' scripts/generate-config.sh
bash ./scripts/generate-config.sh
chmod 600 config/seaweedfs/s3.json
git check-ignore .env config/seaweedfs/s3.json
git status --short
```

The ignore check should identify both sensitive paths as ignored. If it does not, stop and fix ignore rules before proceeding. Do not display or publish the contents of `.env` or generated S3 config.

## 8. Phase F — storage path, DNS and configuration validation

Inspect capacity and mount points again. Confirm the actual data filesystem with the provider. Do not assume the observed 2.9 TiB is guaranteed capacity.

Before creating or changing `AURA_DATA_DIR`, check whether the path already exists and contains data. For a new empty path only, create it with restrictive permissions and appropriate ownership. Do not recursively change ownership of an existing directory without inspecting it.

Create the DNS A record for the selected S3 hostname pointing to the verified VPS IPv4. Configure AAAA only if IPv6 routing and firewalling work end-to-end. Confirm inbound TCP 80/443 reaches Traefik. Then run:

```bash
docker compose config --quiet
```

If this fails, stop. If you need to inspect expanded Compose output, do so locally only because resolved output can include sensitive configuration. Review published ports, networks, host paths, health checks, image tags and command flags against the pinned image release. Only Traefik should publish public TCP 80/443 in the baseline. SeaweedFS admin and internal service ports must not be published.

## 9. Phase G — deploy and validate the pilot

Read `docs/DEPLOYMENT.md`, `docs/SECURITY.md`, `docs/ENVIRONMENT-CONFIGURATION.md` and `docs/BACKUP-RESTORE.md` before deployment. Inspect scripts before executing them.

```bash
bash ./scripts/bootstrap.sh
bash ./scripts/deploy.sh
docker compose ps
docker compose logs --tail=150 traefik seaweed-master seaweed-volume seaweed-filer
```

`deploy.sh` builds the frontend bundle (`web/dist`, git-ignored, bind-mounted into the `app` container) with `npm ci && npm run build` before starting the stack, so Node.js and npm must be installed. It then rebuilds the API image from `api/` and pulls the remaining registry images.

Use the service names from the current Compose file if they differ. Check DNS, certificate validity, expected container health, disk path, and absence of unintended public ports. Never publish full logs without checking for sensitive values.

Run the encryption smoke test using the documented AWS CLI v2 prerequisites:

```bash
bash tests/sse-s3-smoke-test.sh
```

Required evidence: the server reports `ServerSideEncryption=AES256`; downloaded bytes match the uploaded test object; unauthenticated access is denied; authenticated test access behaves as expected; internal ports are not reachable externally; and objects persist across a controlled container restart and host reboot. A passing upload alone does not prove durability.

## 10. Phase H — independent backup and restore gate

Choose a backup destination outside this VPS and preferably outside the same provider/account failure domain. Follow the selected SeaweedFS release's documented consistency and backup requirements. Include the data, required metadata/configuration, and a secure method to recover the exact SSE-S3 key.

Restore into an isolated environment. Verify that restored objects can be read/decrypted and their hashes match. Record scope, date, result and recovery duration in the private verification log. A snapshot or second directory on this VPS is not an independent backup.

**Do not import valuable original PDFs/audio until this independent restore succeeds. Do not delete local originals until a later, explicitly approved migration and retention plan is complete.**

## 11. Repeatable verification commands

After every deployment or maintenance window:

```bash
date -Is
git status --short --branch
git log -1 --oneline
uname -r
systemctl is-active ssh
sudo systemctl is-active docker
docker compose ps
df -hT
df -i
free -h
sudo ss -lntup
```

Run Compose-specific checks from the repository directory. Check service logs and the external HTTPS/S3 acceptance tests. Store evidence without secrets in `docs/verification-log.md` or a private operations record; never commit private addresses, credentials, keys or customer metadata unnecessarily.

## 12. Rollback and incident handling

- If SSH fails, use the provider's console/rescue path. Do not repeatedly alter firewall/SSH config without a recovery path.
- If TLS fails, inspect DNS, TCP/80 reachability, ACME and Traefik logs.
- If S3 fails, isolate DNS, TLS, routing, authentication, service health and disk capacity before restarting components.
- Never delete SeaweedFS data directories or Docker volumes as a troubleshooting shortcut.
- Before upgrading pinned images, read release notes and follow the release-specific backup procedure.
- If the SSE key is missing or suspected exposed, stop writes and follow a documented key-recovery/rotation plan; do not assume existing objects will re-encrypt automatically.
- A single VPS is not highly available. Plan a separate recovery target and test it.

## 13. Definition of done

The pilot is not accepted until all relevant items are evidenced:

- [ ] Host rebooted into the intended kernel and administrator access verified.
- [ ] SSH public-key login tested in a second session.
- [ ] Firewall and provider networking reviewed; recovery path confirmed.
- [ ] Optional WireGuard, if enabled, has a tested handshake and does not lock out SSH.
- [ ] Docker/Compose start successfully and survive reboot.
- [ ] Secrets and generated configuration are ignored by Git.
- [ ] DNS and HTTPS certificate validate externally.
- [ ] Only intended public ports are reachable.
- [ ] S3 auth, SSE-S3, byte integrity and persistence tests pass.
- [ ] Independent backup restored in isolation; encrypted objects are readable.
- [ ] Private verification log records the test evidence.
- [ ] Original files remain untouched until migration approval and restore evidence exist.

## References

- [Ubuntu Server WireGuard VPN](https://ubuntu.com/server/docs/how-to/wireguard-vpn/)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [WireGuard official quick start](https://www.wireguard.com/quickstart/)


## Network performance and optional personal VPN

See [Network architecture and throughput test plan](NETWORK-AND-THROUGHPUT-PLAN.md) for the design and test matrix covering AURA transfers, Internet downloads and transfers between devices. This is documentation only. Do not install WireGuard, benchmark tools, change firewall/routing or deploy AURA until the SSH safety gate and live host preflight have been reviewed. Keep AURA storage traffic and the optional full-tunnel personal VPN logically separate; do not assume a VPN will increase throughput.


## SSH access inventory and device keys

Use [SSH access and key management](SSH-ACCESS-AND-KEY-MANAGEMENT.md) for the recorded VPS connection details, per-device SSH key policy, fingerprint inventory and safe validation sequence. This document contains no private keys. SSH public keys and WireGuard keys serve different purposes. Actual device keys must be generated locally and tested; their existence is not implied by the documentation.
