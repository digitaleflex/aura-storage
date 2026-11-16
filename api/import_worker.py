"""Background worker for bulk import jobs (Lot 3).

The API books import jobs in ``queued`` state with a ``total_items`` count but
no per-item payload yet (see ``api/main.py`` / OpenAPI). This worker provides the
execution skeleton: it claims jobs under a lease, drives them to a terminal
state, honours cancellation, and recovers from crashes via lease expiry.

Processing hook
---------------
``process_import_job`` is the extension point for real item handling. Today it
marks the whole batch processed and completes the job with an explicit summary,
because the current contract defines no import source/items to fetch.

Safety
------
- **Lease-based claim** so two workers never process the same job; an expired
  lease (crash) is reclaimed.
- **Cancellation-aware**: if the job is cancelled while running, processing
  stops and the cancelled state is preserved.
- **Never fatal**: exceptions fail the job (or release it for retry via the
  claim/lease model) without killing the loop.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable


_STUB_SUMMARY = json.dumps(
    {
        "message": "batch booked (no per-item import source defined by the current API contract)",
        "worker": "stub",
    },
    separators=(",", ":"),
)


def _is_cancelled(repo, jid: str) -> bool:
    row = repo.get_import_job_by_id(jid)
    return row is not None and row.get("status") == "cancelled"


def process_import_job(
    repo, job: dict[str, Any], settings, *, now=time.time, audit: Callable | None = None,
) -> str:
    """Process one claimed job. Returns the terminal outcome string.

    Stub behaviour: the contract carries no items to import, so we complete the
    booked batch in one step. Real import sources can replace this function to
    iterate items while renewing the lease and updating progress.
    """
    jid = job["id"]
    total = int(job.get("total_items") or 0)

    if _is_cancelled(repo, jid):
        return "cancelled"

    # Placeholder processing: nothing to fetch, so the batch is accounted for.
    repo.update_import_job(
        jid,
        status="done",
        processed_items=total,
        failed_items=0,
        summary=_STUB_SUMMARY,
    )
    # Release lease marker; status is terminal.
    try:
        repo.renew_import_job_lease(jid, 0)
    except Exception:
        pass
    if audit:
        audit(
            "import_job.complete",
            "system",
            "success",
            {
                "import_job_id": jid,
                "space_id": job.get("space_id"),
                "processed_items": total,
                "failed_items": 0,
                "mode": "stub",
            },
        )
    return "done"


def run_once(
    repo, settings, *, now=time.time, audit: Callable | None = None,
) -> str | None:
    """Claim and process at most one job. Returns outcome or None if idle."""
    t = int(now())
    job = repo.claim_import_job(t, t + settings.import_worker_lease_s)
    if job is None:
        return None
    if isinstance(job, dict):
        job = dict(job)
    jid = job["id"]
    if audit:
        audit(
            "import_job.start",
            "system",
            "success",
            {
                "import_job_id": jid,
                "space_id": job.get("space_id"),
                "total_items": int(job.get("total_items") or 0),
                "attempt": int(job.get("attempts") or 1),
            },
        )
    try:
        outcome = process_import_job(repo, job, settings, now=now, audit=audit)
    except Exception as exc:
        # Mark failed but never kill the worker loop.
        try:
            if not _is_cancelled(repo, jid):
                repo.update_import_job(
                    jid,
                    status="failed",
                    summary=json.dumps(
                        {"message": "import worker error", "error": str(exc)[:500]},
                        separators=(",", ":"),
                    ),
                )
                if audit:
                    audit(
                        "import_job.fail",
                        "system",
                        "error",
                        {"import_job_id": jid, "space_id": job.get("space_id")},
                    )
        except Exception:
            pass
        return "failed"
    return outcome


def start_background(repo, settings, audit: Callable | None = None) -> threading.Event:
    """Process queued import jobs in a daemon thread; set the event to stop."""
    stop = threading.Event()
    if not getattr(settings, "import_worker_enabled", True):
        stop.set()
        return stop

    def loop():
        while not stop.is_set():
            try:
                outcome = run_once(repo, settings, audit=audit)
            except Exception:
                outcome = None
            if outcome is None:
                stop.wait(settings.import_worker_poll_s)

    threading.Thread(target=loop, name="aura-import-worker", daemon=True).start()
    return stop
