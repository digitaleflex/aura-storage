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
from typing import Any, Literal
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
    NotFoundError,
    UnauthorizedError,
    UnavailableError,
)
from .ids import constant_time_equal, new_token
from .metadata import (
    ITunesMetadataProvider,
    OpenLibraryMetadataProvider,
    UrllibJsonTransport,
)
from .repository import Repository
from .services import AudiobookService
from .storage import AuraStoragePort, FakeStoragePort, StoragePort

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
from .schemas import (
    DevLoginIn,
    WorkIn,
    ContributorIn,
    EditionIn,
    AssetIn,
    TrackIn,
    ChapterIn,
    RightsIn,
    EntitlementIn,
    LibraryIn,
    SessionIn,
    EventIn,
    ProfileIn,
    DeviceIn,
    PersonalCollectionIn,
    PersonalCollectionItemIn,
    CategoryIn,
    EditorialCollectionIn,
    EditorialCollectionItemIn,
    ContractIn,
    EntitlementRevokeIn,
)

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
    metadata_providers: tuple[Any, ...] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    db = db or Database(settings.dsn, settings.schema)
    if initialize_schema:
        db.init_schema()
    repo = Repository(db)
    storage = storage or _build_storage(settings)
    if metadata_providers is None:
        transport = UrllibJsonTransport(
            timeout_seconds=settings.metadata_provider_timeout_seconds
        )
        metadata_providers = (
            OpenLibraryMetadataProvider(transport),
            ITunesMetadataProvider(
                transport, country=settings.metadata_itunes_country
            ),
        )
    service = AudiobookService(
        repo, settings, storage, metadata_providers=metadata_providers
    )

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
    app.state.metadata_providers = metadata_providers
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

    from .routes.admin import register_admin_routes
    from .routes.auth import register_auth_routes
    from .routes.catalog_library import register_catalog_library_routes
    from .routes.health import register_health_routes
    from .routes.listener import register_listener_routes
    from .routes.playback import register_playback_routes

    register_health_routes(app)
    register_auth_routes(app)
    register_listener_routes(app)
    register_catalog_library_routes(app)
    register_playback_routes(app)
    register_admin_routes(app)

    return app
