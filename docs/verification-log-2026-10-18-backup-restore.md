# Verification log — off-site backup and restore (2026-10-18)

Local end-to-end run, **not** the pilot VPS. Same SeaweedFS release as the
pilot (4.48 binary), PostgreSQL 16, rclone 1.68.2, AURA API from this branch.
Off-site destination simulated by an rclone `local` remote behind rclone crypt.

| Step | Result |
|---|---|
| 5 files uploaded through the API (intent, presigned PUT, commit; 1 B to 3 MB), 1 soft-deleted, 1 empty extra bucket | OK, commit SHA-256 = local SHA-256 |
| `scripts/backup.sh` | OK, 2 buckets, 4 available objects; names and contents encrypted at the destination |
| Second run | OK, retention pruning without error (after fixing the first-run "objects-history not found" noise) |
| `scripts/restore-check.sh --sample 10` against a scratch database | 10/10 PASS (manifest hashes, counts, 4 sampled SHA-256) |
| Primary SeaweedFS **stopped**; fresh SeaweedFS with a **different** `WEED_S3_SSE_KEK` + empty catalogue + new API | started |
| `scripts/restore.sh <stamp>` without the flag / on a non-empty target | refused, as designed |
| `scripts/restore.sh <stamp> --confirm-empty-target` | OK in 2 s |
| API restarted; login with the restored admin; 4/4 objects downloaded through presigned GET | SHA-256 match |
| Restored objects report `ServerSideEncryption=AES256` | OK |

Not covered: real off-site provider latency/throughput, multi-GB objects
(rclone multipart against SeaweedFS), restore of a large catalogue, the Docker
runners on the VPS (the run used host binaries through the runner overrides).
