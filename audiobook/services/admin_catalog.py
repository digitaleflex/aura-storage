"""Service: AdminCatalog."""
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


class AdminCatalogService(BaseService):
    # ------------------------------------------------------------------
    # Admin/catalog completion (Lot 1)
    # ------------------------------------------------------------------
    def suspend_edition(
        self, edition_id: UUID, *, actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        edition = self.repo.suspend_edition(edition_id)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.edition.suspended",
            target_type="edition",
            target_id=str(edition_id),
            outcome="success",
            request_id=request_id,
        )
        return edition

    def unsuspend_edition(
        self, edition_id: UUID, *, actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        edition = self.repo.unsuspend_edition(edition_id)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.edition.unsuspended",
            target_type="edition",
            target_id=str(edition_id),
            outcome="success",
            request_id=request_id,
        )
        return edition

    def create_category(
        self, *, slug: str, name: str, description: str = "", actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        category = self.repo.create_category(slug, name, description)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.category.created",
            target_type="category",
            target_id=str(category["id"]),
            outcome="success",
            request_id=request_id,
        )
        return category

    def list_categories(self) -> list[dict]:
        return self.repo.list_categories()

    def create_editorial_collection(
        self, *, slug: str, title: str, description: str = "", actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        collection = self.repo.create_editorial_collection(slug, title, description)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.editorial_collection.created",
            target_type="editorial_collection",
            target_id=str(collection["id"]),
            outcome="success",
            request_id=request_id,
        )
        return collection

    def add_editorial_collection_item(
        self, collection_id: UUID, edition_id: UUID, position: int = 0
    ) -> None:
        self.repo.add_editorial_collection_item(collection_id, edition_id, position)

    def publish_editorial_collection(
        self, collection_id: UUID, *, actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        collection = self.repo.publish_editorial_collection(collection_id)
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="catalog.editorial_collection.published",
            target_type="editorial_collection",
            target_id=str(collection_id),
            outcome="success",
            request_id=request_id,
        )
        return collection

    def list_editorial_collections(self, *, published_only: bool = False) -> list[dict]:
        return self.repo.list_editorial_collections(published_only=published_only)

    # ------------------------------------------------------------------
