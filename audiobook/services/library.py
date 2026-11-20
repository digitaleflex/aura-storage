"""Service: Library."""
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


class LibraryService(BaseService):
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
