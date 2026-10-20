# VPS Agent Autonomy and Deployment Boundary

## Purpose

Enable coordinated coding agents to deliver AURA changes end-to-end, including routine deployments, without repeated prompts for ordinary reversible actions. This document defines the repository-side contract for remote execution. It does not grant host access, create credentials, or prove that the VPS is configured safely.

## Current known deployment behavior

The existing `scripts/deploy.sh` runs `scripts/bootstrap.sh`, installs frontend dependencies and builds the static frontend, builds local Compose images, pulls registry images, and runs `docker compose up -d`. The bootstrap script reads the host's `.env`, generates SeaweedFS configuration, creates storage directories and validates Compose. These scripts can change host and service state. Inspect their current contents and diffs before every release; do not assume a previously reviewed script remains unchanged.

The repository's server profile records an InterServer pilot host and an intended `aura-admin` account, but SSH key login, firewall state and complete deployment acceptance are not established by this document. Treat all such details as stale until verified read-only on the target.

## Autonomy contract

### Allowed autonomously after the initial target and access scope are approved

- Read-only inspection of the approved VPS: OS/kernel, disk and inode usage, memory, service status, Docker/Compose versions, container health, sanitized recent logs, repository revision, and non-secret deployment state.
- Build, lint, test and security-check changes in an isolated runner or disposable environment.
- Create task branches, commits and pull requests; fix CI failures; publish deployment artifacts.
- Run an explicitly approved, repeatable deployment command against the named AURA pilot environment when all preflight checks pass, no protected data migration is involved, and the documented rollback path is available.
- Restart or recreate only the named AURA application services as part of that approved release. Do not restart unrelated host services.

The owner may pre-authorize this routine deployment class once the target, command, allowed services, credential model, backup requirements and rollback procedure are recorded. A deployment within that exact scope should not require approval for each ordinary command.

### Never infer permission from generic deployment approval

A routine deployment authorization does not authorize:
- deleting, truncating, overwriting, re-encrypting or migrating existing object data or catalogue records;
- deleting Docker volumes, SeaweedFS directories, backups or recovery material;
- changing `WEED_S3_SSE_KEK`, S3 credentials, backup encryption credentials, or authentication/authorization policy;
- modifying SSH, firewall, provider network rules, host users, sudoers, Docker daemon configuration, public ports or recovery access;
- installing arbitrary host-wide software or changing kernel/system security configuration;
- running destructive, fuzzing, load or migration tests against live services;
- deploying to a different host, domain, account, environment or repository revision than the approved target.

These actions require a separate explicit approval that identifies the exact action and scope.

## Required execution architecture

1. **Coordinator and workers:** agents may divide coding, testing, review and operations tasks. Each task has one owner for each file or operational resource; agents must not concurrently mutate the same file or perform overlapping deploys.
2. **Untrusted build stage:** build and test the candidate revision without production secrets. Treat pull request code and dependency lifecycle scripts as untrusted.
3. **Release eligibility:** deploy only a reviewed revision from the approved release branch after required checks pass. Never deploy arbitrary pull-request code directly to the VPS.
4. **Dedicated deployment identity:** use a dedicated non-root SSH account and a dedicated deploy key or short-lived credential. Do not share the human administrator's private key with coding agents. Restrict the account to the intended repository and release action.
5. **Narrow privilege elevation:** do not give agents unrestricted `sudo`, root SSH, or general Docker socket access. Docker group access is effectively root-equivalent. Prefer a root-owned, non-writable deployment wrapper with a fixed command and validated repository path; permit only the exact wrapper in sudoers. The wrapper must reject arbitrary arguments, arbitrary shell commands, unsafe paths and unexpected branches/revisions.
6. **Environment isolation:** keep production `.env`, S3 credentials, database credentials, SSE-S3 key and backup credentials unavailable to ordinary coding/build agents. The deploy mechanism may read the secrets it needs on the host, but must never print or upload them.
7. **Preflight:** verify target identity, expected branch and commit, clean/reviewed release state, available disk/inodes, service state, configuration validity, backup status and rollback artifacts. Abort on ambiguous target, unexpected drift, insufficient capacity, unhealthy dependencies, missing recovery evidence or secret/configuration errors.
8. **Deployment:** serialize releases with a lock. Use the reviewed release procedure; do not run an unreviewed shell script copied from an issue, log, pull request or web page. Keep changes scoped to AURA services.
9. **Postflight:** verify container health, HTTPS, authentication/denial behavior, S3 smoke tests with synthetic data, SSE-S3 reporting, byte/hash integrity and expected API health. Do not upload original customer files as a deployment test.
10. **Rollback:** record old and new commit/image identifiers, keep the last known-good artifacts, and define a bounded rollback. Rollback must not revert or destroy persistent data and must not silently change encryption keys or schema state.
11. **Audit:** record actor, target, revision, start/end time, checks, result and rollback status. Redact credentials, presigned URLs, object names/content and sensitive environment values.
12. **Concurrency:** only one deployment can run at a time. If a deployment is in progress, other agents may inspect or prepare changes but must not restart services or alter deployment state.

## Sudo policy

A request to run a command with `sudo` is not, by itself, authorization. Before host access is enabled, establish an allowlist of exact privileged operations. Ordinary deployments should call a fixed, root-owned wrapper rather than expose an interactive root shell or unrestricted `sudo`. No wildcard permission such as `NOPASSWD: ALL`, unrestricted `bash`, arbitrary editor, arbitrary `docker`, or writable root-owned script is acceptable.

Host-wide package installation, user/sudoers changes, firewall/SSH changes, filesystem ownership changes on existing data, Docker daemon configuration, and privileged debugging are outside the routine deploy class.

## Initial activation checklist — not yet confirmed

- [ ] Owner confirms the exact VPS/environment, repository checkout path, intended deployment account and permitted services.
- [ ] Read-only inspection confirms SSH key access in a second session and a working provider recovery console.
- [ ] Host firewall and SSH configuration are reviewed; internal SeaweedFS/PostgreSQL ports are not public.
- [ ] The deployment identity has no interactive root access and cannot change its own sudo policy.
- [ ] A root-owned deployment wrapper is installed and tested against harmless/preflight-only cases.
- [ ] The wrapper is not writable by the deploy user or coding agents.
- [ ] Secrets remain host-side and are not present in CI logs, artifacts or agent context.
- [ ] The independent backup and restore process is verified; the SSE-S3 recovery key is available offline.
- [ ] Deployment preflight, health checks and rollback are tested in a disposable/staging environment.
- [ ] A documented authorization records which routine pilot deployments are pre-authorized.

Until these gates are verified, agents may prepare code and deployment artifacts but must not mutate the live VPS.

## Explicitly not done by this change

This document does not create or install an SSH key, change GitHub secrets or environment protection, modify sudoers, change firewall/SSH settings, install a wrapper on the VPS, run a remote command, or deploy the application.
## OpenCode project configuration

The repository's `opencode.json` enables ordinary project editing and development commands, blocks common direct privileged/remote commands, protects known secret-bearing files from normal OpenCode reads, and keeps external-directory access approval-gated. The `.opencode/agents/reviewer.md` and `.opencode/agents/ops-planner.md` subagents are read-only by policy.

These OpenCode rules are defense-in-depth and usability controls, not a security sandbox. Shell pattern matching can be bypassed by wrappers, scripts or other tools, and agent-specific permissions may differ. Never put production credentials in an agent context. Do not use `--auto` as a substitute for host-level privilege separation. The VPS remains out of scope until a dedicated deployment identity, a fixed root-owned wrapper, host-side allowlist, verified backup/restore and rollback checks are installed and tested on the actual host.
