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


def register_playback_routes(app):
    # ------------------------------------------------------------------
    # Access and playback
    # ------------------------------------------------------------------
    @app.get("/api/v1/access/{edition_id}")
    def access(
        edition_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        action: Literal["stream", "preview"] = Query(default="stream"),
        territory: str | None = Header(default=None, alias="X-Territory", max_length=32),
        device_id: UUID | None = Header(default=None, alias="X-Device-Id"),
    ) -> dict:
        decision, _ = request.app.state.service.evaluate_access(
            principal,
            edition_id,
            action=action,
            territory_code=territory,
            device_id=device_id,
            request_id=request_id(request),
        )
        return decision_payload(decision)

    @app.get("/api/v1/progress/{edition_id}")
    def progress(
        edition_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.get_progress(principal, edition_id)

    @app.get("/api/v1/history")
    def history(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        return {
            "items": request.app.state.service.listening_history(
                principal, limit=limit
            )
        }

    @app.get("/api/v1/stats")
    def stats(
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.listening_stats(principal)

    @app.post("/api/v1/playback/sessions")
    def start_playback(
        body: SessionIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        territory: str | None = Header(default=None, alias="X-Territory", max_length=32),
    ) -> dict:
        result = request.app.state.service.start_session(
            principal,
            edition_id=body.edition_id,
            device_id=body.device_id,
            takeover=body.takeover,
            territory_code=territory,
            request_id=request_id(request),
        )
        result["decision"] = decision_payload(result["decision"])
        return result

    @app.post("/api/v1/playback/sessions/{session_id}/events")
    def playback_event(
        session_id: UUID,
        body: EventIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.append_event(
            principal,
            session_id,
            event_id=body.event_id,
            client_seq=body.client_seq,
            kind=body.kind,
            position_ms=body.position_ms,
            track_id=body.track_id,
            duration_ms=body.duration_ms,
            occurred_at_client=body.occurred_at_client,
            playback_rate=body.playback_rate,
            request_id=request_id(request),
        )

    @app.post("/api/v1/playback/editions/{edition_id}/tracks/{track_id}/url")
    def track_url(
        edition_id: UUID,
        track_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        territory: str | None = Header(default=None, alias="X-Territory", max_length=32),
        device_id: UUID | None = Header(default=None, alias="X-Device-Id"),
    ) -> dict:
        result = request.app.state.service.authorize_track(
            principal,
            edition_id,
            track_id,
            territory_code=territory,
            device_id=device_id,
            request_id=request_id(request),
        )
        result["decision"] = decision_payload(result["decision"])
        return result

