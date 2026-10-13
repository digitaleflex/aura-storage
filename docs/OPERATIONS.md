# Operations

## Routine checks

- Container status and restart count.
- Host CPU, RAM, disk capacity, inodes and I/O.
- S3 health and upload/download failures.
- Monthly transfer usage against provider quota.
- Backup freshness and last successful restore test.
- TLS expiry, OS security updates and image versions.
- Failed authentication and unusual administrative actions.

## Capacity

Investigate at 70% filesystem use and plan remediation before 80%; tune these thresholds to growth and expansion lead time. Reserve room for logs, metadata and temporary upload activity.

## Changes

Pin images and review release notes. Back up required data/metadata before risky upgrades. Test with representative content. Never run destructive cleanup without explicit target validation and a current independent backup.