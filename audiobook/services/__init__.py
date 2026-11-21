"""Application services for the audiobook bounded context.

Split by concern while preserving ``AudiobookService`` as the single facade
used by the HTTP layer and tests.
"""
from __future__ import annotations

from .account import AccountService
from .admin_catalog import AdminCatalogService
from .analytics import AnalyticsService
from .auth import AuthService
from .catalog import CatalogService
from .entitlements import EntitlementsService
from .library import LibraryService
from .personal_collections import PersonalCollectionsService
from .playback import PlaybackService
from .recommendations import RecommendationsService
from .serialization import SerializationService


class AudiobookService(
    AuthService,
    CatalogService,
    LibraryService,
    PlaybackService,
    EntitlementsService,
    AccountService,
    PersonalCollectionsService,
    AdminCatalogService,
    AnalyticsService,
    RecommendationsService,
    SerializationService,
):
    """Facade service composing audiobook application use cases."""


__all__ = ["AudiobookService"]
