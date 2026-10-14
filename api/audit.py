"""Append-only JSON-lines audit log (#22 hardening).

Only IDs, actions, timestamps and results are recorded. Callers must never
pass passwords, secret keys, session tokens, CSRF tokens, or (presigned) URLs
— not even truncated. URLs stay server-side or go to the authenticated caller
in the API response body only.
"""
import json
import os
import time


def audit_path() -> str:
    # Resolved live so tests can redirect via the environment.
    from .config import settings
    return os.environ.get("AURA_AUDIT_LOG", settings.audit_log)


def audit_event(action: str, actor: str | None, result: str,
                extra: dict | None = None) -> None:
    record = {
        "ts": int(time.time()),
        "actor": actor,
        "action": action,
        "result": result,
    }
    if extra:
        # Whitelist: flat scalars only (IDs, buckets, statuses, TTLs).
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value
    try:
        path = audit_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        # Audit must never break the API itself.
        pass
