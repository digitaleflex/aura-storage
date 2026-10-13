# Security Baseline

- Use SSH keys and confirm key access before disabling password login.
- Restrict SSH source addresses when practical.
- Apply OS security updates and configure unattended security updates.
- Use default-deny inbound firewall rules and allow only required ports.
- Keep SeaweedFS master, volume, filer, metrics and admin interfaces private.
- Expose S3 only through HTTPS.
- Generate credentials outside Git and store local config with restrictive permissions.
- Use different least-privilege identities per app/environment; avoid Admin for normal app traffic.
- Pin reviewed container image versions; inspect release notes before upgrades.
- Restrict Docker socket access; Docker group membership is effectively root-equivalent.
- Never commit `.env`, keys, certificates, production config, customer data or backups.
- Validate S3 policy syntax/actions against the exact selected SeaweedFS release.
- Document credential revocation, secret rotation, disk-full response, backup restore and rollback.