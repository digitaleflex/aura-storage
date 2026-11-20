"""Service: Catalog."""
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


class CatalogService(BaseService):
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
