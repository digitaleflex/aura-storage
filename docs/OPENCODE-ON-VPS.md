# OpenCode Running Directly on the AURA VPS

## Scope

This runbook applies when OpenCode itself runs in an SSH session on the AURA pilot VPS. It is intentionally a preparation and inspection document: committing it does not execute commands, change the host, or authorize production operations.

## Important distinction

When OpenCode runs on the VPS, its shell commands execute as the operating-system account that launched it. Project-level OpenCode permissions are not an operating-system sandbox. A shell command may invoke scripts, interpreters, tools or Docker in ways that are not fully represented by a simple command-pattern deny rule. If the account has unrestricted `sudo` or Docker daemon access, repository instructions alone cannot protect the host.

Do not start or restart OpenCode as root. Do not use `sudo opencode`. Do not add the OpenCode account to the Docker group as a convenience; Docker daemon access is effectively root-equivalent.

## Phase 0 — Read-only discovery (no changes)

Run these commands manually in the existing SSH session, or have a trusted operator run them. They are intended for inspection only; do not paste secrets or full environment output into the agent.

```bash
whoami
id
pwd
git status --short --branch
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
opencode --version
command -v opencode
sudo -n -l
id -nG
docker --version
docker compose version
docker compose ps --format '{{.Name}} {{.State}} {{.Status}}'
df -hT
df -i
```

Safety notes:
- `sudo -n -l` lists sudo privileges without prompting for a password; it does not run an elevated command.
- Docker inspection is still access to a privileged control plane. Run only if this access is already authorized.
- Do not run `env`, `printenv`, `cat .env`, `docker inspect` without a redaction plan, or `docker compose config` in shared output; these can disclose credentials.
- Do not share public IPs, account identifiers, SSH details, tokens, environment values or full sensitive logs unnecessarily.
- Record the output locally in a private operator note; never commit host-specific secrets.

## Phase 1 — Safe development autonomy

Keep OpenCode running as a non-root user and work in a dedicated checkout/branch. Allow repository file edits, local builds and non-destructive tests. Keep production secrets unreadable to the coding agent wherever feasible. Use synthetic data and disposable databases for tests.

Do not assume `opencode.json` is sufficient protection. Its command rules are defense-in-depth only. A script, shell interpreter, alternate executable or Docker API may bypass simplistic command matching. Inspect the effective OpenCode version and configuration before relying on any setting.

## Phase 2 — Routine deployment without repeated prompts

Do not enable until the owner explicitly approves the deployment boundary and an operator verifies it on the host:

1. Identify the exact checkout path, deployment account, environment and permitted Compose services.
2. Confirm an independent backup and a successful restore test, including catalogue and objects.
3. Keep `.env`, generated S3 configuration, database credentials, backup credentials and `WEED_S3_SSE_KEK` out of the agent's read scope and logs.
4. Install a root-owned deployment wrapper outside the repository, writable only by root. It must accept no arbitrary shell or Compose arguments and must validate the expected checkout, approved branch/commit, clean/reviewed release state and required preflight checks.
5. Configure sudoers to permit only that exact wrapper, not `NOPASSWD: ALL`, unrestricted `bash`, an editor, arbitrary `docker`, or a script writable by the deploy account. Validate the sudoers file with `visudo -c` before applying any change.
6. The wrapper must serialize releases with a lock; verify disk/inodes, expected services, image/commit IDs and recovery artifacts; refuse unexpected state; deploy only the named AURA services; run postflight checks; and preserve logs with secrets redacted.
7. Test the wrapper in a disposable/staging environment first. Verify denial of arbitrary arguments, altered scripts, wrong branches, missing backup evidence and concurrent deployments.
8. Document the exact authorized routine deployment class. Within that narrow class, agents may execute the wrapper without asking for every release. All operations outside it remain blocked.

The wrapper and sudoers policy are host changes. This repository task does not install or activate them.

## Operations that remain approval-gated

- Any data/volume/backup deletion or overwrite.
- Database or object-store migration, re-encryption, SSE-S3 key rotation or credential rotation.
- SSH, sudoers, users/groups, firewall, provider network, Docker daemon or recovery access changes.
- Installing/upgrading host-wide packages, kernel changes or security-control changes.
- Deploying an unreviewed revision, deploying outside the approved service list, or bypassing failed health checks.
- Any operation for which target identity, backup status or rollback is unclear.

## Activation record

Before enabling unattended deployment, record in a private operator record:
- OpenCode version and actual runtime user.
- Exact repository checkout path and allowed branch/revision source.
- Approved target/environment and Compose service allowlist.
- Root-owned wrapper path and checksum.
- Exact sudoers command grant (no secret values).
- Backup/restore evidence and tested rollback revision.
- Preflight/postflight results and date.
- Owner approval for the bounded routine deployment class.

Do not place credentials, private keys, encryption keys, IP allowlists or full sudo output in this repository.
