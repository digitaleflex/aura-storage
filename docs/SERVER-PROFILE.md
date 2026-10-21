# VPS server profile — AURA Storage

> **Last verified:** 2026-10-14  
> **Status:** the AURA stack is deployed on this host with partial, dated verification evidence (bootstrap OK, live PostgreSQL migration, SSE-S3 smoke PASS — see the 2026-10-15 and 2026-10-16 verification logs linked from `README.md`). The host has **not** yet passed AURA deployment acceptance tests.

This document records operational facts observed on the AURA Storage pilot VPS. It is not a secret store. Do not add passwords, private SSH keys, API tokens, environment values, encryption keys, or recovery codes here.

## 1. Provider and service

| Field | Value |
|---|---|
| Provider | InterServer |
| VPS identifier | 3718250 |
| Hostname | vps3718250.trouble-free.net |
| Public IPv4 | 153.75.248.230 |
| Product/plan shown in provider panel | KVM Storage Ubuntu 3 Slices |
| Monthly price recorded at provisioning | USD $9/month |
| Next invoice recorded at provisioning | 2026-11-14 |
| Provider host node | Storage-kvm5600 |
| Service status in panel | Active |
| Intended workload | AURA Storage pilot: Docker Compose, Traefik, SeaweedFS; PostgreSQL and the management API are implemented in the stack and deployed locally on this VPS, but not accepted |

Billing and provider plan details were copied from the account information available at provisioning. Re-check the provider panel before renewals or capacity decisions.

## 2. Observed system resources

Values below were observed from the guest OS, not inferred from the commercial plan.

| Resource | Observed value | Notes |
|---|---:|---|
| CPU | 2 logical CPUs | Reported by nproc |
| Memory | 5.3 GiB total | free -h output |
| Memory available at last check | 4.7 GiB | Before the AURA stack is deployed |
| Swap | 1.0 GiB | Unused at last check |
| Root filesystem | 2.9 TiB total | Device /dev/sda4; approximately 2.8 TiB available at last check |
| Boot filesystem | 974 MiB total | Device /dev/sda2; 643 MiB available at last check |
| Network interface | eth0 | Reported UP during initial inspection |
| IPv4 address | 153.75.248.230/26 | Observed on eth0 |

**Capacity caveat:** the guest reports a 2.9 TiB root filesystem, which is unusually large relative to many small VPS plans. Confirm the allocated storage and any provider-specific limits in the InterServer panel before treating all reported capacity as guaranteed usable capacity.

## 3. Operating system and patch state

| Field | Last observed value |
|---|---|
| Distribution | Ubuntu 26.04 LTS |
| Codename | resolute |
| Kernel currently running at last check | 7.0.0-38-generic (verified live 2026-10-14) |
| New kernel installed | 7.0.0-38-generic |
| Reboot status | **Reboot completed and verified 2026-10-14; no reboot marker present** |
| Package upgrade | APT upgrade reported 163 packages upgraded, 7 installed, 0 removed, and 5 held back due to phased updates |
| Standard LTS security updates reported by APT | 122 |
| APT download size reported | 390 MB |
| APT additional disk space reported | 322 MB |

After reboot, verify with:

    uname -r
    systemctl is-active ssh

Expected kernel after a successful reboot: 7.0.0-38-generic. Verified live on 2026-10-14
(`uname -r` → 7.0.0-38-generic, no `/var/run/reboot-required` marker).

## 4. Administrative access

| Field | Current recorded state |
|---|---|
| Intended day-to-day administrator | aura-admin |
| Administrative elevation | Member of sudo; sudo id -u returned 0 |
| Sudo policy file | /etc/sudoers.d/90-aura-admin |
| Sudo authentication cache | timestamp_timeout=30 |
| Sudo policy validation | visudo -c reported /etc/sudoers: parsed OK |
| Root access | Root SSH login has been used during bootstrap; do not disable until key-based administrator access is tested |
| SSH service | Active and listening on TCP/22 during last observation |
| SSH activation | ssh.service appeared disabled but was active through ssh.socket socket activation |
| SSH key authentication | Not yet confirmed |
| Firewall policy | Not yet confirmed |
| Non-root SSH login after reboot | Not yet confirmed |

The administrator's password must be stored only in an approved password manager. Never store it in this repository or in shell history.

### Access validation checklist

- [ ] Reboot completed and expected kernel verified.
- [ ] Open a fresh SSH session as aura-admin.
- [ ] Confirm whoami prints aura-admin.
- [ ] Confirm sudo -v and sudo id -u succeed.
- [ ] Create an SSH key on the trusted client and install only its public key on the VPS.
- [ ] Test key-based login in a separate session before changing any SSH policy.
- [ ] Review SSH settings and firewall rules before disabling root/password-based SSH.
- [ ] Keep the provider console/recovery path available during hardening.

## 5. Security observations

During the initial SSH inspection, logs showed inbound attempts for an invalid ubuntu account from an external IP. Such attempts are common on publicly reachable SSH services and do not, by themselves, prove compromise. Continue monitoring authentication logs and investigate any successful login that cannot be attributed to an authorized administrator.

Do not expose SeaweedFS master, volume, filer/admin, metrics, or other internal ports publicly. The intended public ingress is Traefik on TCP/80 and TCP/443; SSH access must be deliberately secured.

## 6. AURA deployment baseline

The VPS hosts the pilot stack. Dated verification logs (2026-10-15, 2026-10-16; linked from `README.md`) record partial progress, but these items are **not yet all verified as complete**:

- [x] Docker Engine and Docker Compose plugin installed and running (Engine 29.9.0 / Compose v5.6.0).
- [ ] Host firewall and provider firewall reviewed and tested.
- [ ] SSH public-key login tested for aura-admin.
- [ ] DNS records and HTTPS certificate issuance verified externally. (Partially: A records and Let's Encrypt certificates validated for `app.aura-storage.eurinhash.com` and `aura-storage.eurinhash.com` on 2026-10-15.)
- [x] Compose configuration validated on the real host (`docker compose config --quiet` during bootstrap).
- [x] SeaweedFS release, flags, S3 policy, and SSE-S3 behavior validated. (SSE-S3 smoke PASS 2026-10-15 and 2026-10-16 on SeaweedFS 4.48.)
- [ ] S3 access controls and private internal networking tested. (Partially: unauthenticated S3 request denied 403; internal ports confirmed only via the listening-port scan, not probed from outside.)
- [ ] Data persistence tested across container recreation and host reboot. (Partially: the API was recreated during deploys and returned healthy; host reboot not tested.)
- [ ] Independent backup configured outside this VPS.
- [ ] Backup restoration tested successfully.
- [x] End-to-end smoke test confirms encrypted-object response and byte-for-byte download integrity.

**Do not import the original PDF/audio files until encryption, access control, persistence, and an independent backup restoration have all passed.** Keep the original files until that restoration test succeeds.

## 7. Useful diagnostic commands

Run these as aura-admin, using sudo where required:

    # Identity and elevation
    whoami
    id
    sudo -v
    sudo id -u

    # OS and kernel
    cat /etc/os-release
    uname -r
    test -f /var/run/reboot-required && cat /var/run/reboot-required || echo "No reboot required"

    # CPU, memory and filesystems
    nproc
    free -h
    df -h / /boot
    ip -brief address

    # SSH state
    systemctl status ssh --no-pager
    systemctl status ssh.socket --no-pager
    sudo sshd -t

Record new observations with a date. Never paste passwords, private keys, access tokens, encryption keys, or full secret-bearing environment output into issue comments or documentation.
