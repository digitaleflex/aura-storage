"""PostgreSQL persistence for the audiobook bounded context.

The implementation is split by concern (identity, catalog, library/entitlements,
playback, audit) while preserving ``Repository`` as the single public entrypoint.
"""
from __future__ import annotations

from .audit import AuditRepository
from .base import _jsonable
from .catalog import CatalogRepository
from .identity import IdentityRepository
from .library import LibraryRepository
from .playback import PlaybackRepository
from .recommendations import RecommendationsRepository


class Repository(
    IdentityRepository,
    CatalogRepository,
    LibraryRepository,
    PlaybackRepository,
    AuditRepository,
    RecommendationsRepository,
):
    """Facade repository composing all audiobook persistence concerns."""


__all__ = ["Repository", "_jsonable"]
