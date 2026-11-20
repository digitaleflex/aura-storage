"""Service: Analytics."""
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


class AnalyticsService(BaseService):
    # ------------------------------------------------------------------
    # History, stats, dashboard, contracts (Lot 2)
    # ------------------------------------------------------------------
    def listening_history(
        self, principal: auth.Principal, *, limit: int = 50
    ) -> list[dict]:
        return self.repo.listening_history(principal.listener_id, limit=limit)

    def listening_stats(self, principal: auth.Principal) -> dict:
        return self.repo.listening_stats(principal.listener_id)

    def access_refusal_dashboard(self, *, limit: int = 200) -> dict:
        return self.repo.access_refusal_dashboard(limit=limit)

    def create_contract(
        self,
        *,
        name: str,
        licensor: str = "",
        territory_scope: str = "WORLD",
        starts_at: datetime,
        ends_at: datetime,
        status: str = "draft",
        notes: str = "",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        contract = self.repo.create_contract(
            name=name,
            licensor=licensor,
            territory_scope=territory_scope,
            starts_at=starts_at,
            ends_at=ends_at,
            status=status,
            notes=notes,
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="rights.contract.created",
            target_type="contract",
            target_id=str(contract["id"]),
            outcome="success",
            request_id=request_id,
        )
        return contract

    def list_contracts(self) -> list[dict]:
        return self.repo.list_contracts()

    # ------------------------------------------------------------------
