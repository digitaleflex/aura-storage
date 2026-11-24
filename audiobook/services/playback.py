"""Service: Playback."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from .. import auth, google_oidc
from ..domain import (
    AccessDecision,
    AccessFacts,
    EntitlementFact,
    PlaybackEvent,
    PublicationFacts,
    RightsWindowFact,
    TrackFact,
    decide_access,
    require_publishable,
    validate_publication,
)
from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..ids import new_id, slugify, utcnow
from .base import BaseService


class PlaybackService(BaseService):
    # ------------------------------------------------------------------
    # Access decisions and playback
    # ------------------------------------------------------------------
    def evaluate_access(
        self,
        principal: auth.Principal,
        edition_id: UUID,
        *,
        action: str = "stream",
        territory_code: str | None = None,
        device_id: UUID | None = None,
        request_id: str = "",
    ) -> tuple[AccessDecision, dict]:
        bundle = self.repo.get_edition_bundle(edition_id)
        if bundle is None:
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        edition = bundle["edition"]
        resolved_territory = (
            territory_code
            or str(principal.listener.get("territory_code") or "WORLD")
        )
        device_authorized: bool | None = None
        if device_id is not None:
            device = self.repo.get_device(device_id)
            device_authorized = bool(
                device
                and device["listener_id"] == principal.listener_id
                and device["status"] == "active"
            )
        entitlements = self.repo.list_entitlements(
            principal.listener_id,
            now=utcnow(),
            edition_id=edition_id,
            work_id=edition["work_id"],
        )
        facts = AccessFacts(
            listener_status=principal.listener["status"],
            edition_id=edition_id,
            work_id=edition["work_id"],
            edition_status=edition["status"],
            access_model=edition["access_model"],
            action=action,
            territory_code=resolved_territory,
            now=utcnow(),
            rights=tuple(
                RightsWindowFact(
                    id=r["id"],
                    territory_code=r["territory_code"],
                    channel=r["channel"],
                    starts_at=r["starts_at"],
                    ends_at=r["ends_at"],
                    status=r["status"],
                )
                for r in bundle["rights"]
            ),
            entitlements=tuple(
                EntitlementFact(
                    id=e["id"],
                    source_type=e["source_type"],
                    scope_type=e["scope_type"],
                    scope_id=e["scope_id"],
                    status=e["status"],
                    valid_from=e["valid_from"],
                    valid_until=e["valid_until"],
                )
                for e in entitlements
            ),
            asset_ready=(
                any(
                    t["status"] == "ready" and t["asset_status"] == "ready"
                    for t in bundle["tracks"]
                )
                if str(edition.get("publication_kind") or "audiobook") == "audiobook"
                else any(
                    asset["asset_status"] == "ready"
                    for asset in bundle.get("ebook_assets", [])
                )
            ),
            device_authorized=device_authorized,
            decision_ttl_seconds=self.settings.access_decision_ttl_seconds,
            policy_version=self.settings.policy_version,
        )
        decision = decide_access(facts)
        self.repo.record_access_decision(
            listener_id=principal.listener_id,
            edition_id=edition_id,
            action=action,
            decision="allow" if decision.allowed else "deny",
            reason_code=decision.reason_code,
            sources=list(decision.sources),
            policy_version=decision.policy_version,
            territory_code=resolved_territory,
            decided_at=facts.now,
            expires_at=decision.expires_at,
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action=f"access.{action}",
            target_type="edition",
            target_id=str(edition_id),
            outcome="success" if decision.allowed else "denied",
            reason=decision.reason_code,
            request_id=request_id,
        )
        return decision, bundle

    def authorize_track(
        self,
        principal: auth.Principal,
        edition_id: UUID,
        track_id: UUID,
        *,
        territory_code: str | None = None,
        device_id: UUID | None = None,
        request_id: str = "",
    ) -> dict:
        decision, bundle = self.evaluate_access(
            principal,
            edition_id,
            action="stream",
            territory_code=territory_code,
            device_id=device_id,
            request_id=request_id,
        )
        if not decision.allowed:
            raise ForbiddenError(
                "access denied",
                code=decision.reason_code,
                details={"reason_code": decision.reason_code},
            )
        track = next((t for t in bundle["tracks"] if t["id"] == track_id), None)
        if track is None:
            raise NotFoundError("track not found", code="TRACK_NOT_FOUND")
        if track["status"] != "ready" or track["asset_status"] != "ready":
            raise ConflictError("track is not playable", code="TRACK_UNAVAILABLE")
        asset = {
            "storage_object_id": track["storage_object_id"],
            "content_type": track["content_type"],
        }
        issued = self.storage.presigned_playback_url(asset)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="playback.url.issued",
            target_type="track",
            target_id=str(track_id),
            outcome="success",
            request_id=request_id,
        )
        return {
            "edition_id": edition_id,
            "track_id": track_id,
            "url": issued.url,
            "expires_at": issued.expires_at,
            "content_type": issued.content_type,
            "decision": decision,
        }

    def authorize_ebook(
        self,
        principal: auth.Principal,
        edition_id: UUID,
        *,
        territory_code: str | None = None,
        device_id: UUID | None = None,
        request_id: str = "",
    ) -> dict:
        decision, bundle = self.evaluate_access(
            principal,
            edition_id,
            action="stream",
            territory_code=territory_code,
            device_id=device_id,
            request_id=request_id,
        )
        if str(bundle["edition"].get("publication_kind") or "audiobook") != "ebook":
            raise ValidationError("edition is not an ebook", code="EDITION_NOT_EBOOK")
        if not decision.allowed:
            raise ForbiddenError(
                "access denied",
                code=decision.reason_code,
                details={"reason_code": decision.reason_code},
            )
        asset = next(
            (
                item
                for item in bundle.get("ebook_assets", [])
                if item["asset_status"] == "ready"
            ),
            None,
        )
        if asset is None:
            raise ConflictError("ebook asset is not ready", code="EBOOK_ASSET_UNAVAILABLE")
        issued = self.storage.presigned_playback_url(asset)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="ebook.url.issued",
            target_type="ebook_asset",
            target_id=str(asset["id"]),
            outcome="success",
            request_id=request_id,
        )
        return {
            "edition_id": edition_id,
            "asset_id": asset["id"],
            "url": issued.url,
            "expires_at": issued.expires_at,
            "content_type": issued.content_type,
            "decision": decision,
        }

    def start_session(
        self,
        principal: auth.Principal,
        *,
        edition_id: UUID,
        device_id: UUID | None = None,
        takeover: bool = False,
        territory_code: str | None = None,
        request_id: str = "",
    ) -> dict:
        decision, _ = self.evaluate_access(
            principal,
            edition_id,
            action="stream",
            territory_code=territory_code,
            device_id=device_id,
            request_id=request_id,
        )
        if not decision.allowed:
            raise ForbiddenError(
                "access denied",
                code=decision.reason_code,
                details={"reason_code": decision.reason_code},
            )
        if device_id is not None:
            device = self.repo.get_device(device_id)
            if device is None or device["listener_id"] != principal.listener_id:
                raise NotFoundError("device not found", code="DEVICE_NOT_FOUND")
            if device["status"] != "active":
                raise ForbiddenError(
                    "device is not active", code="DEVICE_NOT_ACTIVE"
                )
        session = self.repo.start_playback_session(
            principal.listener_id,
            edition_id,
            device_id=device_id,
            lease_seconds=self.settings.playback_lease_seconds,
            now=utcnow(),
            takeover=takeover,
            max_simultaneous=self.settings.max_simultaneous_playback_sessions,
        )
        progress = self.repo.get_progress(principal.listener_id, edition_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="playback.session.started",
            target_type="session",
            target_id=str(session["id"]),
            outcome="success",
            request_id=request_id,
        )
        return {
            "session": session,
            "progress": progress,
            "decision": decision,
        }

    def append_event(
        self,
        principal: auth.Principal,
        session_id: UUID,
        *,
        event_id: UUID | None = None,
        client_seq: int,
        kind: str,
        position_ms: int,
        track_id: UUID | None = None,
        duration_ms: int | None = None,
        occurred_at_client: datetime | None = None,
        playback_rate: float = 1.0,
        request_id: str = "",
    ) -> dict:
        session = self.repo.get_session(session_id)
        if session is None or session["listener_id"] != principal.listener_id:
            raise NotFoundError("playback session not found", code="SESSION_NOT_FOUND")
        event = PlaybackEvent(
            event_id=event_id or new_id(),
            session_id=session_id,
            listener_id=principal.listener_id,
            edition_id=session["edition_id"],
            kind=kind,
            client_seq=client_seq,
            position_ms=position_ms,
            track_id=track_id,
            duration_ms=duration_ms,
            occurred_at_client=occurred_at_client,
            playback_rate=playback_rate,
        )
        result = self.repo.append_event(
            principal.listener_id,
            session_id,
            event,
            now=utcnow(),
            lease_seconds=self.settings.playback_lease_seconds,
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="playback.event",
            target_type="session",
            target_id=str(session_id),
            outcome="success" if result["applied"] else "denied",
            reason=result["reason"],
            request_id=request_id,
        )
        return result

    def get_progress(
        self, principal: auth.Principal, edition_id: UUID
    ) -> dict:
        edition = self.repo.get_edition(edition_id)
        if edition is None:
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        progress = self.repo.get_progress(principal.listener_id, edition_id)
        if progress is None:
            progress = {
                "listener_id": principal.listener_id,
                "edition_id": edition_id,
                "position_ms": 0,
                "track_id": None,
                "active_session_id": None,
                "last_event_id": None,
                "version": 0,
                "completed_at": None,
                "last_completed_position_ms": None,
                "updated_at": None,
            }
        active = self.repo.get_active_session(principal.listener_id, edition_id)
        return {"progress": progress, "active_session_id": active["id"] if active else None}

    # ------------------------------------------------------------------
