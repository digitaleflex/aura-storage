# Agent Definition of Done

A task is complete only when every applicable item below is satisfied or explicitly marked blocked with evidence.

## Scope and implementation
- [ ] Acceptance criteria are met, or remaining gaps are named.
- [ ] Changes are limited to the task; unrelated user work is preserved.
- [ ] Existing architecture, API contracts and authorization policy are respected.
- [ ] No unsupported feature or environment state is described as implemented.
- [ ] Error paths, security implications and compatibility have been considered.

## Tests and quality
- [ ] Relevant unit/integration/E2E tests were run where available.
- [ ] Regression tests were added or a reason is documented.
- [ ] Build/type checks were run when relevant.
- [ ] Test commands and results are accurate; skipped checks have reasons.
- [ ] Full diff was inspected and `git diff --check` passed or its failure is explained.
- [ ] Tests were not removed or weakened merely to obtain a green result.

## Security and data protection
- [ ] No secrets, private keys, real environment files, user files or backups were added.
- [ ] Authorization is enforced server-side and follows least privilege.
- [ ] No real data was deleted, overwritten, imported or migrated without required approval.
- [ ] Dangerous operations have a documented recovery/rollback path.
- [ ] No production-readiness claim exceeds the available evidence.

## Documentation and delivery
- [ ] Relevant documentation/config examples are updated.
- [ ] Important architectural changes have a decision record where appropriate.
- [ ] Branch/commit/PR details are provided when applicable.
- [ ] Remaining risks, blockers and required human decisions are explicit.
- [ ] The next recommended action is concrete and prioritized.

## Production acceptance is separate
Code completion, CI success, deployment success and production acceptance are different states. Production acceptance requires the gates in `docs/DEPLOYMENT.md`, `docs/SECURITY.md`, `docs/BACKUP-RESTORE.md` and the verification log to be evidenced for the actual target environment.