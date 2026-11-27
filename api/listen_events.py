"""Shared rules for append-only listening events (#320).

No listener-level detail leaves the catalogue: events are keyed by a stable
hash, carry only a position delta, and are anonymised on account deletion.
"""
from __future__ import annotations

import hashlib

DEFAULT_RETENTION_DAYS = 365
# The player saves a sample every ~5 s; allow wall-clock jitter and a small
# tolerance, but never count a long forward seek as listened time. A gap longer
# than this is treated as an idle/suspended tab, not as listening time.
SEEK_TOLERANCE_SECONDS = 5.0
DELAYS_FACTOR = 1.25
MAX_CREDITED_INTERVAL_SECONDS = 15.0


def event_id(
    user_id: str, object_id: str, kind: str, position_seconds: float,
    now: int, client_event_id: str = "",
) -> str:
    """Deterministic id: the same sample in the same minute is one event."""
    raw = "|".join((
        str(user_id), str(client_event_id or ""), str(object_id), str(kind),
        str(int(float(position_seconds))), str(int(now) // 60),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def listened_delta(previous: float, position: float, elapsed_seconds: float) -> float:
    """Positive position change capped by a bounded listening interval."""
    advance = max(0.0, float(position) - float(previous))
    credited = min(max(0.0, float(elapsed_seconds)), MAX_CREDITED_INTERVAL_SECONDS)
    cap = credited * DELAYS_FACTOR + SEEK_TOLERANCE_SECONDS
    return round(min(advance, cap), 3)
