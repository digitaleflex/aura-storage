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


def register_admin_routes(app):
    # ------------------------------------------------------------------
    # Admin (bootstrap token until SSO lands; never enabled without a token)
    # ------------------------------------------------------------------
    @app.post("/api/v1/admin/works")
    def admin_create_work(
        body: WorkIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_work(
            title=body.title,
            language=body.language,
            description=body.description,
            publication_year=body.publication_year,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/works/{work_id}/contributors")
    def admin_add_contributor(
        work_id: UUID,
        body: ContributorIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_contributor(
            work_id=work_id,
            name=body.name,
            role=body.role,
            position=body.position,
            sort_name=body.sort_name,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/works/{work_id}/approve")
    def admin_approve_work(
        work_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.approve_work(
            work_id, actor_id=admin["id"], request_id=request_id(request)
        )

    @app.post("/api/v1/admin/editions")
    def admin_create_edition(
        body: EditionIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_edition(
            work_id=body.work_id,
            title=body.title,
            language=body.language,
            description=body.description,
            duration_ms=body.duration_ms,
            slug=body.slug,
            publisher=body.publisher,
            publication_date=body.publication_date,
            cover_asset_id=body.cover_asset_id,
            access_model=body.access_model,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/assets")
    def admin_create_asset(
        body: AssetIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_asset(
            **body.model_dump(),
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/editions/{edition_id}/tracks")
    def admin_create_track(
        edition_id: UUID,
        body: TrackIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_track(
            edition_id, **body.model_dump(),
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/editions/{edition_id}/chapters")
    def admin_create_chapter(
        edition_id: UUID,
        body: ChapterIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_chapter(
            edition_id, **body.model_dump(),
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/editions/{edition_id}/rights")
    def admin_create_rights(
        edition_id: UUID,
        body: RightsIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_rights_window(
            edition_id, **body.model_dump(),
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/editions/{edition_id}/publish")
    def admin_publish(
        edition_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.publish_edition(
            edition_id, actor_id=admin["id"], request_id=request_id(request)
        )

    @app.post("/api/v1/admin/editions/{edition_id}/suspend")
    def admin_suspend(
        edition_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.suspend_edition(
            edition_id, actor_id=admin["id"], request_id=request_id(request)
        )

    @app.post("/api/v1/admin/editions/{edition_id}/unsuspend")
    def admin_unsuspend(
        edition_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.unsuspend_edition(
            edition_id, actor_id=admin["id"], request_id=request_id(request)
        )

    @app.get("/api/v1/admin/editions/{edition_id}")
    def admin_edition(
        edition_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        del admin
        return request.app.state.service.get_admin_edition(edition_id)

    @app.post("/api/v1/admin/entitlements")
    def admin_entitlement(
        body: EntitlementIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.grant_entitlement(
            listener_id=body.listener_id,
            source_type=body.source_type,
            source_id=body.source_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            status=body.status,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/categories")
    def admin_create_category(
        body: CategoryIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_category(
            slug=body.slug,
            name=body.name,
            description=body.description,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.get("/api/v1/admin/categories")
    def admin_list_categories(
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        del admin
        return {"items": request.app.state.service.list_categories()}

    @app.post("/api/v1/admin/editorial-collections")
    def admin_create_editorial_collection(
        body: EditorialCollectionIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_editorial_collection(
            slug=body.slug,
            title=body.title,
            description=body.description,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.get("/api/v1/admin/editorial-collections")
    def admin_list_editorial_collections(
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        del admin
        return {"items": request.app.state.service.list_editorial_collections()}

    @app.post("/api/v1/admin/editorial-collections/{collection_id}/items")
    def admin_add_editorial_collection_item(
        collection_id: UUID,
        body: EditorialCollectionItemIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        del admin
        request.app.state.service.add_editorial_collection_item(
            collection_id, body.edition_id, body.position
        )
        return {"ok": True}

    @app.post("/api/v1/admin/editorial-collections/{collection_id}/publish")
    def admin_publish_editorial_collection(
        collection_id: UUID,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.publish_editorial_collection(
            collection_id, actor_id=admin["id"], request_id=request_id(request)
        )

    @app.post("/api/v1/admin/entitlements/{entitlement_id}/revoke")
    def admin_revoke_entitlement(
        entitlement_id: UUID,
        request: Request,
        body: EntitlementRevokeIn | None = None,
        admin: dict = Depends(get_admin),
    ) -> dict:
        reason = body.reason if body else "revoked"
        return request.app.state.service.revoke_entitlement(
            entitlement_id,
            reason=reason,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.post("/api/v1/admin/contracts")
    def admin_create_contract(
        body: ContractIn,
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        return request.app.state.service.create_contract(
            name=body.name,
            licensor=body.licensor,
            territory_scope=body.territory_scope,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            status=body.status,
            notes=body.notes,
            actor_id=admin["id"],
            request_id=request_id(request),
        )

    @app.get("/api/v1/admin/contracts")
    def admin_list_contracts(
        request: Request,
        admin: dict = Depends(get_admin),
    ) -> dict:
        del admin
        return {"items": request.app.state.service.list_contracts()}

    @app.get("/api/v1/admin/access-refusals")
    def admin_access_refusals(
        request: Request,
        admin: dict = Depends(get_admin),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict:
        del admin
        return request.app.state.service.access_refusal_dashboard(limit=limit)

    @app.get("/api/v1/admin/audit")
    def admin_audit(
        request: Request,
        admin: dict = Depends(get_admin),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict:
        del admin
        return {"items": request.app.state.repo.list_audit(limit=limit)}

