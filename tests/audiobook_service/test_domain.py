from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from audiobook.domain import (
    AccessFacts,
    EntitlementFact,
    PlaybackEvent,
    PlaybackSessionState,
    ProgressState,
    PublicationFacts,
    RightsWindowFact,
    TrackFact,
    apply_event,
    decide_access,
    validate_publication,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _session(**overrides) -> PlaybackSessionState:
    values = dict(
        id=uuid4(),
        listener_id=uuid4(),
        edition_id=uuid4(),
        state="active",
        last_client_seq=0,
        last_heartbeat_at=NOW - timedelta(seconds=5),
        active_lease_until=NOW + timedelta(seconds=60),
        version=1,
    )
    values.update(overrides)
    return PlaybackSessionState(**values)


def _progress(session: PlaybackSessionState, **overrides) -> ProgressState:
    values = dict(
        listener_id=session.listener_id,
        edition_id=session.edition_id,
        position_ms=0,
        version=1,
        updated_at=NOW - timedelta(seconds=5),
    )
    values.update(overrides)
    return ProgressState(**values)


def _event(session: PlaybackSessionState, **overrides) -> PlaybackEvent:
    values = dict(
        event_id=uuid4(),
        session_id=session.id,
        listener_id=session.listener_id,
        edition_id=session.edition_id,
        kind="heartbeat",
        client_seq=1,
        position_ms=1_000,
        duration_ms=600_000,
        playback_rate=1.0,
    )
    values.update(overrides)
    return PlaybackEvent(**values)


def test_forward_progress_applies_and_versions():
    session = _session()
    progress = _progress(session)
    result = apply_event(progress, session, _event(session), NOW)
    assert result.applied
    assert result.progress.position_ms == 1_000
    assert result.progress.version == 2
    assert result.progress.active_session_id == session.id


def test_stale_sequence_never_moves_progress():
    session = _session(last_client_seq=10)
    progress = _progress(session, position_ms=5_000, version=4)
    result = apply_event(
        progress, session, _event(session, client_seq=10, position_ms=9_000), NOW
    )
    assert not result.applied
    assert not result.conflict
    assert result.reason == "stale_sequence"
    assert result.progress.position_ms == 5_000
    assert result.progress.version == 4


def test_heartbeat_cannot_silently_rewind_but_seek_can():
    session = _session(last_client_seq=2)
    progress = _progress(session, position_ms=50_000, version=3)
    rewind = apply_event(
        progress,
        session,
        _event(session, kind="heartbeat", client_seq=3, position_ms=30_000),
        NOW,
    )
    assert not rewind.applied
    assert rewind.reason == "regressive_position"
    seek = apply_event(
        progress,
        session,
        _event(session, kind="seek", client_seq=3, position_ms=30_000),
        NOW,
    )
    assert seek.applied
    assert seek.progress.position_ms == 30_000


def test_completion_is_monotonic_and_explicit_end_wins():
    session = _session(last_client_seq=1)
    progress = _progress(session, position_ms=590_000, version=2)
    completed = apply_event(
        progress,
        session,
        _event(session, kind="ended", client_seq=2, position_ms=600_000),
        NOW,
    )
    assert completed.applied
    assert completed.progress.completed_at == NOW
    later = apply_event(
        completed.progress,
        session,
        _event(session, kind="seek", client_seq=3, position_ms=10_000),
        NOW + timedelta(seconds=1),
    )
    assert later.applied
    assert later.progress.position_ms == 10_000
    assert later.progress.completed_at == NOW


def test_paused_session_only_resumes_itself():
    session = _session(state="paused", last_client_seq=2)
    progress = _progress(session, position_ms=10_000, version=3)
    heartbeat = apply_event(
        progress, session, _event(session, kind="heartbeat", client_seq=3), NOW
    )
    assert heartbeat.conflict
    assert heartbeat.reason == "session_not_active"
    resume = apply_event(
        progress,
        session,
        _event(session, kind="resume", client_seq=3, position_ms=10_000),
        NOW,
    )
    assert resume.applied
    assert resume.session_state == "active"


def test_abandoned_session_cannot_advance_without_takeover():
    session = _session(state="abandoned")
    progress = _progress(session)
    blocked = apply_event(progress, session, _event(session), NOW)
    assert blocked.conflict
    takeover = apply_event(
        progress, session, _event(session, kind="takeover"), NOW, takeover=True
    )
    assert takeover.applied


def test_event_context_mismatch_is_rejected():
    session = _session()
    progress = _progress(session)
    other = _event(session, listener_id=uuid4())
    with pytest.raises(Exception):
        apply_event(progress, session, other, NOW)


def _rights(**overrides) -> RightsWindowFact:
    values = dict(
        id=uuid4(),
        territory_code="WORLD",
        channel="stream",
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=30),
        status="active",
    )
    values.update(overrides)
    return RightsWindowFact(**values)


def _access(**overrides) -> AccessFacts:
    values = dict(
        listener_status="active",
        edition_id=uuid4(),
        work_id=uuid4(),
        edition_status="published",
        access_model="free",
        action="stream",
        territory_code="FR",
        now=NOW,
        rights=(_rights(),),
        entitlements=(),
        asset_ready=True,
        decision_ttl_seconds=60,
        policy_version="test",
    )
    values.update(overrides)
    return AccessFacts(**values)


def test_free_access_requires_rights_and_ready_asset():
    allowed = decide_access(_access())
    assert allowed.allowed
    assert "free" in allowed.sources
    assert not decide_access(_access(asset_ready=False)).allowed
    no_rights = decide_access(_access(rights=()))
    assert not no_rights.allowed
    assert no_rights.reason_code == "NO_ACTIVE_RIGHTS"


def test_paid_access_requires_matching_entitlement():
    facts = _access(access_model="paid")
    denied = decide_access(facts)
    assert not denied.allowed
    assert denied.reason_code == "NO_ACTIVE_ENTITLEMENT"
    entitlement = EntitlementFact(
        id=uuid4(),
        source_type="purchase",
        scope_type="edition",
        scope_id=str(facts.edition_id),
        status="active",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
    )
    allowed = decide_access(
        _access(
            access_model="paid",
            edition_id=facts.edition_id,
            entitlements=(entitlement,),
        )
    )
    assert allowed.allowed
    assert any(source.startswith("entitlement:") for source in allowed.sources)


def test_territory_restriction_and_account_status_are_deny_reasons():
    restricted = _access(rights=(_rights(territory_code="US"),))
    denied = decide_access(restricted)
    assert denied.reason_code == "TERRITORY_RESTRICTED"
    suspended = decide_access(_access(listener_status="suspended"))
    assert suspended.reason_code == "ACCOUNT_SUSPENDED"


def test_download_is_disabled_until_offline_grants_exist():
    decision = decide_access(_access(action="download"))
    assert not decision.allowed
    assert decision.reason_code == "DOWNLOAD_NOT_ENABLED"


def _publication(**overrides) -> PublicationFacts:
    values = dict(
        work_id=uuid4(),
        work_title="Le Livre",
        work_language="fr",
        work_status="approved",
        authors=("Auteur",),
        narrators=("Narratrice",),
        edition_title="Le Livre",
        edition_language="fr",
        edition_description="Description",
        duration_ms=600_000,
        cover_asset_id=uuid4(),
        tracks=(TrackFact(uuid4(), 1, "ready", "ready"),),
        rights=(_rights(),),
        now=NOW,
    )
    values.update(overrides)
    return PublicationFacts(**values)


def test_publication_accepts_complete_free_book():
    assert validate_publication(_publication()) == ()


def test_publication_reports_all_blockers():
    blockers = validate_publication(
        _publication(
            work_status="draft",
            narrators=(),
            cover_asset_id=None,
            tracks=(TrackFact(uuid4(), 1, "pending", None),),
            rights=(),
        )
    )
    codes = {b.code for b in blockers}
    assert {
        "WORK_NOT_APPROVED",
        "NARRATOR_MISSING",
        "COVER_MISSING",
        "TRACK_NOT_READY",
        "NO_RIGHTS_WINDOW",
    } <= codes
