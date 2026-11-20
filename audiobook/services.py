"""Application services: orchestration of domain rules, persistence and storage."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from . import auth, google_oidc
from .config import Settings
from .domain import (
    AccessDecision,
    AccessFacts,
    EntitlementFact,
    PlaybackEvent,
    PublicationFacts,
    RightsWindowFact,
    TrackFact,
    decide_access,
    require_publishable,
)
from .errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .ids import new_id, slugify, utcnow
from .repository import Repository
from .storage import StoragePort


class AudiobookService:
    def __init__(
        self, repo: Repository, settings: Settings, storage: StoragePort
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.storage = storage

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def dev_login(
        self, email: str, display_name: str = "", *, request_id: str = ""
    ) -> dict:
        if not self.settings.dev_auth:
            raise ForbiddenError(
                "development authentication is disabled",
                code="DEV_AUTH_DISABLED",
            )
        listener = self.repo.create_listener(email, display_name)
        if listener["status"] != "active":
            raise ForbiddenError("listener account is not active", code="ACCOUNT_INACTIVE")
        issued = auth.issue_session(self.repo, listener["id"], self.settings)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(listener["id"]),
            action="auth.dev_login",
            target_type="listener",
            target_id=str(listener["id"]),
            outcome="success",
            request_id=request_id,
        )
        return {
            "listener": listener,
            "token": issued.token,
            "csrf_token": issued.csrf_token,
            "expires_at": issued.expires_at,
        }

    def google_login(
        self, claims: dict, *, request_id: str = ""
    ) -> tuple[dict, auth.IssuedSession]:
        subject = str(claims["sub"])
        email = str(claims["email"]).strip()
        listener = self.repo.get_listener_by_identity("google", subject)
        if listener is None:
            listener = self.repo.get_listener_by_email(email)
            if listener is None:
                listener = self.repo.create_listener(
                    email, str(claims.get("name") or "")
                )
            self.repo.create_identity(listener["id"], "google", subject)
            listener = self.repo.get_listener_by_identity("google", subject) or listener
        if listener["status"] != "active":
            raise ForbiddenError("listener account is not active", code="ACCOUNT_INACTIVE")
        issued = auth.issue_session(self.repo, listener["id"], self.settings)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(listener["id"]),
            action="auth.google_login",
            target_type="listener",
            target_id=str(listener["id"]),
            outcome="success",
            request_id=request_id,
        )
        return listener, issued

    def authenticate(self, raw_token: str, *, source: str) -> auth.Principal:
        return auth.authenticate(self.repo, raw_token, source=source)

    def logout(self, principal: auth.Principal, *, request_id: str = "") -> None:
        self.repo.revoke_session(principal.session_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="auth.logout",
            target_type="session",
            target_id=str(principal.session_id),
            outcome="success",
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------
    def create_work(
        self,
        *,
        title: str,
        language: str,
        description: str = "",
        publication_year: int | None = None,
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        work = self.repo.create_work(title, language, description, publication_year)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.work.created",
            target_type="work",
            target_id=str(work["id"]),
            outcome="success",
            request_id=request_id,
        )
        return work

    def create_contributor(
        self,
        *,
        work_id: UUID,
        name: str,
        role: str,
        position: int = 0,
        sort_name: str = "",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        contributor = self.repo.create_contributor(name, sort_name)
        self.repo.link_contributor(work_id, contributor["id"], role, position)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.contributor.linked",
            target_type="work",
            target_id=str(work_id),
            outcome="success",
            request_id=request_id,
        )
        return contributor

    def approve_work(
        self, work_id: UUID, *, actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        work = self.repo.set_work_status(work_id, "approved")
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.work.approved",
            target_type="work",
            target_id=str(work_id),
            outcome="success",
            request_id=request_id,
        )
        return work

    def create_edition(
        self,
        *,
        work_id: UUID,
        title: str,
        language: str,
        description: str,
        duration_ms: int,
        slug: str | None = None,
        publisher: str = "",
        publication_date=None,
        cover_asset_id: UUID | None = None,
        access_model: str = "free",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        edition_id = new_id()
        chosen_slug = slug or slugify(title or "livre", str(edition_id))
        edition = self.repo.create_edition(
            work_id,
            title=title,
            language=language,
            slug=chosen_slug,
            description=description,
            duration_ms=duration_ms,
            publisher=publisher,
            publication_date=publication_date,
            cover_asset_id=cover_asset_id,
            access_model=access_model,
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.edition.created",
            target_type="edition",
            target_id=str(edition["id"]),
            outcome="success",
            request_id=request_id,
        )
        return edition

    def _audit_admin_change(
        self, *, actor_id: str, request_id: str, action: str,
        target_type: str, target: dict,
    ) -> None:
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target["id"]),
            outcome="success",
            request_id=request_id,
        )

    def create_asset(
        self, *, actor_id: str = "admin", request_id: str = "", **kwargs: Any,
    ) -> dict:
        asset = self.repo.create_asset(**kwargs)
        self._audit_admin_change(
            actor_id=actor_id, request_id=request_id,
            action="catalog.asset.created", target_type="asset", target=asset,
        )
        return asset

    def create_track(
        self, edition_id: UUID, *, actor_id: str = "admin",
        request_id: str = "", **kwargs: Any,
    ) -> dict:
        track = self.repo.create_track(edition_id, **kwargs)
        self._audit_admin_change(
            actor_id=actor_id, request_id=request_id,
            action="catalog.track.created", target_type="track", target=track,
        )
        return track

    def create_chapter(
        self, edition_id: UUID, *, actor_id: str = "admin",
        request_id: str = "", **kwargs: Any,
    ) -> dict:
        chapter = self.repo.create_chapter(edition_id, **kwargs)
        self._audit_admin_change(
            actor_id=actor_id, request_id=request_id,
            action="catalog.chapter.created", target_type="chapter", target=chapter,
        )
        return chapter

    def create_rights_window(
        self, edition_id: UUID, *, actor_id: str = "admin",
        request_id: str = "", **kwargs: Any,
    ) -> dict:
        rights = self.repo.create_rights_window(edition_id, **kwargs)
        self._audit_admin_change(
            actor_id=actor_id, request_id=request_id,
            action="catalog.rights.created", target_type="rights_window", target=rights,
        )
        return rights

    def publish_edition(
        self,
        edition_id: UUID,
        *,
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        bundle = self.repo.get_edition_bundle(edition_id)
        if bundle is None:
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        edition = bundle["edition"]
        contributors = bundle["contributors"]
        facts = PublicationFacts(
            work_id=edition["work_id"],
            work_title=str(edition["work_title"]),
            work_language=str(edition["work_language"]),
            work_status=str(edition["work_status"]),
            authors=tuple(
                c["name"] for c in contributors if c["role"] == "author"
            ),
            narrators=tuple(
                c["name"] for c in contributors if c["role"] == "narrator"
            ),
            edition_title=str(edition["title"]),
            edition_language=str(edition["language"]),
            edition_description=str(edition["description"]),
            duration_ms=int(edition["duration_ms"]),
            cover_asset_id=edition["cover_asset_id"],
            tracks=tuple(
                TrackFact(
                    id=t["id"],
                    position=int(t["position"]),
                    status=t["status"],
                    asset_status=t["asset_status"],
                )
                for t in bundle["tracks"]
            ),
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
            now=utcnow(),
        )
        try:
            require_publishable(facts)
        except Exception as exc:
            self.repo.record_audit(
                actor_type="admin",
                actor_id=actor_id,
                action="catalog.edition.publish",
                target_type="edition",
                target_id=str(edition_id),
                outcome="denied",
                reason=getattr(exc, "code", "PUBLICATION_BLOCKED"),
                request_id=request_id,
            )
            raise
        published = self.repo.publish_edition(edition_id)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.edition.publish",
            target_type="edition",
            target_id=str(edition_id),
            outcome="success",
            request_id=request_id,
        )
        return published

    def list_catalog(
        self, *, language: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        rows = self.repo.list_catalog(language=language, limit=limit, offset=offset)
        return [self._public_edition_row(row) for row in rows]

    def get_public_edition(self, edition_id: UUID) -> dict:
        bundle = self.repo.get_edition_bundle(edition_id)
        if bundle is None or bundle["edition"]["status"] != "published":
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        return self._public_bundle(bundle)

    def get_admin_edition(self, edition_id: UUID) -> dict:
        bundle = self.repo.get_edition_bundle(edition_id)
        if bundle is None:
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        return bundle

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------
    def add_to_library(
        self,
        principal: auth.Principal,
        *,
        work_id: UUID,
        preferred_edition_id: UUID | None = None,
        source: str = "manual",
        request_id: str = "",
    ) -> dict:
        if self.repo.get_work(work_id) is None:
            raise NotFoundError("work not found", code="WORK_NOT_FOUND")
        if preferred_edition_id is not None:
            bundle = self.repo.get_edition_bundle(preferred_edition_id)
            if bundle is None or bundle["edition"]["work_id"] != work_id:
                raise ValidationError(
                    "preferred edition does not belong to this work",
                    code="EDITION_WORK_MISMATCH",
                )
        else:
            latest = self.repo.latest_published_edition(work_id)
            preferred_edition_id = latest["id"] if latest else None
        entry = self.repo.add_library_entry(
            principal.listener_id,
            work_id,
            preferred_edition_id=preferred_edition_id,
            source=source,
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="library.add",
            target_type="work",
            target_id=str(work_id),
            outcome="success",
            request_id=request_id,
        )
        return entry

    def remove_from_library(
        self,
        principal: auth.Principal,
        work_id: UUID,
        *,
        request_id: str = "",
    ) -> bool:
        removed = self.repo.remove_library_entry(principal.listener_id, work_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="library.remove",
            target_type="work",
            target_id=str(work_id),
            outcome="success" if removed else "failed",
            request_id=request_id,
        )
        return removed

    def list_library(self, principal: auth.Principal) -> list[dict]:
        return self.repo.list_library(principal.listener_id)

    def set_favorite(
        self,
        principal: auth.Principal,
        work_id: UUID,
        favorite: bool,
        *,
        request_id: str = "",
    ) -> bool:
        result = self.repo.set_favorite(principal.listener_id, work_id, favorite)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="library.favorite" if favorite else "library.unfavorite",
            target_type="work",
            target_id=str(work_id),
            outcome="success",
            request_id=request_id,
        )
        return result

    # ------------------------------------------------------------------
    # Access decisions and playback
    # ------------------------------------------------------------------
    def evaluate_access(
        self,
        principal: auth.Principal,
        edition_id: UUID,
        *,
        action: str = "stream",
        territory_code: str = "WORLD",
        request_id: str = "",
    ) -> tuple[AccessDecision, dict]:
        bundle = self.repo.get_edition_bundle(edition_id)
        if bundle is None:
            raise NotFoundError("edition not found", code="EDITION_NOT_FOUND")
        edition = bundle["edition"]
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
            territory_code=territory_code,
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
            asset_ready=any(
                t["status"] == "ready" and t["asset_status"] == "ready"
                for t in bundle["tracks"]
            ),
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
            territory_code=territory_code,
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
        territory_code: str = "WORLD",
        request_id: str = "",
    ) -> dict:
        decision, bundle = self.evaluate_access(
            principal,
            edition_id,
            action="stream",
            territory_code=territory_code,
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

    def start_session(
        self,
        principal: auth.Principal,
        *,
        edition_id: UUID,
        device_id: UUID | None = None,
        takeover: bool = False,
        territory_code: str = "WORLD",
        request_id: str = "",
    ) -> dict:
        decision, _ = self.evaluate_access(
            principal,
            edition_id,
            action="stream",
            territory_code=territory_code,
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
    # Admin entitlements (Lot 1 manual grants; Lot 3 replaces with payment)
    # ------------------------------------------------------------------
    def grant_entitlement(
        self,
        *,
        listener_id: UUID,
        source_type: str,
        source_id: str,
        scope_type: str,
        scope_id: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        status: str = "active",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        entitlement = self.repo.create_entitlement(
            listener_id,
            source_type=source_type,
            source_id=source_id,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_from=valid_from or utcnow(),
            valid_until=valid_until,
            status=status,
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="entitlement.grant",
            target_type="listener",
            target_id=str(listener_id),
            outcome="success",
            request_id=request_id,
        )
        return entitlement

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _public_edition_row(row: dict) -> dict:
        return {
            "id": row["id"],
            "work_id": row["work_id"],
            "title": row["title"] or row["work_title"],
            "language": row["language"] or row["work_language"],
            "description": row["description"],
            "slug": row["slug"],
            "duration_ms": int(row["duration_ms"]),
            "access_model": row["access_model"],
            "published_at": row["published_at"],
            "cover_asset_id": row["cover_asset_id"],
            "track_count": int(row.get("track_count", 0)),
            "ready_track_count": int(row.get("ready_track_count", 0)),
        }

    @classmethod
    def _public_bundle(cls, bundle: dict) -> dict:
        edition = bundle["edition"]
        contributors = bundle["contributors"]
        return {
            "edition": cls._public_edition_row(edition),
            "authors": [
                {"id": c["id"], "name": c["name"], "position": c["position"]}
                for c in contributors
                if c["role"] == "author"
            ],
            "narrators": [
                {"id": c["id"], "name": c["name"], "position": c["position"]}
                for c in contributors
                if c["role"] == "narrator"
            ],
            "tracks": [
                {
                    "id": t["id"],
                    "position": t["position"],
                    "title": t["title"],
                    "start_ms": int(t["start_ms"]),
                    "end_ms": int(t["end_ms"]),
                    "duration_ms": int(t["end_ms"]) - int(t["start_ms"]),
                    "status": t["status"],
                }
                for t in bundle["tracks"]
            ],
            "chapters": [
                {
                    "id": c["id"],
                    "position": c["position"],
                    "title": c["title"],
                    "start_ms": int(c["start_ms"]),
                    "end_ms": int(c["end_ms"]),
                }
                for c in bundle["chapters"]
            ],
        }
