"""Service: Entitlements."""
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


class EntitlementsService(BaseService):
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

    def revoke_entitlement(
        self,
        entitlement_id: UUID,
        *,
        reason: str = "revoked",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        entitlement = self.repo.revoke_entitlement(entitlement_id, reason=reason)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="entitlement.revoked",
            target_type="entitlement",
            target_id=str(entitlement_id),
            outcome="success",
            reason=reason,
            request_id=request_id,
        )
        return entitlement

    # ------------------------------------------------------------------
