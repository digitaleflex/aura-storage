"""HTTP dependencies and helpers for the audiobook API."""
from __future__ import annotations

from fastapi import Depends, Request

from . import auth
from .config import Settings
from .errors import UnauthorizedError, UnavailableError
from .ids import constant_time_equal
from .services import AudiobookService


def get_service(request: Request) -> AudiobookService:
    return request.app.state.service


def get_principal(
    request: Request, svc: AudiobookService = Depends(get_service)
) -> auth.Principal:
    settings_: Settings = request.app.state.settings
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        source = "bearer"
    else:
        token = request.cookies.get(settings_.cookie_name, "")
        source = "cookie"
    if not token:
        raise UnauthorizedError("authentication required")
    principal = svc.authenticate(token, source=source)
    if source == "cookie" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        auth.require_csrf(principal, request.headers.get("x-csrf-token", ""))
    return principal


def get_admin(request: Request) -> dict:
    settings_: Settings = request.app.state.settings
    if not settings_.admin_token:
        raise UnavailableError(
            "admin authentication is not configured",
            code="ADMIN_AUTH_DISABLED",
        )
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("admin authentication required")
    supplied = authorization[7:].strip()
    if not constant_time_equal(supplied, settings_.admin_token):
        raise UnauthorizedError("invalid admin token", code="ADMIN_TOKEN_INVALID")
    return {"id": "admin"}


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def decision_payload(decision) -> dict:
    return {
        "allowed": decision.allowed,
        "reason_code": decision.reason_code,
        "sources": list(decision.sources),
        "expires_at": decision.expires_at,
        "policy_version": decision.policy_version,
        "territory_code": decision.territory_code,
        "action": decision.action,
        "edition_id": decision.edition_id,
    }


def set_session_cookies(response, issued: auth.IssuedSession, settings: Settings) -> None:
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        settings.cookie_name,
        issued.token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
        domain=settings.cookie_domain or None,
    )
    # Double-submit CSRF cookie: readable by the SPA, checked against the
    # hashed value stored server-side. The session cookie stays HttpOnly.
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
        domain=settings.cookie_domain or None,
    )
