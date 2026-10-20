# Agent Autonomy and Approval Policy

## Objective

Agents should complete normal engineering work without waiting for human confirmation at every step. Approval is a risk boundary, not a general workflow bottleneck. This policy applies to coding agents, orchestration agents, CI automation, and humans acting through automation.

## Autonomy classes

### A0 — Read and analyze (always allowed)
Inspect files, history, tests, CI output, configuration examples, sanitized logs and architecture. Produce plans, diagnostics, diffs and recommendations.

### A1 — Repository changes (autonomous)
Create, modify, move, rename and delete repository files; refactor code; add tests; update documentation; add compatible dependencies; update lockfiles; generate fixtures; run local builds and non-destructive tests. Preserve unrelated work and secrets. Keep changes scoped and reviewable.

### A2 — Development workflow (autonomous when credentials and repository policy permit)
Create task branches, commit changes on those branches, push task branches, open/update pull requests, inspect CI, fix failed checks, and request review. Never bypass branch protection, required reviews or required checks. Do not merge to protected main unless that exact authority has been explicitly delegated.

### A3 — Reversible environment changes (allowed only in isolated development environments)
Start/stop disposable local containers, create throwaway test databases, install project dependencies, run migrations against disposable databases, and use synthetic test objects. Confirm the target is isolated before executing. Do not reuse production credentials.

### A4 — Elevated-risk actions (explicit approval required)
Obtain approval before production/pilot deployment or restart with service impact; production schema/data migrations; deletion or overwrite of real objects, records, volumes or backups; encryption/key changes; firewall/SSH/host/network changes; opening public ports; privilege escalation or Docker daemon access changes; disabling security controls; public access policy changes; destructive/load tests against a live endpoint; importing originals; or irreversible operations.

## Approval contract

Before requesting approval, provide a compact change request containing:
- Target environment/resource and exact operation.
- Reason and expected outcome.
- Scope and expected service/data impact.
- Read-only preflight results.
- Backup and restore evidence, or a clear statement that none exists.
- Rollback/recovery steps and their limitations.
- Exact command or change to be authorized.

Wait for an unambiguous human approval of that action before executing it. Approval does not extend to unrelated actions or a broader scope. If the owner has explicitly pre-authorized a narrowly defined repeatable operation, follow only that documented scope.

## Stop conditions

Stop before the risky action if target identity is ambiguous, a backup is missing or unverified, the operation is irreversible, recovery access is unknown, the encryption key may be unavailable, current state contradicts the runbook, or the action would weaken a security boundary. Continue with safe diagnostics, prepare a plan, and report the blocker.

## Required safeguards

- Use least privilege and deny by default.
- Keep production credentials unavailable to ordinary coding agents.
- Prefer disposable environments, synthetic data, dry runs and read-only diagnostics.
- Require a dedicated branch and PR for code changes.
- Require independent review for security-sensitive code and high-impact infrastructure changes.
- Log the decision and verification evidence without logging secrets or customer content.
- Never bypass a gate by renaming an operation, splitting it into smaller commands, or claiming it is “just a test.”

## AURA-specific hard gates

The real pilot must not receive original files until HTTPS, authentication/authorization, SSE-S3 AES256 reporting, byte/hash integrity, persistence and an independent backup restore test have passed and evidence is recorded. The SSE-S3 key must have a protected offline recovery copy. Never manually remove SeaweedFS data directories or Docker volumes to free space.

## Policy limitation

This document is an instruction contract, not an enforcement mechanism by itself. Enforce critical boundaries through separate credentials, environment isolation, branch protections, required reviews, CI checks, host access controls and deployment permissions. An agent that has unrestricted production credentials can technically bypass a prose-only rule.