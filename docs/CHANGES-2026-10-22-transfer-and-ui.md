# Changes of 2026-10-22 — slow uploads audit, transfer engine and UI

Context: after a series of upstream changes (queue concurrency 3 → 10, bounded S3
client, background workers, read caches) uploads became very slow. A code audit
of the transfer engine and the web UI produced the changes below. Each line names
the pull request of the fork `letriplenesty-ai/aura-storage`.

> **Status.** Everything here is in code and covered by offline tests (pytest on
> SQLite and PostgreSQL 17; Playwright with mocked APIs). **No gain has been
> measured on the pilot**, and nothing has been deployed by this work. Use
> [MEASURE-TRANSFER.md](MEASURE-TRANSFER.md) before and after deploying.

## Why uploads were slow (hypotheses ranked, evidence level)

| # | Cause | Evidence |
|---|---|---|
| 1 | 10 parallel PUTs share one uplink; a file lasting more than Traefik's 1200 s read timeout is cut and restarts from zero | Mechanism checked in code and config; impact depends on the real uplink (not measured) |
| 2 | A commit failure re-sent the whole file, which then hit `412`/`409` and ended `failed` with intact bytes | Checked in code |
| 3 | The commit re-reads the object while other PUTs run: 37-45 % of PUT time idle, 5.8-7.1x slower with 4 concurrent writes | Team benchmark (`engineering/commit-latency-bench.md`) |
| 4 | A file in `verifying` kept its queue slot while polling every 1-15 s, so ten such files froze the queue | Checked in code |
| 5 | The scrubber re-read freshly uploaded files (`mark_available` did not stamp `scrubbed_at`) | Checked in code |
| 6 | `-s3.readerCacheSizeMB=128` is a blocking global read budget | Plausible from SeaweedFS source; **not measured** |
| 7 | The page re-rendered at every XHR progress event (~200/s at ten files) | Engine cost measured on a faithful copy; React render not measured |

Weak effects, measured or checked: catalogue queries (< 25 ms at 100 000 rows),
the boto connection pool, `If-None-Match: *`.

## Transfer engine and API

| PR | Change |
|---|---|
| #27 | Default queue concurrency 10 → 4 (adaptive back-off unchanged) |
| #29 | Commit retried on its own; `412` on the PUT goes straight to commit; a file answered `202` releases its upload slot; polling capped at 5 s |
| #28 | `mark_available` stamps `scrubbed_at`/`scrub_result='ok'`; the scrubber yields while uploads are in flight |
| #30 | The verifier waits while uploads are running; async verification from 32 MiB (was 256 MiB) |
| #31 | A commit past its deadline is handed to the verifier (`202`) instead of deleting the bytes |
| #35 | Antivirus hook shared by commit and verifier, with a timeout and a 0600 temp file; daily quota debited atomically and only for accepted requests; commit response cache fixed (it never ran), scoped to the caller and bounded; one `commit_deadline_s` declaration |
| #37 | Indexes `idx_objects_idem(actor_id, idempotency_key)` and a partial `idx_objects_inflight` on `pending`/`verifying`; SeaweedFS reader cache default 128 → 512 MB |

Behaviour users will notice: a file stays **`verifying` (not downloadable) until
the batch of uploads is over**; keep the local originals until everything is
`available`. `AURA_VERIFY_PAUSE_WHILE_UPLOADING=0` restores continuous
verification.

## Web UI

| PR | Change |
|---|---|
| #32 | Progress-only updates coalesced (one per 250 ms); toast timers no longer restart on every render; the tray list is no longer `aria-live` |
| #33 | "Annuler" asks for confirmation; visible focus ring; field borders ≥ 3:1 |
| #34 | Throughput over a 20 s sliding window; ledger refreshed while a batch runs; "Réessayer les échecs" available mid-import |
| #38 | On batches above 30 files the tray lists only what needs attention (filter Auto/En cours/Échecs/Tous), 100 rows at most |
| #41, #42 | The tray explains each step in a sentence, shows its duration, a one-line breakdown, and a per-file detail view (steps with times, object id, server SHA-256) |
| #43, #44 | Tray extracted into a memoised component; cascade-deletion logic moved to `lib/cascade.ts` with unit tests |
| #46, #47, #48 | Design pass from real screenshots: vault overview, file-type tiles, status pills, theme-aware native controls, branded error page, administration panels, readable supervision, dialogs, `scroll-padding-top` under the sticky bar |

## Tooling, CI and operations

| PR | Change |
|---|---|
| #36, #39 | `package-lock.json` resynchronised; 15 routes documented in `openapi.yaml` (descriptions quoted) |
| #40 | `deploy.yml` is `workflow_dispatch` only in this fork: a merge no longer opens SSH on the VPS |
| #45 | `scripts/transfer-baseline.py` and [MEASURE-TRANSFER.md](MEASURE-TRANSFER.md): read-only before/after comparison from saved logs |

## Not done, on purpose

* Multipart uploads stay disabled (`AURA_MULTIPART_ENABLED=0`) until validated on
  the pinned SeaweedFS 4.48.
* Sending the SHA-256 with the PUT to remove the re-read: not proven.
* PC sync agent, resumable downloads, S3 circuit breaker, chained audit log.
* Splitting the rest of `ObjectsPage.tsx` (registry, drawer, cascade loop, hooks).
* Real antivirus (ClamAV): only a shell stub was tested.
