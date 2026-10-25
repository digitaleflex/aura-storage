# AURA verification log — 2026-10-25 (multipart part PUT through the edge proxy, gate item 6)

> Instance of [verification-log-template.md](verification-log-template.md). Contains no
> credentials, private keys, SSE-S3 keys, full environment dumps, customer filenames or
> document contents. The S3 credentials and bucket were generated for a throwaway stack
> and the stack — containers, network and workdir — was removed at the end of the run
> (see `D`); presigned query parameters are redacted in the transcript and dropped from
> the proxy access log.

## Run metadata

- Date: 2026-10-25 (UTC). The run identifier embeds `1792966551`, i.e. 22:15:51 UTC;
  the first Traefik access-log line reads `22:15:57`, the last filer line `22:18:19`.
- Operator: `aura-admin` (AI-assisted session; this file is a documentation-only record).
- Repository: `aura-storage`, HEAD `3922cd4` at the time of writing. The working tree
  was dirty at documentation time; the captured output does not record the tree state
  at run time.
- Purpose: close **gate item 6** of the multipart plan
  ([MULTIPART-UPLOAD-PLAN.md](MULTIPART-UPLOAD-PLAN.md)): presigned part PUTs through
  Traefik, and the largest part that fits the configured `readTimeout` at the slowest
  supported client rate.
- Artifacts: `chrislusf/seaweedfs:4.48` (no `:latest`) and `traefik:v3.7.14`. The
  harness printed the resolved images:
  - SeaweedFS `sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`
    (`created 2026-09-28T18:41:21Z`);
  - Traefik `sha256:575fa15b135078fe5e50aa847987d96dbddd7b093c172429618404df73f3fa7c`
    (`created 2026-10-06T17:48:04Z`).
- Harness: `tests/multipart-proxy-4.48.sh` + `tests/multipart_proxy_client.py`.

## Exact command used

```bash
sg docker -c 'bash tests/multipart-proxy-4.48.sh'
```

That invocation is the one documented in the harness header; the preserved transcript
starts after it and does not echo `argv`. No environment override was used: the harness
defaults applied, `SLOW_RATE_KBPS=64`, `PART_BYTES=5242880`, `TRAEFIK_IMAGE=traefik:v3.7.14`.
The harness starts the isolated stack itself, generates the throwaway S3 credentials and
bucket, and deletes the stack and workdir in its `trap`. No secret is passed on a command
line or written to the transcript.

Capture note: the preserved artifact is the full harness stdout — 179 lines, from the
run header through the `A`/`B`/`C` probes, the diagnostics and the `D` teardown proof to
`kept transcript: /tmp/opencode/multipart-proxy-4-48-1792966551-2481976.log`. Evidence
lines are quoted verbatim below where the exact values matter.

## Environment and isolation

- Image pinned: `chrislusf/seaweedfs:4.48`; proxy pinned `traefik:v3.7.14`.
- Topology: master + volume + filer/S3 gateway, each its own container
  (`multipart-proxy-4-48-master`, `-volume`, `-filer`), plus **two** Traefik instances
  in front of the same gateway — `multipart-proxy-4-48-traefik` and
  `multipart-proxy-4-48-traefik-default` — on their own Docker network
  (`multipart-proxy-4-48-net`), data under
  `/tmp/opencode/multipart-proxy-4-48-1792966551-2481976`.
- Proxy configuration as actually passed to `docker` (quoted from the transcript):

  ```text
  good args:    --entrypoints.websecure.address=:443
                --entrypoints.websecure.transport.respondingTimeouts.readTimeout=7200s
                --providers.file.filename=/etc/traefik/dynamic.yml --accesslog=true
                --accesslog.fields.queryparameters.defaultmode=drop --log.level=INFO
  default args: --entrypoints.websecure.address=:443
                --providers.file.filename=/etc/traefik/dynamic.yml --accesslog=true
                --accesslog.fields.queryparameters.defaultmode=drop --log.level=INFO
  ```

  The second proxy deliberately omits the `readTimeout` override, so it runs Traefik's
  default **60s**. Both route `Host(`s3.test`)` to the SeaweedFS S3 gateway.
- Host routing proven before the uploads: `Host(s3.test) -> routed`,
  `Host(other.test) -> HTTP 404`.
- Signed-host integrity: the harness installs a `s3.test -> 127.0.0.1` DNS override, so
  the URL and the `Host` header keep `s3.test:<port>` and the SigV4 signature covers the
  same host the proxy routes on. The endpoints were `http://s3.test:32790` (7200s proxy)
  and `http://s3.test:32791` (default-60s proxy); a direct `127.0.0.1:32789` gateway
  endpoint was used for readiness only (HTTP 403 on `/`).
- Exposure: single ephemeral host port per service bound to `127.0.0.1`; plain HTTP, no
  TLS termination, no certificate, no HTTP/2.
- Credentials: generated per run by the harness, throwaway; the presigned URLs' query
  parameters are dropped from the access log by
  `--accesslog.fields.queryparameters.defaultmode=drop`.
- Pilot isolation: the harness never creates, inspects or modifies the pilot stack
  (`aura-001-*` / compose project `aura-storage`) and never reads the pilot `.env`.
- Teardown (`D`): no `multipart-proxy-4-48-*` containers remain, no
  `multipart-proxy-4-48-*` networks remain, the workdir
  `/tmp/opencode/multipart-proxy-4-48-1792966551-2481976` was removed, and the pilot
  compose-project container set is byte-identical before and after (same nine
  containers with the same IDs, `aura-001-api` `6325550ef1f6` … `aura-001-volume`
  `12a76454e852`).

## Results

Summary as printed:

```text
=== SUMMARY: failures=0 blocking_unknowns=0 other_unknowns=0 passes=10 ===
client exit code: 0 (0 = A/B/C passed)
```

The ten counted assertions are the client's; the four `D` checks print after the client
exits and are the harness's own isolation proof, not part of `passes=10`.

| Assertion | What is claimed | Status | Evidence (from the captured output) |
|---|---|---|---|
| PREFLIGHT | A normal-speed 5 MiB part PUT through the proxy succeeds, so the stack is writable before the slow probe | **PASS** | `elapsed=0.117s ETag='"ba8c3fac0e224c9b79a8e74bebd54654"' local_md5=ba8c3fac0e224c9b79a8e74bebd54654 HTTP=200` |
| A | A client-paced slow 5 MiB part PUT through the 7200s proxy completes, and the ETag is the MD5 of the exact bytes sent | **PASS** | `status=200 elapsed=80.008s sent=5242880/5242880 early_response=False rate=64KiB/s`; `etag='"006a88ed7d5826af90d38dba4666fd89"'`, local MD5 `006a88ed7d5826af90d38dba4666fd89`, `full_body_sent=True`; Traefik access log `PUT … 200 … 80005ms` |
| A2 | The assembled object has the length uploaded through the proxy | **PASS** | Complete → `ETag='"5b393e16e44f517e623cf940a475ecbe-1"'`; `HEAD ContentLength=5242880` (expected 5242880) |
| A3 | A GET after the proxied part PUT is byte-identical | **PASS** | `GET bytes=5242880 sha256=2e7cab6314e9614b6f2da12630661c3038e5592025f6534ba5823c3b340a1cb6 expected_sha256=2e7cab6314e9614b6f2da12630661c3038e5592025f6534ba5823c3b340a1cb6` |
| DIAG Expect | `Expect: 100-continue` is forwarded and the PUT still completes | **PASS** | interim `HTTP/1.1 100 Continue` after `0.002s`; final `status=200 elapsed=0.019s etag='"65e953c1cc4e9edde60cb8aed1af5797"'` |
| DIAG CORS | The CORS preflight for a proxied part PUT allows the origin and exposes `ETag` | **PASS** | `OPTIONS` → 200; `access-control-allow-methods: GET, PUT, POST, DELETE, HEAD`; `access-control-allow-origin: https://proxy.example.test`; `access-control-expose-headers: ETag, Content-Length, Content-Type, Last-Modified, x-amz-request-id, x-amz-version-id` |
| B | Negative control: the identical upload through a default-60s proxy is cut off, and that cut-off is observable | **PASS** | `status=499 elapsed=60.004s sent=3938353/5242880 early_response=True`; body `b'Client Closed Request'`; no ETag (`etag_norm=''`); Traefik log `PUT … 499 21 … 60001ms`; filer `chunked upload failed: truncated request body: read chunk at offset 0 (got 3938353 bytes): unexpected EOF` |
| C | At a conservative 64 KiB/s, both the pilot 5 MiB part and the code-default 16 MiB part fit well inside `readTimeout=7200s` | **PASS** | max part `471859200 B = 450.00 MiB`; comfortable (50% budget) `225.00 MiB`; 5 MiB = `80.0s = 1.11%`; 16 MiB = `256.0s = 3.56%` |
| D | Teardown and pilot isolation | **PASS** | no containers, no network, workdir removed, pilot container set identical before/after |

No assertion was reported as FAIL or UNKNOWN in this run.

## A — slow part through the 7200s proxy (raw evidence)

Presigned `UploadPart` URL through `http://s3.test:32790`, `PartNumber=1`, 5,242,880
bytes, paced at 64 KiB/s, `Origin: https://proxy.example.test`:

```text
A: status=200 error=None elapsed=80.008s expected_send=80.00s sent=5242880/5242880
   early_response=False rate=64KiB/s
   resp_headers={'accept-ranges': 'bytes', 'content-length': '0',
     'date': 'Sun, 25 Oct 2026 22:17:19 GMT',
     'etag': '"006a88ed7d5826af90d38dba4666fd89"',
     'server': 'SeaweedFS 30GB 4.48', 'vary': 'Origin',
     'x-amz-request-id': '18E1E5961CACC2E442196D98'}
A body_md5_local=006a88ed7d5826af90d38dba4666fd89
  etag_norm=006a88ed7d5826af90d38dba4666fd89
  bytes_sent=5242880 bytes_expected=5242880 full_body_sent=True
```

The proxy's own access-log duration is the client's send duration:

```text
"PUT /proxy-51d754813df3/proxy/a-slow-1792966559.bin HTTP/1.1" 200 0
  "-" "-" 10 "s3@file" "http://multipart-proxy-4-48-filer:8333" 80005ms
```

Completing the one-part upload and reading it back:

```text
A Complete -> ETag='"5b393e16e44f517e623cf940a475ecbe-1"'
A HEAD ContentLength=5242880 (expected 5242880)
A GET bytes=5242880 sha256=2e7cab6314e9614b6f2da12630661c3038e5592025f6534ba5823c3b340a1cb6
```

The `-1` suffix is the expected composite ETag for a single part; the whole-object
integrity check is the SHA-256 re-read, not the ETag.

## B — negative control, default 60s (raw evidence)

Same 5,242,880-byte payload (the transcript prints the same full-payload MD5,
`006a88ed7d5826af90d38dba4666fd89`, in both runs), same client pacing, only the proxy
differs — `http://s3.test:32791`, no `readTimeout` override:

```text
B: status=499 error=None elapsed=60.004s expected_send=80.00s sent=3938353/5242880
   early_response=True rate=64KiB/s
   resp_headers={'date': 'Sun, 25 Oct 2026 22:18:19 GMT',
     'content-length': '21', 'connection': 'close'}
   resp_body=b'Client Closed Request'
B etag_norm='' status=499 ... early_response=True
```

The client received the response at 60.004s while it still had 1,304,527 of the
5,242,880 bytes to send. Traefik recorded:

```text
"PUT /proxy-51d754813df3/proxy/b-default-timeout-1792966639.bin HTTP/1.1"
  499 21 "-" "-" 3 "s3@file" "http://multipart-proxy-4-48-filer:8333" 60001ms
```

and the gateway saw a truncated body:

```text
filer E ... upload_chunked.go:281 chunked upload failed: truncated request body:
  read chunk at offset 0 (got 3938353 bytes): unexpected EOF
  (returning 0 partial chunks for cleanup)
filer E ... s3api_object_handlers_multipart.go:480 PutObjectPart: putToFiler failed
  with error code 102 for bucket=proxy-51d754813df3,
  object=proxy/b-default-timeout-1792966639.bin, partNumber=1
```

So the regression is detectable from three independent places: the client (non-200,
short byte count, no ETag), the proxy access log (499 at 60001ms), and the gateway
(truncated-body error naming the exact received byte count).

## C — sizing arithmetic under `readTimeout=7200s`

The plan states no explicit worst-case client bandwidth; its slowest measured rate is
300 KB/s. This harness therefore tests one explicit conservative assumption, **64 KiB/s
(0.5 Mbit/s)**, and the transcript also prints the same arithmetic at the plan's
300 KiB/s for comparison.

At 64 KiB/s (65,536 B/s):

| Quantity | Calculation | Result |
|---|---|---|
| Absolute maximum part inside 7200s | `7200 × 65,536` | 471,859,200 B = **450.00 MiB** |
| Comfortable part (50% of the deadline, 3600s) | `3600 × 65,536` | 235,929,600 B = **225.00 MiB** |
| Pilot part (5 MiB) | `5,242,880 / 65,536 = 80.0s` | **1.11%** of 7200s |
| Code default part (16 MiB) | `16,777,216 / 65,536 = 256.0s` | **3.56%** of 7200s |

At the plan's slowest measured 300 KiB/s (307,200 B/s), for reference:

| Quantity | Result |
|---|---|
| Absolute maximum part inside 7200s | 2,211,840,000 B = 2109.38 MiB |
| Comfortable part (50% of the deadline) | 1054.69 MiB |
| Pilot 5 MiB | 17.1s = 0.24% of 7200s |
| Code default 16 MiB | 54.6s = 0.76% of 7200s |

Conclusion recorded by the harness: `both 5 MiB (pilot) and 16 MiB (code default) parts
use at most 256.0s / 7200s at 64 KiB/s — safe with large margin`. Operationally, 7200s
supports parts up to **225 MiB** at the conservative rate while staying inside half the
deadline, and up to 450 MiB at the absolute ceiling; the current 16 MiB default uses
3.56% of the budget. This bounds the *proxy* deadline only — backend part-size limits are
a separate question (item 5) and may bind first.

## Proxy behaviours observed

- **Body is not rejected or truncated at 5 MiB, and no buffering was observed.** The
  proxy held the request open for the whole paced send (`80005ms` in its access log vs
  `80.008s` client-side) and the gateway computed `ETag == MD5` over all 5,242,880 bytes.
  A proxy that buffered the entire part would still fit 5 MiB in memory, so this run
  cannot exclude buffering at 225–450 MiB part sizes — see "What this does NOT prove".
- **`Host` is preserved.** Routing worked on `Host(s3.test)` (and `other.test` got a
  404), and the presigned request returned 200 rather than `403 SignatureDoesNotMatch`,
  so the SigV4-signed host still matches what the gateway sees.
- **The part `ETag` is returned through the proxy** on both the preflight and the slow
  part (`etag` header present, value equal to the local MD5).
- **`Expect: 100-continue` is forwarded.** The client saw the interim
  `HTTP/1.1 100 Continue` after `0.002s`, then the final 200 in `0.019s`.
- **CORS preflight is forwarded**, with `Access-Control-Expose-Headers` including
  `ETag` — the header a browser multipart client needs to read the part digest.
- **Query parameters are dropped from the access log** (`defaultmode=drop`), so
  `X-Amz-Signature`/`X-Amz-Credential` do not appear in proxy logs.

## Discrepancy: the 60s cutoff surfaced as 499, not 502

The plan's 2026-10-15 live-pilot measurements describe the 60s cutoff as **HTTP 502**
(37.5 MB single PUT at 300 KB/s: "HTTP 502, 18.4 MB of 37.5 MB sent", 60.05s), with the
browser XHR reporting a network error and status 0. In this run the same class of
cut-off — a part body still in flight when the 60s deadline fires — produced **499
`Client Closed Request`** at 60.004s, not 502.

This log records the observation rather than reconciling the mechanism: the captured
evidence shows the client read a 499 response with the 21-byte body `Client Closed
Request`, Traefik logged `499 21 … 60001ms`, and SeaweedFS reported `unexpected EOF` at
3,938,353 bytes. Why the earlier pilot surfaced 502 and this one 499 (single PUT vs
multipart part, different client, different Traefik version/config, or which side
observes the close) was **not** investigated here. Two operational consequences hold
either way:

- a monitor that pages on 5xx alone will **miss** this failure mode — 499 is not a 5xx;
- the reliable detection points are the client (non-200, short `sent` count, absent
  `ETag`) and the gateway (`truncated request body` / `unexpected EOF`), not the proxy
  status code alone.

The plan's dated 2026-10-15 table is left as the record of that live run; this entry is
the record of the harness observation on 2026-10-25.

## Note on unrelated log noise

During the run the filer repeatedly logged
`metadata log write failed /topics/.system/log/…: AssignVolume: … No writable volumes
and no free volumes left`. It did not correlate with any assertion outcome (A still
passed, B still failed exactly as designed) and is **not** attributed or investigated
here; it is mentioned only so a later reader does not mistake it for part of the result.

## What this does NOT prove

- **No real browser.** Part PUTs were issued with Python (`urllib`/`boto3`); the CORS
  "PASS" is header inspection on the wire, not browser enforcement. No preflight cache,
  no `fetch`/XHR limits, no `web/src/lib/transfer.ts`, no CORS failure behaviour, and no
  `ETag` readability from JavaScript were exercised.
- **No TLS termination.** Requests went over plain HTTP to an entrypoint configured with
  `address=:443` but no certificate: no TLS handshake, certificate chain, ALPN/HTTP-2,
  HSTS or real `https://` client were tested.
- **Single VPS, loopback client.** The client, both proxies and the gateway ran on one
  host over loopback with a DNS override, and 64 KiB/s was applied by the client's own
  pacing, not by a constrained network. No WAN RTT, packet loss, NAT, MTU or middlebox
  behaviour. The "slowest supported client rate" is an assumption (64 KiB/s), not a
  measured population.
- **No concurrent-part load.** One part was in flight at a time; part concurrency,
  aggregate bandwidth through Traefik, many simultaneous uploads, per-connection limits
  and proxy memory under load were not tested.
- **Part count and part-size limits are probed separately.** This run uploads exactly
  one 5 MiB part per session. Minimum part size, maximum part count, maximum object
  size, and the backend's own part limits (gate item 5) are outside this capture and
  are being probed in a parallel lane. The 225 MiB/450 MiB figures bound the proxy
  deadline only.
- **The AURA API and web path.** The harness talks directly to the S3 gateway with
  throwaway credentials; it does not prove the API's presigning, part-URL renewal,
  session state, commit verification, abort/reconcile or the UI. Upload-intent URL TTL
  (900s) and renewal after expiry were not exercised.
- **Buffering at production part sizes.** Only 5 MiB traversed the proxy. Whether
  Traefik spools or buffers a 225–450 MiB part, and what that costs in memory, is
  unmeasured.
- **Retry/resume after the cut-off.** B shows the failure is detectable; it does not
  show a client recovering from it, nor that a retried part succeeds after the 60s
  proxy has closed the connection.
- **Crash recovery, restart, HA, disk reclamation.** No container kill, restart, host
  reboot or crash-during-complete scenario; the compat run's disk-reclaim UNKNOWN after
  abort stands.
- **An enabling decision.** `AURA_MULTIPART_ENABLED` stays at its default `off`. This
  run covers gate item 6 only; the gate as a whole is not closed.

## Decision

- Gate item 6 (part PUTs through Traefik plus `readTimeout` sizing) is **COVERED** by
  this run: a slow presigned part PUT succeeds through the 7200s proxy with a correct
  part ETag and a byte-identical object, the identical upload is cut off by a default-60s
  proxy, and at 64 KiB/s a 7200s deadline supports a 225 MiB comfortable / 450 MiB
  absolute part against the current 5 MiB pilot and 16 MiB default.
- The gate as a whole is **not closed**: items 2 and 5 are still being probed in a
  parallel lane, and the compat run's disk-reclaim UNKNOWN remains.
- `AURA_MULTIPART_ENABLED` must remain `0` (default off). Do not enable on this evidence
  alone.
- Next evidence needed: browser-side part PUT, TLS through the real entrypoint, part
  concurrency and aggregate throughput, part count/size limits, and proxy memory at
  production part sizes.

## References

- [S3 multipart upload plan](MULTIPART-UPLOAD-PLAN.md) — gate item 6
- [Multipart compatibility log](verification-log-2026-10-25-multipart-compat-4.48.md)
  (same day, direct-to-gateway run; items 1, 3, 4 and part of 5)
- `docker-compose.yml` — `--entrypoints.websecure.transport.respondingTimeouts.readTimeout=7200s`
- Harness: `tests/multipart-proxy-4.48.sh`, `tests/multipart_proxy_client.py`
- Transcript: `/tmp/opencode/multipart-proxy-4-48-1792966551-2481976.log` (workdir
  removed; transcript preserved)
