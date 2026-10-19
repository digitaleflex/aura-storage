# Host bootstrap and hardening checklist

> **Scope:** InterServer pilot VPS for AURA Storage.  
> **Working account:** aura-admin.  
> **Rule:** complete each phase and verify it before starting the next. Do not import real files during bootstrap.

## Phase 0 — Confirm current host state

- [ ] Connect as aura-admin in a new SSH session.
- [ ] Confirm the identity and sudo path:

      whoami
      id
      sudo -v
      sudo id -u

- [ ] Confirm the host state:

      cat /etc/os-release
      uname -r
      nproc
      free -h
      df -h / /boot
      ip -brief address

- [ ] If /var/run/reboot-required exists, plan a controlled reboot before installing Docker.
- [ ] Confirm the provider panel or recovery console is accessible before hardening SSH.

The reboot was performed and verified on 2026-10-14: the running kernel is 7.0.0-38-generic and no `/var/run/reboot-required` marker is present (see [Server Profile](SERVER-PROFILE.md)). Recheck the live state before proceeding.

## Phase 1 — Administrator access

- [x] Create the aura-admin account.
- [x] Add aura-admin to the sudo group.
- [x] Configure sudo timestamp_timeout=30 in /etc/sudoers.d/90-aura-admin.
- [x] Validate sudo syntax with visudo -c.
- [x] Confirm sudo id -u returns 0.
- [ ] Revalidate the account after the next reboot.
- [ ] Generate an SSH key on the trusted workstation.
- [ ] Install only the public key in /home/aura-admin/.ssh/authorized_keys.
- [ ] Set strict ownership and permissions on .ssh and authorized_keys.
- [ ] Test key-based login from a second terminal while the original session remains open.
- [ ] Confirm sudo still works in the new key-based session.

Never upload the private key to the VPS, GitHub, this repository, tickets, or chat.

## Phase 2 — SSH and network hardening

Perform this phase only after key-based login has been tested and a provider recovery path is available.

- [ ] Inspect effective SSH configuration, including included files and socket activation.
- [ ] Confirm the intended administrator can log in with a key in a new session.
- [ ] Decide whether password authentication and root login can be disabled safely.
- [ ] Validate SSH configuration before applying changes.
- [ ] Apply changes in a way that does not terminate the only working session.
- [ ] Configure host/provider firewalls with default-deny inbound policy.
- [ ] Allow SSH only from known administrative source addresses where feasible.
- [ ] Allow public TCP/80 and TCP/443 for Traefik when deploying HTTPS.
- [ ] Do not publish SeaweedFS master, volume, filer/admin, metrics, or database ports.
- [ ] Verify firewall behavior from an independent client.

Do not copy generic firewall commands without confirming the active firewall manager and SSH source address. A misconfigured firewall can lock out the administrator.

## Phase 3 — Install container runtime

- [ ] Confirm the Ubuntu release is supported by the selected Docker Engine installation method.
- [ ] Follow the official Docker installation instructions for that exact release.
- [ ] Install Docker Engine and the Compose plugin.
- [ ] Verify versions and service state:

      docker --version
      docker compose version
      sudo systemctl is-active docker

- [ ] Decide deliberately whether aura-admin needs membership in the docker group. Membership in that group is effectively root-level access; do not add it merely for convenience.
- [ ] Verify Docker starts after reboot.
- [ ] Review the Compose files and pinned image versions before the first launch.

## Phase 4 — Prepare AURA storage paths and configuration

- [ ] Inspect block devices and filesystem usage before choosing a data path:

      lsblk -f
      df -hT
      df -i

- [ ] Confirm the provider's actual storage allocation; the guest reported a 2.9 TiB root filesystem, which must be reconciled with the plan details.
- [ ] Select and document the final persistent data directory.
- [ ] Create the directory with least-privilege ownership and permissions.
- [ ] Clone the repository into an appropriate administrative directory.
- [ ] Create a local .env from .env.example and restrict its permissions.
- [ ] Generate unique S3 credentials and the SSE-S3 key locally.
- [ ] Keep secrets out of Git and shell history; keep a protected offline recovery copy of the encryption key.
- [ ] Generate config/seaweedfs/s3.json locally and confirm Git ignores both it and .env.
- [ ] Run docker compose config --quiet.
- [ ] Review all published ports, network membership, volume paths, healthchecks, image tags, and command flags.

## Phase 5 — Controlled pilot deployment

- [ ] Configure DNS A record to the confirmed public IPv4.
- [ ] Confirm inbound TCP/80 and TCP/443 reach Traefik.
- [ ] Start the stack using the repository runbook, not ad hoc commands.
- [ ] Check service status and logs.
- [ ] Verify the HTTPS certificate from an external client.
- [ ] Confirm internal service ports are not publicly reachable.
- [ ] Run tests/sse-s3-smoke-test.sh against the deployed version.
- [ ] Confirm the S3 response reports ServerSideEncryption=AES256.
- [ ] Compare downloaded test bytes with the original test bytes.
- [ ] Test authentication, access denial, persistence after container restart, and service recovery after host reboot.

## Phase 6 — Independent backup and data-import gate

Do not copy original PDF/audio documents into AURA until all applicable checks pass:

- [ ] Define a backup destination independent of this VPS.
- [ ] Back up the data and required metadata/configuration according to the selected SeaweedFS release guidance.
- [ ] Protect the SSE-S3 key and prove the recovery process can retrieve it.
- [ ] Restore the backup into an isolated test environment.
- [ ] Verify restored objects can be decrypted/read and their hashes match.
- [ ] Record test date, scope, result, and recovery duration without recording secrets.
- [ ] Keep original source files until the independent restore test succeeds.

A snapshot or second directory on the same VPS is not an independent backup. A running container or successful upload is not proof of recoverability.

## Change log

- 2026-10-14: initial server profile and host bootstrap checklist created; reboot performed and kernel 7.0.0-38-generic verified. SSH-key setup, firewall review, S3 acceptance, Docker deployment and independent restore remain to be verified.
