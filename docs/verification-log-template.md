# AURA deployment verification log

> Keep this log free of credentials, private keys, SSE-S3 keys, full environment dumps, customer filenames and document contents. Prefer storing this file privately or committing only sanitized test outcomes.

## Run metadata

- Date/time (UTC or timezone stated):
- Operator:
- Repository branch:
- Git commit:
- VPS/provider inventory reference (private record, not secrets):
- Maintenance/deployment purpose:

## Host baseline

- OS/release:
- Running kernel:
- Reboot required before/after:
- SSH key login verified in second session:
- Sudo verified:
- Recovery console tested/available:
- Disk allocation reconciled with provider:
- Firewall manager and policy reviewed:
- WireGuard enabled? If yes, handshake and admin access verified:
- Docker/Compose versions:
- Docker active after reboot:

## Application validation

- Compose config validation:
- Image tags/release notes reviewed:
- DNS A/AAAA validated:
- HTTPS certificate validated externally:
- Public listening ports reviewed:
- Internal SeaweedFS ports not publicly reachable:
- S3 unauthenticated request denied:
- Authenticated test upload/download:
- SSE-S3 response reports AES256:
- Downloaded bytes/hash match:
- Persistence after container restart:
- Persistence after host reboot:
- Logs reviewed for errors/secrets:

## Backup and recovery

- Backup destination independent of VPS:
- Backup method/release-specific consistency guidance:
- SSE-S3 key recovery verified (do not record the key):
- Restore environment isolated:
- Restored objects readable/decryptable:
- Restored object hashes match:
- Restore duration:
- Outcome and corrective actions:

## Decision

- [ ] Accepted for controlled test only
- [ ] Accepted for production import
- [ ] Rejected / blocked

Outstanding blockers:
Next actions and owner:
Approval to migrate originals (must be explicit):
