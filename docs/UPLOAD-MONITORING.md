# Upload monitoring — catching what the API cannot see

The API signs an upload; the browser sends the bytes **straight to the S3 gateway**.
That design is what makes bulk transfers cheap, but it creates a blind spot: when
Traefik closes a request at `respondingTimeouts.readTimeout`, the resulting HTTP **499
"Client Closed Request"** never reaches the AURA API. It exists only in the proxy's
access log.

Consequence, measured on 2026-10-25
([verification log](verification-log-2026-10-25-multipart-proxy-4.48.md)): a monitor
that pages on 5xx alone is blind to this failure mode, because 499 is not a 5xx. The
browser surfaces it as a generic network error.

`scripts/upload-health.sh` is the watcher for that gap. It has no database dependency
and needs no admin token, which also makes it independent of the machine-identity
problem recorded for `scripts/reconcile-cron.sh`.

## What it does

It reads the Traefik access log — from the running container by default, or from a saved
file with `--file` — and keeps **only PUT/POST requests routed to the S3 router**.

Filtering matters. This host receives a constant stream of internet scanner traffic
(`GET /autodiscover/autodiscover.xml`, `GET /version`, `GET /`). Those lines vastly
outnumber real uploads and would bury the signal, so the router and method are part of
the check rather than a display preference.

## Classes and thresholds

| Observation | Class | Meaning |
|---|---|---|
| `PUT/POST` → **499** | critical | The proxy cut the body at `readTimeout`. |
| `PUT/POST` → **5xx** | critical | The request reached the proxy and failed there. |
| `2xx` but duration **≥ `readTimeout`** | critical | A success slower than the enforced deadline cannot happen while that deadline is enforced: the setting changed under a stale log, or the number this tool warns on is wrong. Refuses to guess. |
| `2xx` and duration **≥ 80 % of `readTimeout`** | warning | The upload nearly ran out of time. Reduce the part size or raise the deadline. |
| anything else | ignored | |

`READ_TIMEOUT_S` (default `7200`) must stay equal to the entrypoint's
`respondingTimeouts.readTimeout` in `docker-compose.yml`. It is read from the environment
on purpose: if the deadline is retuned, the threshold follows instead of silently warning
at the wrong value.

## Exit codes

Cron, systemd and any wrapper act on the exit status, not on the text.

| Code | Meaning |
|---|---|
| `0` | healthy (or no upload traffic in the window) |
| `1` | warning only — an upload is close to the deadline |
| `2` | critical — an upload was cut or failed at the proxy |
| `3` | the check itself could not run (docker unavailable, unreadable file) |

`3` is deliberately distinct from `2`: a broken check must never look like a storage
incident, and must never look healthy either.

## Usage

```bash
scripts/upload-health.sh                 # last 24h from the running stack
scripts/upload-health.sh --since 2h
scripts/upload-health.sh --file /tmp/traefik.log
scripts/upload-health.sh --json          # one JSON object on stdout, for a scraper
```

## Wiring

Cron (root on the VPS) — the exit code becomes a log line `/usr/bin/logger` can ship:

```cron
17 * * * * cd /opt/aura-storage && READ_TIMEOUT_S=7200 \
  ./scripts/upload-health.sh --since 1h 2>&1 | /usr/bin/logger -t aura-upload || \
  /usr/bin/logger -t aura-upload -p user.err "upload-health exited non-zero"
```

Systemd timer, if you prefer explicit units:

```ini
# /etc/systemd/system/aura-upload-health.service
[Service]
Type=oneshot
WorkingDirectory=/opt/aura-storage
Environment=READ_TIMEOUT_S=7200
ExecStart=/opt/aura-storage/scripts/upload-health.sh --since 1h
```

```ini
# /etc/systemd/system/aura-upload-health.timer
[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

`Persistent=true` matters: a laptop-sized VPS that reboots should not skip the hourly
check silently.

## What this does NOT prove

- **No client-side signal.** A user whose upload dies sees a network error; this tool
  only observes the proxy's view. It cannot tell you *which* user, beyond the client IP.
- **No per-request identity.** `accesslog.fields.queryparameters.defaultmode=drop` is set
  in `docker-compose.yml`, so `partNumber` and `uploadId` are not logged. The path in the
  report identifies the object, not the upload session.
- **No proof of data loss.** A cut part is retried by the client (`classifyHttp` treats
  499 as retryable since the 2026-10-26 fix), so a 499 means *wasted bandwidth and a
  delay*, not a corrupt object.
- **A bounded window.** `docker logs` only holds what Docker retained, and the log starts
  over when the container is recreated. A `--since 24h` request can therefore cover much
  less than 24 hours. Ship the logs off-host if you need real history.
- **No storage-side truth.** Disk pressure, scrubber results and object integrity live in
  `/api/v1/admin/integrity` and the scrubber, not here.

## Why not Prometheus

There is no metrics backend in this stack, and adding one to scrape a single VPS would
cost more than it returns. Traefik's access log already carries status and duration per
request. If metrics are ever added, enable `--metrics.prometheus` on Traefik and alert on
the same four conditions; keep this script as the offline-verifiable fallback.

## Verification

`tests/test-upload-health.sh` feeds synthetic access-log lines — a 499, a 502, a near-
deadline success, a fast success, scanner noise and a non-S3 router — and asserts the exit
codes and messages. It needs no Docker and no network, so it runs in CI.
