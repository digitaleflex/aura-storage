"""Service: Auth."""
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


class AuthService(BaseService):
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
