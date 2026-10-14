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

## Network and throughput validation (not yet executed)

- Safety gate passed before any host modification:
- SSH key login verified in a second independent session:
- Provider recovery console available:
- Baseline access network/device and timestamp:
- Baseline download/upload/idle latency (three trials):
- Controlled VPS path test authorized and scoped:
- AURA synthetic upload median / range:
- AURA synthetic download median / range:
- WireGuard off/on Internet download median / range:
- Device-to-device local / remote median / range:
- DNS and IPv6 leak checks:
- SHA-256 integrity checks:
- VPS CPU/memory/provider transfer usage before and after:
- AURA impact observed:
- Test files removed and temporary listeners/rules removed:
- Decision and blockers:

> Do not run tests or change the VPS merely to fill this template. Use synthetic, non-sensitive files; record sanitized results only.

## SSH access verification

- Provider recovery console available and tested:
- Hostname/IP reconfirmed in provider panel:
- Actual SSH port/listener confirmed:
- Main PC SSH public-key SHA-256 fingerprint (fingerprint only):
- Main PC key login verified in second independent session:
- `sudo -v` and `sudo id -u` verified:
- Separate Linux-client key tested, if applicable:
- iPhone SSH client/key tested, if applicable:
- Android SSH client/key tested, if applicable:
- Lost-device/key revocation procedure reviewed:
- SSH socket/service activation and firewall reviewed:

> Never enter private-key contents, passwords or WireGuard private keys in this log or GitHub.
