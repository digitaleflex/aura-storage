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

## Scheduled SeaweedFS vacuum

Deleted objects and abandoned multipart parts free logical space immediately but
leave bytes in the `.dat` files until a volume vacuum. Run the idempotent helper
off-peak (03:00), after a backup exists:

```cron
0 3 * * * cd /srv/aura-storage && ./scripts/seaweedfs-vacuum.sh >> /var/log/aura-vacuum.log 2>&1
```

The cluster is locked for the operation and always unlocked afterwards.
`SEAWEED_VACUUM_GARBAGE_THRESHOLD` defaults to 0.3: volumes below 30% garbage are
left alone, so a normal night is a no-op. Verify with `volume.list` that
`DeletedBytes` does not keep growing. New volumes use the master setting
`SEAWEED_VOLUME_SIZE_LIMIT_MB` (10 GiB by default); existing volumes are unchanged.

## HTTP/3 and media caching

Traefik publishes UDP/443 and enables HTTP/3 on `websecure`. On the current
pilot UFW is disabled (`ENABLED=no`), so nothing blocks `443/udp`; if UFW is
ever enabled, allow it explicitly with `sudo ufw allow 443/udp`. There is
deliberately **no buffering middleware** on the
S3 router: presigned PUT/GET bodies stream straight to SeaweedFS. The S3 router
only carries HSTS, and nginx gzip types exclude `audio/*` and `video/*`.

AURA's media URLs are **mutable by design** (`/m/<slug>` survives content
replacement, grants are revocable), so they must keep `no-store`/short-lived
redirects. `Cache-Control: public, max-age=31536000, immutable` belongs only on
content-hashed assets (already done for `/assets/`) or on a CDN/course-site
layer that owns its own immutable URLs. Do not add it to `/m/` or `/a/`.

Cloudflare: the two existing DNS records (`aura-storage.` and
`public.aura-storage.`) are currently **DNS-only** (`proxied=false`). Do not
switch the S3 upload domain to orange-cloud without verifying the plan's upload
size limit: presigned `PUT` bodies of 50 GiB would traverse the CDN and most
free/low-cost plans cap request bodies far below that. If a CDN is needed for
playback, use a **dedicated media hostname** with a verified plan, keep the S3
upload hostname grey, and test Range requests through the CDN before rollout.

## Changes

Pin images and review release notes. Back up required data/metadata before risky upgrades. Test with representative content. Never run destructive cleanup without explicit target validation and a current independent backup.