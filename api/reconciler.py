"""Automatic reconciliation sweep (#144).

The reconciliation sweep existed only as an administrative route
(``POST /api/v1/admin/reconcile``): nothing triggered it, so stale intents
and half-done purges piled up until a human remembered. This module runs the
same sweep on a fixed interval, in a daemon thread, like the verifier
(``api/verifier.py``) and the scrubber (``api/scrubber.py``).

What a sweep does:

- expires pending intents whose grace window has passed, deleting their bytes
  first — a row is only expired once the storage bytes are really gone
  (``api/lifecycle.py::reconcile_pending``);
- finishes purges interrupted between their two steps (a crash between
  "delete the bytes" and "delete the row").

Safety rules (a sweep deletes user bytes, so it is deliberately conservative):

- **bounded**: at most ``settings.reconcile_limit`` intents per run, so a
  large backlog cannot monopolize the API;
- **never early**: the staleness window is derived from the intent life
  (``intent_ttl + intent_grace_s``) plus ``settings.reconcile_extra_grace_s``,
  so a slow upload in progress is not cut in the middle. The extra margin is
  what separates the automatic sweep from the manual admin route, which
  keeps its historical window;
- **never a false success**: a storage failure keeps the intent ``pending``
  and is counted in ``storage_failures``; the next run retries it;
- **never fatal**: a storage or catalogue outage must not kill the loop. The
  failure is visible in ``GET /api/v1/admin/health`` and the next run retries.

The last sweep's counters are kept in memory and exposed by the health
endpoint, so an operator can see that the sweep runs without reading logs.
"""
from __future__ import annotations

import threading
import time

from .lifecycle import reconcile_pending, resume_purges

_state_lock = threading.Lock()
_last_sweep: dict | None = None


def last_sweep() -> dict | None:
    """The last sweep's counters (``None`` until the first sweep ran)."""
    with _state_lock:
        return dict(_last_sweep) if _last_sweep is not None else None


def _record(payload: dict) -> None:
    global _last_sweep
    with _state_lock:
        _last_sweep = payload


def sweep(repo, s3ops, settings, *, now=time.time, audit=None) -> dict:
    """Run one bounded sweep and return its counters.

    The counters mirror the manual admin route (``expired``,
    ``storage_deletes_attempted``, ``storage_failures``, ``purges_completed``,
    ``purge_failures``) plus ``at`` (epoch seconds) and ``duration_ms``.
    """
    started_at = int(now())
    monotonic_start = time.monotonic()
    limit = max(1, settings.reconcile_limit)
    # The window is the intent life plus the automatic-sweep margin: an
    # intent is only swept long after its grace window, so a slow upload
    # cannot lose its bytes to the sweep.
    expire_after_s = (
        settings.intent_ttl + settings.intent_grace_s + settings.reconcile_extra_grace_s
    )
    out = reconcile_pending(
        repo, s3ops,
        expire_after_s=expire_after_s,
        limit=limit,
        multipart_expired_before=started_at - settings.intent_grace_s,
    )
    out.update(resume_purges(repo, s3ops, limit=limit, now=now))
    out["at"] = started_at
    out["duration_ms"] = int((time.monotonic() - monotonic_start) * 1000)
    _record(out)
    if audit:
        audit("reconcile", "system", "success", out)
    return out


def start_background(repo, s3ops, settings, audit=None) -> threading.Event:
    """Sweep every ``settings.reconcile_interval_s``; set the event to stop."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                sweep(repo, s3ops, settings, audit=audit)
            except Exception:
                # A storage or catalogue outage must not kill the loop: record
                # it and let the next run retry.
                _record({"at": int(time.time()), "error": "sweep failed"})
            stop.wait(settings.reconcile_interval_s)

    threading.Thread(target=loop, name="aura-reconciler", daemon=True).start()
    return stop
