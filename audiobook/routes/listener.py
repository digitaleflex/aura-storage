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


def register_listener_routes(app):
    @app.get("/api/v1/me")
    def me(request: Request, principal: auth.Principal = Depends(get_principal)):
        settings_: Settings = request.app.state.settings
        return {
            "listener": principal.listener,
            "auth_source": principal.auth_source,
            "csrf_token": request.cookies.get(settings_.csrf_cookie_name),
        }

    @app.post("/api/v1/auth/logout")
    def logout(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ):
        request.app.state.service.logout(
            principal, request_id=request_id(request)
        )
        response = JSONResponse({"ok": True})
        settings_: Settings = request.app.state.settings
        response.delete_cookie(settings_.cookie_name, path="/")
        response.delete_cookie(settings_.csrf_cookie_name, path="/")
        return response

    @app.patch("/api/v1/me")
    def update_me(
        body: ProfileIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        listener = request.app.state.service.update_profile(
            principal,
            display_name=body.display_name,
            locale=body.locale,
            timezone=body.timezone,
            territory_code=body.territory_code,
            request_id=request_id(request),
        )
        return {"listener": listener}

    @app.post("/api/v1/me/deletion-request")
    def request_deletion(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        listener = request.app.state.service.request_deletion(
            principal, request_id=request_id(request)
        )
        return {"listener": listener}

    @app.get("/api/v1/me/sessions")
    def list_auth_sessions(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return {"items": request.app.state.service.list_auth_sessions(principal)}

    @app.delete("/api/v1/me/sessions/{session_id}")
    def revoke_auth_session(
        session_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        revoked = request.app.state.service.revoke_auth_session(
            principal, session_id, request_id=request_id(request)
        )
        if not revoked:
            raise NotFoundError("session not found", code="SESSION_NOT_FOUND")
        return {"revoked": True}

    @app.get("/api/v1/devices")
    def list_devices(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return {"items": request.app.state.service.list_devices(principal)}

    @app.post("/api/v1/devices")
    def register_device(
        body: DeviceIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.register_device(
            principal,
            name=body.name,
            platform=body.platform,
            request_id=request_id(request),
        )

    @app.post("/api/v1/devices/{device_id}/revoke")
    def revoke_device(
        device_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        revoked = request.app.state.service.revoke_device(
            principal, device_id, request_id=request_id(request)
        )
        if not revoked:
            raise NotFoundError("device not found", code="DEVICE_NOT_FOUND")
        return {"revoked": True}

