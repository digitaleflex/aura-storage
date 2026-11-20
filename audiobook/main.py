"""FastAPI entry point for the audiobook bounded context.

Run in production with::

    uvicorn audiobook.main:create_app --factory --host 0.0.0.0 --port 8080

The service owns listener identity, catalog publication, library, access
decisions and listening progress. It never reads AURA tables; media URLs come
from ``StoragePort`` after an allow decision.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth, google_oidc
from .config import ConfigError, Settings
from .db import Database
from .errors import (
    AppError,
    ForbiddenError,
    UnauthorizedError,
    UnavailableError,
)
from .ids import constant_time_equal, new_token
from .repository import Repository
from .services import AudiobookService
from .storage import AuraStoragePort, FakeStoragePort, StoragePort

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class DevLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=200)


class WorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=2, max_length=16)
    description: str = Field(default="", max_length=20_000)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)


class ContributorIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    role: Literal["author", "narrator", "translator", "adapter", "illustrator", "other"]
    position: int = Field(default=0, ge=0, le=10_000)
    sort_name: str = Field(default="", max_length=500)


class EditionIn(BaseModel):
    work_id: UUID
    title: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=2, max_length=16)
    description: str = Field(min_length=1, max_length=50_000)
    duration_ms: int = Field(gt=0)
    slug: str | None = Field(default=None, max_length=140)
    publisher: str = Field(default="", max_length=300)
    publication_date: date | None = None
    cover_asset_id: UUID | None = None
    access_model: Literal["free", "paid", "subscription"] = "free"


class AssetIn(BaseModel):
    storage_object_id: str = Field(min_length=1, max_length=200)
    kind: Literal["source", "hls", "cover", "subtitle", "derivative"] = "source"
    content_type: str = Field(default="", max_length=200)
    size_bytes: int = Field(default=-1, ge=-1)
    checksum_sha256: str = Field(default="", max_length=128)
    duration_ms: int | None = Field(default=None, ge=0)
    codec: str = Field(default="", max_length=100)
    status: Literal[
        "initiated", "uploaded", "quarantined", "validating", "ready",
        "rejected", "blocked", "superseded", "deleted",
    ] = "ready"


class TrackIn(BaseModel):
    position: int = Field(ge=1, le=100_000)
    title: str = Field(default="", max_length=500)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    asset_id: UUID | None = None
    status: Literal["pending", "ready", "unavailable", "blocked"] = "ready"


class ChapterIn(BaseModel):
    position: int = Field(ge=1, le=100_000)
    title: str = Field(default="", max_length=500)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class RightsIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    territory_code: str = Field(default="WORLD", min_length=2, max_length=32)
    channel: Literal["stream", "download", "preview"] = "stream"
    status: Literal["planned", "active", "suspended", "expired", "terminated"] = "active"
    max_downloads: int | None = Field(default=None, ge=0)
    allowed_formats: list[str] | None = None


class EntitlementIn(BaseModel):
    listener_id: UUID
    source_type: Literal[
        "purchase", "subscription", "free", "promotion", "manual", "personal_import"
    ]
    source_id: str = Field(default="", max_length=200)
    scope_type: Literal["edition", "work", "plan_catalog", "personal_asset"]
    scope_id: str = Field(min_length=1, max_length=200)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: Literal["pending", "active", "suspended", "revoked", "expired", "canceled"] = "active"


class LibraryIn(BaseModel):
    work_id: UUID
    preferred_edition_id: UUID | None = None
    source: Literal["manual", "purchase", "subscription", "import", "promotion"] = "manual"


class SessionIn(BaseModel):
    edition_id: UUID
    device_id: UUID | None = None
    takeover: bool = False


class EventIn(BaseModel):
    event_id: UUID | None = None
    client_seq: int = Field(ge=1, le=2_147_483_647)
    kind: Literal["start", "heartbeat", "seek", "pause", "resume", "ended", "takeover"]
    position_ms: int = Field(ge=0)
    track_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    occurred_at_client: datetime | None = None
    playback_rate: float = Field(default=1.0, ge=0.25, le=4.0)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def _build_storage(settings: Settings) -> StoragePort:
    if settings.aura_api_base_url and settings.aura_service_token:
        return AuraStoragePort(
            settings.aura_api_base_url,
            settings.aura_service_token,
            fallback_ttl_seconds=settings.aura_intent_ttl_seconds,
        )
    if settings.dev_auth:
        return FakeStoragePort()
    raise ConfigError(
        "AURA_API_BASE_URL and AURA_SERVICE_TOKEN are required outside development"
    )


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    storage: StoragePort | None = None,
    *,
    initialize_schema: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    db = db or Database(settings.dsn, settings.schema)
    if initialize_schema:
        db.init_schema()
    repo = Repository(db)
    storage = storage or _build_storage(settings)
    service = AudiobookService(repo, settings, storage)

    app = FastAPI(
        title="AURA Audiobook API",
        version="0.1.0",
        docs_url="/docs" if settings.dev_auth else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.dev_auth else None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.repo = repo
    app.state.storage = storage
    app.state.service = service

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-CSRF-Token",
                "X-Request-ID",
                "X-Territory",
            ],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = (
            supplied if _REQUEST_ID_RE.fullmatch(supplied) else secrets.token_hex(8)
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith(("/api/v1/auth", "/api/v1/me")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": jsonable_encoder(exc.details),
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "invalid request",
                "details": jsonable_encoder(exc.errors()),
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------
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
            auth.require_csrf(
                principal, request.headers.get("x-csrf-token", "")
            )
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

    def _decision(decision) -> dict:
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

    # ------------------------------------------------------------------
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
        _set_session_cookies(response, issued, settings_)
        response.delete_cookie(
            settings_.oauth_cookie_name, path="/api/v1/auth"
        )
        return response

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

    # ------------------------------------------------------------------
    # Access and playback
    # ------------------------------------------------------------------
    @app.get("/api/v1/access/{edition_id}")
    def access(
        edition_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        action: Literal["stream", "preview"] = Query(default="stream"),
        territory: str = Header(default="WORLD", alias="X-Territory", max_length=32),
    ) -> dict:
        decision, _ = request.app.state.service.evaluate_access(
            principal,
            edition_id,
            action=action,
            territory_code=territory,
            request_id=request_id(request),
        )
        return _decision(decision)

    @app.get("/api/v1/progress/{edition_id}")
    def progress(
        edition_id: UUID,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
    ) -> dict:
        return request.app.state.service.get_progress(principal, edition_id)

    @app.post("/api/v1/playback/sessions")
    def start_playback(
        body: SessionIn,
        request: Request,
        principal: auth.Principal = Depends(get_principal),
        territory: str = Header(default="WORLD", alias="X-Territory", max_length=32),
    ) -> dict:
        result = request.app.state.service.start_session(
            principal,
            edition_id=body.edition_id,
            device_id=body.device_id,
            takeover=body.takeover,
            territory_code=territory,
            request_id=request_id(request),
        )
        result["decision"] = _decision(result["decision"])
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
        territory: str = Header(default="WORLD", alias="X-Territory", max_length=32),
    ) -> dict:
        result = request.app.state.service.authorize_track(
            principal,
            edition_id,
            track_id,
            territory_code=territory,
            request_id=request_id(request),
        )
        result["decision"] = _decision(result["decision"])
        return result

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

    @app.get("/api/v1/admin/audit")
    def admin_audit(
        request: Request,
        admin: dict = Depends(get_admin),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict:
        del admin
        return {"items": request.app.state.repo.list_audit(limit=limit)}

    return app


def _set_session_cookies(
    response: Response, issued: auth.IssuedSession, settings: Settings
) -> None:
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


