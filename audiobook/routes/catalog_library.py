from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, google_oidc
from ..config import Settings
from ..deps import decision_payload, get_admin, get_principal, get_service, request_id, set_session_cookies
from ..errors import ForbiddenError, NotFoundError, UnauthorizedError, UnavailableError
from ..ids import constant_time_equal, new_token
from ..schemas import (
    AssetIn, CategoryIn, ChapterIn, ContractIn, ContributorIn, DevLoginIn, DeviceIn, EditionIn,
    EditorialCollectionIn, EditorialCollectionItemIn, EntitlementIn, EntitlementRevokeIn, EventIn,
    LibraryIn, PersonalCollectionIn, PersonalCollectionItemIn, ProfileIn, RightsIn, SessionIn,
    TrackIn, WorkIn,
)


def register_catalog_library_routes(app):
    # ------------------------------------------------------------------
    # Public catalog
    # ------------------------------------------------------------------
    @app.get("/api/v1/catalog")
    def catalog(
        request: Request,
        language: str | None = Query(default=None, max_length=16),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        items = request.app.state.service.list_catalog(
            language=language, limit=limit, offset=offset
        )
        return {"items": items, "limit": limit, "offset": offset}

    @app.get("/api/v1/catalog/{edition_id}")
    def catalog_item(edition_id: UUID, request: Request) -> dict:
        return request.app.state.service.get_public_edition(edition_id)

    @app.get("/api/v1/categories")
    def categories(request: Request) -> dict:
        return {"items": request.app.state.service.list_categories()}

    @app.get("/api/v1/editorial-collections")
    def editorial_collections(request: Request) -> dict:
        return {
            "items": request.app.state.service.list_editorial_collections(
                published_only=True
            )
        }

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------
    @app.get("/api/v1/library")
    def library(
        request: Request, principal: auth.Principal = Depends(get_principal)
    ) -> dict:
        return {
            "items": request.app.state.service.list_library(principal)
        }

    @app.post("/api/v1/library")
    def add_library(
        body: LibraryIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.add_to_library(
            principal,
            work_id=body.work_id,
            preferred_edition_id=body.preferred_edition_id,
            source=body.source,
            request_id=request_id(request),
        )

    @app.delete("/api/v1/library/{work_id}")
    def remove_library(
        work_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        removed = request.app.state.service.remove_from_library(
            principal, work_id, request_id=request_id(request)
        )
        return {"removed": removed}

    @app.put("/api/v1/favorites/{work_id}")
    def favorite(
        work_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return {
            "favorite": request.app.state.service.set_favorite(
                principal, work_id, True, request_id=request_id(request)
            )
        }

    @app.delete("/api/v1/favorites/{work_id}")
    def unfavorite(
        work_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return {
            "favorite": request.app.state.service.set_favorite(
                principal, work_id, False, request_id=request_id(request)
            )
        }

    @app.get("/api/v1/personal-collections")
    def list_personal_collections(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return {
            "items": request.app.state.service.list_personal_collections(principal)
        }

    @app.post("/api/v1/personal-collections")
    def create_personal_collection(
        body: PersonalCollectionIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.create_personal_collection(
            principal,
            title=body.title,
            description=body.description,
            request_id=request_id(request),
        )

    @app.get("/api/v1/personal-collections/{collection_id}")
    def get_personal_collection(
        collection_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.get_personal_collection(
            principal, collection_id
        )

    @app.post("/api/v1/personal-collections/{collection_id}/items")
    def add_personal_collection_item(
        collection_id: UUID,
        body: PersonalCollectionItemIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.add_personal_collection_item(
            principal,
            collection_id,
            work_id=body.work_id,
            position=body.position,
            request_id=request_id(request),
        )

    @app.delete("/api/v1/personal-collections/{collection_id}/items/{work_id}")
    def remove_personal_collection_item(
        collection_id: UUID,
        work_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        removed = request.app.state.service.remove_personal_collection_item(
            principal,
            collection_id,
            work_id,
            request_id=request_id(request),
        )
        return {"removed": removed}

    @app.delete("/api/v1/personal-collections/{collection_id}")
    def delete_personal_collection(
        collection_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        deleted = request.app.state.service.delete_personal_collection(
            principal, collection_id, request_id=request_id(request)
        )
        if not deleted:
            raise NotFoundError(
                "personal collection not found", code="COLLECTION_NOT_FOUND"
            )
        return {"deleted": True}

