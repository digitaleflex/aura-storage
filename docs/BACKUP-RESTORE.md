# Backup and Restore

The primary VPS is not a backup. A snapshot or second directory on the same VPS does not protect against provider loss or account compromise.

Before production:

- Choose an independent destination (ideally separate provider/account or another failure domain).
- Define retention, encryption, access controls, RPO and RTO.
- Back up all required data and metadata according to the selected SeaweedFS release's documented consistency procedure. Do not assume copying a live data directory is consistent.
- Protect backup credentials separately from production credentials.
- Monitor backup completion, age, size and destination capacity.
- Perform and record a full restore to an isolated environment.
- Document recovery order, integrity validation, endpoint/DNS cutover and rollback.

Restore acceptance: expected objects and metadata present; sampled checksums pass; authenticated S3 works; recovery time and data-loss window are recorded.
## Implementation (scripts/backup.sh)

The consistency question above is answered by **not copying SeaweedFS data
directories at all**: objects are read through the S3 API, like any client,
and the catalogue is dumped with `pg_dump`. A restore rebuilds SeaweedFS
volumes and filer metadata from scratch by writing the objects back through
S3. This works on any SeaweedFS release and does not need the original
`WEED_S3_SSE_KEK` (the target re-encrypts with its own key).

| Artefact | How | Where (under `BACKUP_REMOTE`, encrypted) |
|---|---|---|
| Catalogue | `pg_dump -Fc`, checked with `pg_restore -l` | `snapshots/<stamp>/catalogue.dump` |
| Audit trail | tar of the api audit volume | `snapshots/<stamp>/audit.tar.gz` |
| Manifest | sha256 of each artefact, catalogue counts, bucket list | `snapshots/<stamp>/manifest.json` |
| Objects | `rclone sync` per bucket | `objects/<bucket>/` |
| Displaced objects | changed/deleted since last run (`--backup-dir`) | `objects-history/<stamp>/<bucket>/` |

Everything is encrypted client-side with **rclone crypt** (file contents and
names) before it leaves the VPS. The destination is any rclone backend on
another provider/account.

**Order matters:** the catalogue is dumped first, then objects are synced. An
object purged between the two steps is still in `objects-history`, so every
row of the dump has its bytes in the backup.

**Keys to keep offline** (password manager + paper, not on the VPS):
`BACKUP_CRYPT_PASSWORD`, `BACKUP_CRYPT_PASSWORD2` (clear values), the
destination credentials, and — for the live stack only — `WEED_S3_SSE_KEK`.
Losing the crypt passwords makes every backup unreadable.

### Set up

```bash
cp config/backup.env.example config/backup.env && chmod 600 config/backup.env
# fill in the destination and the obscured crypt passwords
bash scripts/backup.sh          # first full run
bash scripts/restore-check.sh   # prove it can be read back
```

Schedule (root crontab on the VPS; RPO = 24h):

```cron
17 2 * * *  cd /opt/aura-storage && bash scripts/backup.sh >>/var/log/aura-backup.log 2>&1
47 3 1 * *  cd /opt/aura-storage && bash scripts/restore-check.sh --sample 50 >>/var/log/aura-restore-check.log 2>&1
```

Set `BACKUP_MONITOR_URL` to a dead-man switch so a missed run alerts.

### Restore test (non-destructive, monthly)

`scripts/restore-check.sh [STAMP] [--sample N]` restores the dump into a
throwaway PostgreSQL container with no network, checks the manifest hashes,
compares counts, and streams N random objects back from the backup to compare
their SHA-256 with the catalogue. Paste its output into a verification log.

### Disaster recovery

1. New host: follow `docs/REPRODUCIBLE-SETUP.md`, restore `.env` and
   `config/backup.env` from the offline copy (a **new** `WEED_S3_SSE_KEK` is fine).
2. `bash scripts/deploy.sh` — empty stack.
3. `bash scripts/restore.sh <STAMP> --confirm-empty-target` — refuses if the
   target catalogue already holds objects.
4. `docker compose restart api`, then `bash scripts/restore-check.sh <STAMP>`
   and a download through the app.

Users keep the passwords stored in the restored catalogue (the bootstrap admin
password from the new `.env` is not re-applied to an existing admin row).
