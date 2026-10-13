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

Restore acceptance: expected objects and metadata present; sampled checksums pass; authenticated S3 works; recovery time and data-loss window are recorded. Implement a backup script only after the exact supported SeaweedFS consistency mechanism is confirmed.