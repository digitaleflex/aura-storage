"""Service: PersonalCollections."""
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


class PersonalCollectionsService(BaseService):
    # ------------------------------------------------------------------
    # Personal collections (Lot 1)
    # ------------------------------------------------------------------
    def create_personal_collection(
        self,
        principal: auth.Principal,
        *,
        title: str,
        description: str = "",
        request_id: str = "",
    ) -> dict:
        collection = self.repo.create_personal_collection(
            principal.listener_id, title, description
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="personal_collection.created",
            target_type="personal_collection",
            target_id=str(collection["id"]),
            outcome="success",
            request_id=request_id,
        )
        return collection

    def list_personal_collections(self, principal: auth.Principal) -> list[dict]:
        return self.repo.list_personal_collections(principal.listener_id)

    def get_personal_collection(
        self, principal: auth.Principal, collection_id: UUID
    ) -> dict:
        collection = self.repo.get_personal_collection(
            principal.listener_id, collection_id
        )
        if collection is None:
            raise NotFoundError(
                "personal collection not found", code="COLLECTION_NOT_FOUND"
            )
        return collection

    def add_personal_collection_item(
        self,
        principal: auth.Principal,
        collection_id: UUID,
        *,
        work_id: UUID,
        position: int = 0,
        request_id: str = "",
    ) -> dict:
        item = self.repo.add_personal_collection_item(
            principal.listener_id, collection_id, work_id, position
        )
        if item is None:
            raise NotFoundError(
                "personal collection not found", code="COLLECTION_NOT_FOUND"
            )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="personal_collection.item_added",
            target_type="personal_collection",
            target_id=str(collection_id),
            outcome="success",
            request_id=request_id,
        )
        return item

    def remove_personal_collection_item(
        self,
        principal: auth.Principal,
        collection_id: UUID,
        work_id: UUID,
        *,
        request_id: str = "",
    ) -> bool:
        removed = self.repo.remove_personal_collection_item(
            principal.listener_id, collection_id, work_id
        )
        if not removed:
            # Could be missing collection or missing item; keep response 404-safe.
            if self.repo.get_personal_collection(principal.listener_id, collection_id) is None:
                raise NotFoundError(
                    "personal collection not found", code="COLLECTION_NOT_FOUND"
                )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="personal_collection.item_removed",
            target_type="personal_collection",
            target_id=str(collection_id),
            outcome="success" if removed else "failed",
            request_id=request_id,
        )
        return removed

    def delete_personal_collection(
        self,
        principal: auth.Principal,
        collection_id: UUID,
        *,
        request_id: str = "",
    ) -> bool:
        deleted = self.repo.delete_personal_collection(
            principal.listener_id, collection_id
        )
        self.repo.record_audit(
            actor_type="listener",
            actor_id=str(principal.listener_id),
            action="personal_collection.deleted",
            target_type="personal_collection",
            target_id=str(collection_id),
            outcome="success" if deleted else "failed",
            request_id=request_id,
        )
        return deleted

    # ------------------------------------------------------------------
