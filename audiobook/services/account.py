"""Service: Account."""
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


class AccountService(BaseService):
    # ------------------------------------------------------------------
    # Devices, profile, account lifecycle (Lot 1 completion)
    # ------------------------------------------------------------------
    def list_devices(self, principal: auth.Principal) -> list[dict]:
        return self.repo.list_devices(principal.listener_id)

    def register_device(
        self,
        principal: auth.Principal,
        *,
        name: str = "",
        platform: str = "",
        request_id: str = "",
    ) -> dict:
        device = self.repo.register_device(
            principal.listener_id,
            name=name,
            platform=platform,
            max_devices=self.settings.max_devices_per_listener,
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="device.registered",
            target_type="device",
            target_id=str(device["id"]),
            outcome="success",
            request_id=request_id,
        )
        return device

    def revoke_device(
        self,
        principal: auth.Principal,
        device_id: UUID,
        *,
        request_id: str = "",
    ) -> bool:
        revoked = self.repo.revoke_device(principal.listener_id, device_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="device.revoked",
            target_type="device",
            target_id=str(device_id),
            outcome="success" if revoked else "failed",
            request_id=request_id,
        )
        return revoked

    def update_profile(
        self,
        principal: auth.Principal,
        *,
        display_name: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        avatar_url: str | None = None,
        bio: str | None = None,
        marketing_opt_in: bool | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        territory_code: str | None = None,
        request_id: str = "",
    ) -> dict:
        listener = self.repo.update_listener(
            principal.listener_id,
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            avatar_url=avatar_url,
            bio=bio,
            marketing_opt_in=marketing_opt_in,
            locale=locale,
            timezone=timezone,
            territory_code=territory_code,
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="listener.profile.updated",
            target_type="listener",
            target_id=str(principal.listener_id),
            outcome="success",
            request_id=request_id,
        )
        return listener

    def request_deletion(
        self, principal: auth.Principal, *, request_id: str = ""
    ) -> dict:
        listener = self.repo.request_listener_deletion(principal.listener_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="listener.deletion.requested",
            target_type="listener",
            target_id=str(principal.listener_id),
            outcome="success",
            request_id=request_id,
        )
        return listener

    def cancel_deletion(
        self, principal: auth.Principal, *, request_id: str = ""
    ) -> dict:
        listener = self.repo.cancel_listener_deletion(principal.listener_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="listener.deletion.canceled",
            target_type="listener",
            target_id=str(principal.listener_id),
            outcome="success",
            request_id=request_id,
        )
        return listener

    def export_me(self, principal: auth.Principal, *, request_id: str = "") -> dict:
        listener = self.repo.get_listener(principal.listener_id)
        preferences = self.repo.get_listener_preferences(principal.listener_id)
        library = self.repo.list_library(principal.listener_id)
        collections = self.repo.list_personal_collections(principal.listener_id)
        devices = self.repo.list_devices(principal.listener_id)
        sessions = self.repo.list_auth_sessions(principal.listener_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="listener.data.exported",
            target_type="listener",
            target_id=str(principal.listener_id),
            outcome="success",
            request_id=request_id,
        )
        return {
            "listener": listener,
            "preferences": preferences,
            "library": library,
            "personal_collections": collections,
            "devices": devices,
            "auth_sessions": sessions,
        }

    def list_auth_sessions(self, principal: auth.Principal) -> list[dict]:
        return self.repo.list_auth_sessions(principal.listener_id)

    def revoke_auth_session(
        self,
        principal: auth.Principal,
        session_id: UUID,
        *,
        request_id: str = "",
    ) -> bool:
        revoked = self.repo.revoke_auth_session(principal.listener_id, session_id)
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="auth.session.revoked",
            target_type="session",
            target_id=str(session_id),
            outcome="success" if revoked else "failed",
            request_id=request_id,
        )
        return revoked

    # ------------------------------------------------------------------
