"""Pure domain logic for Lot 1: access, publication and listening progress.

This module has no database or HTTP dependency. It is deliberately deterministic
so the rules can be property-tested and reused by the API, workers and tests.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable
from uuid import UUID

from .errors import AppError, ConflictError, ValidationError

EVENT_KINDS = frozenset(
    {"start", "heartbeat", "seek", "pause", "resume", "ended", "takeover"}
)
ACCESS_ACTIONS = frozenset({"stream", "preview", "download"})
ACCESS_MODELS = frozenset({"free", "paid", "subscription"})

# A heartbeat may legitimately arrive a little behind the last committed
# position (network reordering, client timer). Explicit seeks are the only way
# to move backwards by more than this tolerance.
REGRESSION_TOLERANCE_MS = 2_000
# Completion is never inferred from a small position alone. The threshold is
# the greater of 30 seconds and 2% of the duration, and only applies when the
# duration is known. An explicit ``ended`` event always completes.
MIN_COMPLETION_THRESHOLD_MS = 30_000
COMPLETION_FRACTION = 0.02


def completion_threshold_ms(duration_ms: int | None) -> int | None:
    if not duration_ms or duration_ms <= 0:
        return None
    return max(MIN_COMPLETION_THRESHOLD_MS, int(duration_ms * COMPLETION_FRACTION))


def validate_position(position_ms: int, duration_ms: int | None) -> None:
    if isinstance(position_ms, bool) or not isinstance(position_ms, int):
        raise ValidationError("position_ms must be an integer")
    if position_ms < 0:
        raise ValidationError("position_ms cannot be negative", code="POSITION_NEGATIVE")
    if duration_ms is not None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise ValidationError("duration_ms must be an integer")
        if duration_ms < 0:
            raise ValidationError("duration_ms cannot be negative")
        if duration_ms > 0 and position_ms > duration_ms + 5_000:
            raise ValidationError(
                "position_ms exceeds the track duration",
                code="POSITION_OUT_OF_RANGE",
                details={"position_ms": position_ms, "duration_ms": duration_ms},
            )


@dataclass(frozen=True)
class ProgressState:
    listener_id: UUID
    edition_id: UUID
    position_ms: int = 0
    track_id: UUID | None = None
    active_session_id: UUID | None = None
    last_event_id: UUID | None = None
    version: int = 1
    completed_at: datetime | None = None
    last_completed_position_ms: int | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PlaybackSessionState:
    id: UUID
    listener_id: UUID
    edition_id: UUID
    state: str
    last_client_seq: int
    last_heartbeat_at: datetime
    active_lease_until: datetime | None
    version: int = 1


@dataclass(frozen=True)
class PlaybackEvent:
    event_id: UUID
    session_id: UUID
    listener_id: UUID
    edition_id: UUID
    kind: str
    client_seq: int
    position_ms: int
    track_id: UUID | None = None
    duration_ms: int | None = None
    occurred_at_client: datetime | None = None
    playback_rate: float = 1.0


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    conflict: bool
    reason: str
    progress: ProgressState
    session_state: str
    duplicate: bool = False


def apply_event(
    progress: ProgressState,
    session: PlaybackSessionState,
    event: PlaybackEvent,
    now: datetime,
    *,
    takeover: bool = False,
) -> ApplyResult:
    """Apply one ordered playback event or return an explicit no-op/conflict.

    Invariants:
    - an event belongs to exactly one listener, edition and session;
    - a client sequence is monotonic; stale sequences never move progress;
    - only an explicit seek (or start/takeover) may move the position backwards;
    - completion is monotonic: a later rewind never erases ``completed_at``;
    - a session without the active lease cannot advance progress unless the
      caller explicitly takes over.
    """
    if event.session_id != session.id:
        raise ValidationError("event does not belong to this session", code="EVENT_CONTEXT_MISMATCH")
    if event.listener_id != session.listener_id or progress.listener_id != session.listener_id:
        raise ValidationError("listener mismatch", code="EVENT_CONTEXT_MISMATCH")
    if event.edition_id != session.edition_id or progress.edition_id != session.edition_id:
        raise ValidationError("edition mismatch", code="EVENT_CONTEXT_MISMATCH")
    if event.kind not in EVENT_KINDS:
        raise ValidationError("unknown playback event kind", code="EVENT_KIND_INVALID")
    if event.client_seq < 1:
        raise ValidationError("client_seq must be positive", code="SEQUENCE_INVALID")
    if not (0.25 <= float(event.playback_rate) <= 4.0):
        raise ValidationError("playback_rate must be between 0.25 and 4.0")
    validate_position(event.position_ms, event.duration_ms)

    if progress.last_event_id == event.event_id:
        return ApplyResult(False, False, "duplicate_event", progress, session.state, duplicate=True)
    if event.client_seq <= session.last_client_seq:
        return ApplyResult(False, False, "stale_sequence", progress, session.state)

    if session.state == "paused":
        if event.kind not in {"resume", "ended"}:
            return ApplyResult(False, True, "session_not_active", progress, session.state)
    elif session.state != "active":
        if not takeover:
            return ApplyResult(False, True, "session_not_active", progress, session.state)
    if (
        session.active_lease_until is not None
        and now > session.active_lease_until
        and not takeover
    ):
        return ApplyResult(False, True, "lease_expired", progress, session.state)

    if (
        event.kind in {"heartbeat", "pause", "resume"}
        and event.position_ms + REGRESSION_TOLERANCE_MS < progress.position_ms
    ):
        return ApplyResult(False, False, "regressive_position", progress, session.state)

    threshold = completion_threshold_ms(event.duration_ms)
    completes = event.kind == "ended" or (
        threshold is not None and event.position_ms >= max(0, event.duration_ms - threshold)
    )
    completed_at = progress.completed_at
    last_completed_position = progress.last_completed_position_ms
    if completes:
        completed_at = completed_at or now
        last_completed_position = event.position_ms

    if event.kind == "pause":
        session_state = "paused"
    elif event.kind == "ended":
        session_state = "ended"
    else:
        session_state = "active"

    new_progress = replace(
        progress,
        position_ms=event.position_ms,
        track_id=event.track_id if event.track_id is not None else progress.track_id,
        active_session_id=session.id,
        last_event_id=event.event_id,
        version=progress.version + 1,
        completed_at=completed_at,
        last_completed_position_ms=last_completed_position,
        updated_at=now,
    )
    return ApplyResult(True, False, "applied", new_progress, session_state)


@dataclass(frozen=True)
class RightsWindowFact:
    id: UUID
    territory_code: str
    channel: str
    starts_at: datetime
    ends_at: datetime
    status: str


@dataclass(frozen=True)
class EntitlementFact:
    id: UUID
    source_type: str
    scope_type: str
    scope_id: str
    status: str
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True)
class AccessFacts:
    listener_status: str
    edition_id: UUID
    work_id: UUID
    edition_status: str
    access_model: str
    action: str
    territory_code: str
    now: datetime
    rights: tuple[RightsWindowFact, ...] = ()
    entitlements: tuple[EntitlementFact, ...] = ()
    asset_ready: bool = False
    device_authorized: bool | None = None
    decision_ttl_seconds: int = 60
    policy_version: str = "lot1-2026-11"


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason_code: str
    sources: tuple[str, ...]
    expires_at: datetime | None
    policy_version: str
    territory_code: str
    action: str
    edition_id: UUID


def _candidate_rights(
    rights: Iterable[RightsWindowFact],
    *,
    action: str,
    now: datetime,
) -> list[RightsWindowFact]:
    result: list[RightsWindowFact] = []
    for window in rights:
        if window.status != "active":
            continue
        if not (window.starts_at <= now < window.ends_at):
            continue
        if window.channel not in {action, "stream"}:
            continue
        result.append(window)
    return result


def _active_rights(
    rights: Iterable[RightsWindowFact],
    *,
    action: str,
    territory: str,
    now: datetime,
) -> list[RightsWindowFact]:
    return [
        window
        for window in _candidate_rights(rights, action=action, now=now)
        if window.territory_code in {"WORLD", territory}
    ]


def _active_entitlements(
    entitlements: Iterable[EntitlementFact],
    *,
    edition_id: UUID,
    work_id: UUID,
    now: datetime,
    scope_types: set[str],
) -> list[EntitlementFact]:
    result: list[EntitlementFact] = []
    for entitlement in entitlements:
        if entitlement.status != "active":
            continue
        if entitlement.valid_from > now:
            continue
        if entitlement.valid_until is not None and entitlement.valid_until <= now:
            continue
        if entitlement.scope_type not in scope_types:
            continue
        if entitlement.scope_type == "edition" and entitlement.scope_id != str(edition_id):
            continue
        if entitlement.scope_type == "work" and entitlement.scope_id != str(work_id):
            continue
        result.append(entitlement)
    return result


def decide_access(facts: AccessFacts) -> AccessDecision:
    """Evaluate the access policy and return an explainable decision.

    The decision is intentionally *not* stored here; the caller records it in
    ``access_decisions`` so every playback grant has an audit trail.
    """

    def deny(code: str) -> AccessDecision:
        return AccessDecision(
            allowed=False,
            reason_code=code,
            sources=(),
            expires_at=None,
            policy_version=facts.policy_version,
            territory_code=facts.territory_code,
            action=facts.action,
            edition_id=facts.edition_id,
        )

    if facts.action not in ACCESS_ACTIONS:
        return deny("ACTION_UNSUPPORTED")
    if facts.listener_status != "active":
        return deny(f"ACCOUNT_{facts.listener_status.upper()}")
    if facts.edition_status != "published":
        return deny("EDITION_NOT_PUBLISHED")
    if facts.access_model not in ACCESS_MODELS:
        return deny("ACCESS_MODEL_UNSUPPORTED")
    if facts.action == "download":
        # D-06 (offline grants) is not part of Lot 1. Refuse rather than leak a
        # long-lived URL through a generic "stream" path.
        return deny("DOWNLOAD_NOT_ENABLED")
    candidates = _candidate_rights(
        facts.rights, action=facts.action, now=facts.now
    )
    rights = [
        window
        for window in candidates
        if window.territory_code in {"WORLD", facts.territory_code}
    ]
    if not rights:
        if candidates:
            return deny("TERRITORY_RESTRICTED")
        return deny("NO_ACTIVE_RIGHTS")
    if not facts.asset_ready:
        return deny("ASSET_UNAVAILABLE")
    if facts.device_authorized is False:
        return deny("DEVICE_NOT_AUTHORIZED")

    sources: list[str] = [f"rights:{rights[0].id}"]
    entitlements: list[EntitlementFact] = []
    if facts.access_model == "free":
        sources.insert(0, "free")
    else:
        scope_types = {"edition", "work"}
        if facts.access_model == "subscription":
            scope_types.add("plan_catalog")
        entitlements = _active_entitlements(
            facts.entitlements,
            edition_id=facts.edition_id,
            work_id=facts.work_id,
            now=facts.now,
            scope_types=scope_types,
        )
        if not entitlements:
            return deny(
                "NO_ACTIVE_ENTITLEMENT"
                if facts.access_model == "paid"
                else "NO_ACTIVE_SUBSCRIPTION"
            )
        sources.append(f"entitlement:{entitlements[0].id}")

    expiry = facts.now + timedelta(seconds=facts.decision_ttl_seconds)
    expiry = min(expiry, rights[0].ends_at)
    for entitlement in entitlements:
        if entitlement.valid_until is not None:
            expiry = min(expiry, entitlement.valid_until)
    return AccessDecision(
        allowed=True,
        reason_code="ALLOWED",
        sources=tuple(sources),
        expires_at=expiry,
        policy_version=facts.policy_version,
        territory_code=facts.territory_code,
        action=facts.action,
        edition_id=facts.edition_id,
    )


@dataclass(frozen=True)
class TrackFact:
    id: UUID
    position: int
    status: str
    asset_status: str | None


@dataclass(frozen=True)
class PublicationFacts:
    work_id: UUID
    work_title: str
    work_language: str
    work_status: str
    authors: tuple[str, ...]
    narrators: tuple[str, ...]
    edition_title: str
    edition_language: str
    edition_description: str
    duration_ms: int
    cover_asset_id: UUID | None
    tracks: tuple[TrackFact, ...]
    rights: tuple[RightsWindowFact, ...]
    now: datetime


@dataclass(frozen=True)
class PublicationBlocker:
    code: str
    field: str


def validate_publication(facts: PublicationFacts) -> tuple[PublicationBlocker, ...]:
    """Return every blocker, not just the first, so an editor can fix them at once."""
    blockers: list[PublicationBlocker] = []

    def add(code: str, field: str) -> None:
        blockers.append(PublicationBlocker(code, field))

    if facts.work_status != "approved":
        add("WORK_NOT_APPROVED", "work.status")
    if not facts.work_title.strip():
        add("WORK_TITLE_MISSING", "work.title")
    if not facts.work_language.strip():
        add("WORK_LANGUAGE_MISSING", "work.language")
    if not facts.authors:
        add("AUTHOR_MISSING", "work.authors")
    if not facts.narrators:
        add("NARRATOR_MISSING", "work.narrators")
    if not facts.edition_title.strip():
        add("EDITION_TITLE_MISSING", "edition.title")
    if not facts.edition_language.strip():
        add("EDITION_LANGUAGE_MISSING", "edition.language")
    if not facts.edition_description.strip():
        add("EDITION_DESCRIPTION_MISSING", "edition.description")
    if facts.duration_ms <= 0:
        add("DURATION_INVALID", "edition.duration_ms")
    if facts.cover_asset_id is None:
        add("COVER_MISSING", "edition.cover_asset_id")
    if not facts.tracks:
        add("TRACKS_MISSING", "edition.tracks")
    for track in facts.tracks:
        if track.status != "ready" or track.asset_status != "ready":
            add("TRACK_NOT_READY", f"track[{track.position}]")
    if not any(
        window.status in {"planned", "active"} and window.ends_at > facts.now
        for window in facts.rights
    ):
        add("NO_RIGHTS_WINDOW", "edition.rights")
    if not any(
        window.status in {"planned", "active"}
        and window.ends_at > facts.now
        and window.territory_code
        for window in facts.rights
    ):
        add("RIGHTS_TERRITORY_MISSING", "edition.rights")
    return tuple(blockers)


def require_publishable(facts: PublicationFacts) -> None:
    blockers = validate_publication(facts)
    if blockers:
        raise AppError(
            "edition is not publishable",
            code="PUBLICATION_BLOCKED",
            http_status=422,
            details=[{"code": b.code, "field": b.field} for b in blockers],
        )


def active_session_required(session_state: str) -> None:
    if session_state != "active":
        raise ConflictError(
            "playback session is not active",
            code="SESSION_NOT_ACTIVE",
            details={"state": session_state},
        )
