# COMMIT-LATENCY-01 — cost of the post-PUT verification (commit)

Answers one operational question: *after the browser's `PUT` returns, how long is the
object still not `available`, and what does that tail cost?*

Symptom that triggered it: users report an **interminable end of upload**. The UI shows
`Envoi…` while the body leaves the browser, then `Validation…`
(`web/src/pages/ObjectsPage.tsx:44-52`), with **no progress bar** for that phase
(`ObjectsPage.tsx:1982-1995`; `web/src/lib/transfer.ts:253` sets `progress: 1` and stops
reporting). A slow commit therefore looks like a frozen upload.

## 1. What the commit actually does

`api/main.py:678-716` (`POST /api/v1/objects/{oid}/commit`):

1. `head_object` — reads size and confirms `ServerSideEncryption=AES256`
   (`api/main.py:679-698`). Cheap: milliseconds.
2. **`get_object` then a full SHA-256 re-read** of every byte just uploaded
   (`api/main.py:700-704` → `stream_sha256`, `api/s3.py:135-148`, 1 MiB chunks,
   `AURA_COMMIT_CHUNK_BYTES` default `1 MiB`, `api/config.py:89`).
3. `repo.mark_available(...)` (`api/main.py:716`).

Step 2 is the only expensive one: it **downloads the entire object again** from the S3
gateway (`AURA_S3_INTERNAL_ENDPOINT`, `docker-compose.yml:236`) purely to compute the
digest. There is no client-supplied checksum to compare against, so the bytes are read
twice: once to store, once to hash.

## 2. Harness (isolated, no pilot)

`tests/commit-latency-bench.sh` + `tests/commit_latency_bench.py`. Same isolation
discipline as `tests/multipart-compat-4.48.sh`: own docker network `bench-commit-net`,
own containers `bench-commit-*`, workdir `/tmp/opencode/bench-commit-<epoch>-<pid>`,
throwaway S3 credentials and `WEED_S3_SSE_KEK` per run, ephemeral host port, `trap`
teardown. It never references the pilot stack (`aura-001-*`, compose project
`aura-storage`) nor the pilot `.env`.

Phases per size, in order — each one mirrors the real code path:

| Phase | Emulates |
|---|---|
| `put_object(ServerSideEncryption='AES256')` | the browser's presigned single `PUT` (`api/s3.py:47-79`) |
| `head_object` | `api/main.py:679` |
| `get_object` + `iter_chunks(1 MiB)` + incremental `hashlib.sha256()` | `api/main.py:700-704` / `stream_sha256` |

`payload_signing_enabled=False` because the app uploads through a presigned URL
(UNSIGNED-PAYLOAD); the server-visible request (SSE header, exact `Content-Length`) is
unchanged. Bodies are streamed, never buffered.

## 3. Commands run

```bash
sg docker -c 'bash tests/commit-latency-bench.sh'
sg docker -c 'bash tests/commit-latency-bench.sh --sizes 8,32 --concurrency 4'
```

Image under test: `chrislusf/seaweedfs:4.48`,
`sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`.
Host: 2 vCPU, `nproc=2`, kernel 7.0.0-38-generic, data dir on the local filesystem.

## 4. Results (verbatim, concurrency 1)

```
     size |    put_s | put MiB/s |  head_ms | rehash_s | rh MiB/s |  ratio | hidden_s | state
    8 MiB |    1.315 |       6.1 |      3.6 |    0.048 |    166.6 |   0.04 |    0.052 | OK
   64 MiB |    0.934 |      68.5 |      4.2 |    0.341 |    187.5 |   0.37 |    0.346 | OK
  256 MiB |    2.150 |     119.1 |      2.9 |    0.961 |    266.4 |   0.45 |    0.964 | OK
```

`ratio = rehash_s / put_s`; `hidden_s = head_ms/1000 + rehash_s` = time the object is
**not** `available` after the `PUT` returned.

Reading: on a fast local disk the rehash runs at ~190-270 MiB/s and costs **37-45 % of
the PUT duration** for the sizes that matter. The 8 MiB row is a stack warm-up artifact
(first PUT of a run pays volume allocation ~1.3 s) — do not read its `put MiB/s` as
steady state.

## 5. Results under concurrent uploads (the pilot's real condition)

`--sizes 8,32 --concurrency 4`: N parallel PUTs, then one rehash **while those PUTs are
still in flight**.

```
     size |  N | put wall_s | agg MiB/s | rehash_s |  base_s |  got/exp | in-flight@end | state
      8 MiB |  4 |      0.336 |      95.3 |    0.265 |   0.046 |     5.76 |             3 | OK
     32 MiB |  4 |      1.141 |     112.1 |    1.181 |   0.166 |     7.11 |             4 | OK
```

`got/exp` = rehash time under contention / idle rehash time. **5.8x-7.1x slowdown** with
only 4 concurrent writes. The rehash competes with the uploads for the same disk, which
is exactly the queue state the web app produces: `DEFAULT_QUEUE_CONCURRENCY = 10`
(`web/src/lib/transfer.ts:401`), per-file commit (`transfer.ts:254`), commits not
serialized (`transfer.ts:646`).

## 6. Aggravating factors found in the pilot configuration

- `uvicorn --workers 1` (`api/Dockerfile:20`): commits run as sync `def` handlers in the
  anyio threadpool of a single worker. Ten simultaneous commits mean ten threads each
  pulling a whole object through the S3 gateway on **2 vCPU**.
- The catalogue layer serializes access with a process-wide `RLock`
  (`api/db_pg.py:31`): each commit must take it at `mark_available`.
- The same disk receives new uploads while old ones are re-read for verification.
- `AURA_MAX_OBJECT_BYTES` defaults to 5 GiB (`api/config.py:88`): the tail scales
  linearly with object size; at 5 GiB the re-read alone is minutes even at 250 MiB/s.
- No timeout on the client commit call (`web/src/lib/api.ts:554-559`): if commit stalls,
  the UI holds `Validation…` indefinitely instead of failing visibly.

## 7. Verdict

| Claim | Status |
|---|---|
| Commit re-reads the whole object to hash it | **VERIFIED in code** (`api/main.py:700-704`) |
| That re-read costs 37-45 % of the PUT time on the measured host | **VERIFIED** (table §4) |
| It slows 5.8x-7.1x under 4 concurrent uploads | **VERIFIED** (table §5) |
| It is the dominant cause of the observed pilot slowness | **UNKNOWN** — the pilot's disk read throughput and real object sizes are not measured (`docs/SERVER-PROFILE.md`: disk IOPS and uplink "not measured") |

The bench proves the mechanism and its scaling. It does **not** prove the pilot's
absolute numbers: on a remote client the PUT is network-bound (slow) while the rehash is
disk-bound (fast), so the ratio differs. The pilot's disk is the missing term.

## 8. Instrumentation (COMMIT-LATENCY-02) — DONE

The commit handler now reports its own timings, with no behaviour change
(`api/main.py:661-746`):

- success path sets `Server-Timing: head;dur=<ms>, hash;dur=<ms>, total;dur=<ms>`
  (milliseconds, 1 decimal). `hash` is the full re-read + SHA-256, i.e. the tail;
- one log line per successful commit on logger `uvicorn.error` (not `api.main`:
  uvicorn installs handlers only on its own loggers, so an `api.main` INFO record is
  dropped by `logging.lastResort`; verified locally by running uvicorn and observing
  that only the `uvicorn.error` line reached the process output):
  `commit timings oid=<id> bytes=<n> head_ms=<x> hash_ms=<y> total_ms=<z>`;
- the idempotent `status == "available"` early return emits neither, so a repeated
  commit cannot pollute the distribution;
- error paths are unchanged and not timed.

Read the distribution on the pilot with:

```bash
docker logs <instance>-api 2>&1 | grep 'commit timings'
```

or from a browser: DevTools → Network → the `commit` request → Response Headers →
`Server-Timing`.

Covered by `test_commit_emits_server_timing` (`tests/test_commit_streaming.py`); the full
offline suite passes (251 passed, 2 skipped).

## 9. Next measurements required, in order

1. Collect `commit timings` from real pilot traffic — this gives the distribution
   actually experienced (file sizes, `hash_ms`, `total_ms`) with no infra change.
2. `commit_latency_bench.py` executed against the pilot's S3 endpoint with a handful of
   representative sizes, under **explicit authorization** (`docs/DEPLOYMENT.md`), to
   obtain the pilot's `rehash MiB/s` and disk headroom.
3. Only then decide between: checksum captured at upload time (removes the re-read),
   sequential-bounded commits (removes the contention), or both.
