"""Append-only JSON-lines audit log (#22 hardening, M07 observability).

Only IDs, actions, timestamps and results are recorded. Callers must never
pass passwords, secret keys, session tokens, CSRF tokens, or (presigned) URLs
— not even truncated. URLs stay server-side or go to the authenticated caller
in the API response body only.

M07: every event is automatically stamped with the request ID carried by the
request context (see ``bind_request``), plus the caller's ``space_id`` /
``application_id`` when the request authenticated before the event was
emitted (see ``bind_principal``). Explicit ``extra`` values always win over
the ambient context, so a call site can never be silently re-scoped.

Reads (``query_audit_log``) scan a bounded tail of the file newest-first and
apply the M07 search filters in memory; writes stay O(1) appends. No database
table or migration is required for this volume.
"""
import json
import os
import threading
import time
from collections import deque
from contextvars import ContextVar
from typing import Any

try:
    import fcntl  # POSIX hardening for multi-process deployments
except ImportError:  # pragma: no cover - pilot and CI run on Linux
    fcntl = None  # type: ignore[assignment]

# Serializes audit appends against retention pruning inside this process
# (the deployed API runs a single worker). Combined with an exclusive
# advisory lock on the file, a prune rewrite can never interleave with an
# append and no event is lost or duplicated.
_AUDIT_LOCK = threading.Lock()

# Ambient request context (M07). The middleware binds one *mutable* holder per
# request and resets it afterwards. A plain immutable value would not work
# here: FastAPI runs sync dependencies and endpoints in separate worker
# threads, each with its own copy of the context, so a ``set`` performed in
# the authorization layer would never reach the endpoint that emits the
# audit event. Mutating the shared holder is visible everywhere because every
# copy references the same dict; the middleware reset still prevents any
# cross-request leak between sequential requests on one worker thread.
_request_ctx: ContextVar[dict | None] = ContextVar(
    "aura_request_ctx", default=None
)


def bind_request_context(request_id: str) -> tuple[dict, Any]:
    """Bind a fresh holder for the current request; returns it and the token."""
    holder: dict[str, Any] = {"request_id": request_id}
    return holder, _request_ctx.set(holder)


def reset_request_context(token) -> None:
    _request_ctx.reset(token)


def set_request_principal(space_id: str | None,
                          application_id: str | None) -> None:
    """Attribute the current request to the authenticated caller's tenant."""
    holder = _request_ctx.get()
    if holder is not None:
        holder["space_id"] = space_id
        holder["application_id"] = application_id


def current_request_id() -> str | None:
    holder = _request_ctx.get()
    return holder.get("request_id") if holder else None


def audit_path() -> str:
    # Resolved live so tests can redirect via the environment.
    from .config import settings
    return os.environ.get("AURA_AUDIT_LOG", settings.audit_log)


def audit_event(action: str, actor: str | None, result: str,
                extra: dict | None = None) -> None:
    record: dict[str, Any] = {
        "ts": int(time.time()),
        "actor": actor,
        "action": action,
        "result": result,
    }
    # Request correlation first: present on every in-request event, including
    # pre-authentication ones such as failed logins.
    holder = _request_ctx.get() or {}
    request_id = holder.get("request_id")
    if request_id is not None:
        record["request_id"] = request_id
    if extra:
        # Whitelist: flat scalars only (IDs, buckets, statuses, TTLs).
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value
    # Tenant attribution from the ambient principal; explicit extras win so
    # the effective scope of an event can never be rewritten silently.
    if record.get("space_id") is None and holder.get("space_id") is not None:
        record["space_id"] = holder["space_id"]
    if (record.get("application_id") is None
            and holder.get("application_id") is not None):
        record["application_id"] = holder["application_id"]
    try:
        path = audit_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _AUDIT_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                fh.write(json.dumps(record) + "\n")
    except OSError:
        # Audit must never break the API itself.
        pass


def _tail_lines(path: str, max_lines: int) -> tuple[list[str], bool]:
    """Return the last ``max_lines`` raw lines and whether older lines exist."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tail: deque[str] = deque(fh, maxlen=max_lines)
    except FileNotFoundError:
        return [], False
    except OSError:
        return [], False
    # ``truncated`` is approximate without a second pass: it is True only when
    # the tail window is full, i.e. older lines *may* exist. Callers surface it
    # as-is so a full window is never mistaken for the whole history.
    return list(tail), len(tail) == max_lines


def query_audit_log(
    *,
    since: int | None = None,
    until: int | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    space_id: str | None = None,
    application_id: str | None = None,
    request_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    max_scan_lines: int = 20000,
) -> dict:
    """Search the audit log newest-first with the M07 filters.

    Returns ``{"items", "total", "truncated", "scanned"}`` where ``total`` is
    the match count inside the scanned window and ``truncated`` signals that
    the window may exclude older history. A missing log file is an empty
    history, never an error.
    """
    # Defensive clamp: a non-positive window would scan nothing (or loop on a
    # zero-length deque). The import-time check in config.py is the primary
    # guard; this keeps a direct caller from silently disabling reads.
    max_scan_lines = max(1, max_scan_lines)
    lines, window_full = _tail_lines(audit_path(), max_scan_lines)
    scanned = len(lines)
    matches: list[dict] = []
    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        ts = record.get("ts")
        if since is not None and (not isinstance(ts, (int, float)) or ts < since):
            continue
        if until is not None and (not isinstance(ts, (int, float)) or ts > until):
            continue
        if actor is not None and actor not in str(record.get("actor") or ""):
            continue
        if action is not None and record.get("action") != action:
            continue
        if result is not None and record.get("result") != result:
            continue
        if space_id is not None and record.get("space_id") != space_id:
            continue
        if application_id is not None and record.get("application_id") != application_id:
            continue
        if request_id is not None and record.get("request_id") != request_id:
            continue
        matches.append(record)
    total = len(matches)
    return {
        "items": matches[offset:offset + limit],
        "total": total,
        "truncated": window_full,
        "scanned": scanned,
    }


def recent_error_events(*, window_s: int = 3600, limit: int = 5,
                        max_scan_lines: int = 5000) -> tuple[list[dict], int]:
    """Newest non-success events inside ``window_s`` (public-safe projection).

    Only timestamp/action/actor/result/request correlation are returned: no
    payload that could carry tenant data. Returns ``(events, scanned)``.
    """
    # Same defensive clamp as ``query_audit_log`` (see there).
    max_scan_lines = max(1, max_scan_lines)
    cutoff = int(time.time()) - window_s
    lines, _ = _tail_lines(audit_path(), max_scan_lines)
    scanned = len(lines)
    errors: list[dict] = []
    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        ts = record.get("ts")
        if not isinstance(ts, (int, float)) or ts < cutoff:
            continue
        if record.get("result") == "success":
            continue
        errors.append({
            "ts": record.get("ts"),
            "action": record.get("action"),
            "actor": record.get("actor"),
            "result": record.get("result"),
            "request_id": record.get("request_id"),
        })
        if len(errors) >= limit:
            break
    return errors, scanned


def prune_audit_log(*, retention_days: int) -> dict:
    """Drop audit lines older than the retention window (M07).

    Lines without a valid timestamp are *kept*: audit data is never deleted
    silently. The rewrite is atomic (temporary file + rename). Returns
    ``{"kept", "dropped", "cutoff", "retention_days"}``.
    """
    # A non-positive retention would drop (or keep, depending on sign) the whole
    # history. Refuse rather than delete audit data by accident.
    if retention_days < 1:
        raise ValueError("retention_days must be >= 1")
    cutoff = int(time.time()) - retention_days * 86400
    path = audit_path()
    with _AUDIT_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            return {"kept": 0, "dropped": 0, "cutoff": cutoff,
                    "retention_days": retention_days}
        kept_lines: list[str] = []
        dropped = 0
        for raw in lines:
            try:
                record = json.loads(raw)
                ts = record.get("ts") if isinstance(record, dict) else None
            except (json.JSONDecodeError, ValueError):
                ts = None
            if isinstance(ts, (int, float)) and ts < cutoff:
                dropped += 1
            else:
                kept_lines.append(raw)
        tmp_path = f"{path}.prune.tmp"
        try:
            # Best-effort exclusive advisory lock across the rewrite. The real
            # guarantee is the in-process _AUDIT_LOCK (the API runs a single
            # worker); a multi-worker deployment must serialize prune calls
            # externally, e.g. one operator at a time.
            with open(path, "a", encoding="utf-8") as lock_fh:
                if fcntl is not None:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    fh.writelines(kept_lines)
                os.replace(tmp_path, path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    return {"kept": len(kept_lines), "dropped": dropped, "cutoff": cutoff,
            "retention_days": retention_days}
