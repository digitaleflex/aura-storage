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


def register_health_routes(app):
    # Health and root
    # ------------------------------------------------------------------
    @app.get("/health/live")
    def health_live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(request: Request) -> dict:
        try:
            request.app.state.db.healthcheck()
        except Exception as exc:
            raise UnavailableError(
                "database unavailable", code="DATABASE_UNAVAILABLE"
            ) from exc
        return {"status": "ok"}

    @app.get("/")
    def root() -> dict:
        return {"service": "audiobook-api", "version": "0.1.0"}

