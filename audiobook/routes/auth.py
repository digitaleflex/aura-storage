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


def register_auth_routes(app):
    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    @app.post("/api/v1/auth/dev-login")
    def dev_login(body: DevLoginIn, request: Request, svc=Depends(get_service)):
        if not request.app.state.settings.dev_auth:
            raise ForbiddenError(
                "development authentication is disabled",
                code="DEV_AUTH_DISABLED",
            )
        return svc.dev_login(
            body.email, body.display_name, request_id=request_id(request)
        )

    @app.get("/api/v1/auth/google")
    def google_start(request: Request):
        settings_: Settings = request.app.state.settings
        if not settings_.google_configured:
            raise UnavailableError(
                "Google authentication is not configured",
                code="GOOGLE_AUTH_DISABLED",
            )
        state = new_token(32)
        verifier, challenge = google_oidc.new_pkce()
        response = RedirectResponse(
            google_oidc.authorization_url(settings_, state, challenge),
            status_code=302,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )
        response.set_cookie(
            settings_.oauth_cookie_name,
            f"{state}.{verifier}",
            httponly=True,
            secure=settings_.cookie_secure,
            samesite="lax",
            max_age=settings_.oauth_cookie_ttl_seconds,
            path="/api/v1/auth",
            domain=settings_.cookie_domain or None,
        )
        return response

    @app.get("/api/v1/auth/google/callback")
    def google_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ):
        settings_: Settings = request.app.state.settings
        if not settings_.google_configured:
            raise UnavailableError(
                "Google authentication is not configured",
                code="GOOGLE_AUTH_DISABLED",
            )
        raw = request.cookies.get(settings_.oauth_cookie_name, "")
        expected_state, separator, verifier = raw.partition(".")
        if (
            not separator
            or not state
            or not constant_time_equal(str(state), str(expected_state))
        ):
            raise UnauthorizedError("invalid OAuth state", code="OAUTH_BAD_STATE")
        if error or not code or len(code) > 512:
            raise UnauthorizedError("OAuth provider error", code="OAUTH_PROVIDER_ERROR")
        try:
            tokens = google_oidc.exchange_code(settings_, code, verifier)
            claims = google_oidc.verify_id_token(settings_, tokens["id_token"])
        except google_oidc.OAuthError as exc:
            raise UnauthorizedError(
                "Google authentication failed", code="OAUTH_FAILED"
            ) from exc
        listener, issued = request.app.state.service.google_login(
            claims, request_id=request_id(request)
        )
        response = RedirectResponse(
            settings_.post_login_redirect,
            status_code=302,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
        set_session_cookies(response, issued, settings_)
        response.delete_cookie(
            settings_.oauth_cookie_name, path="/api/v1/auth"
        )
        return response

