"""PostgreSQL persistence for the audiobook bounded context.

The implementation is split by concern (identity, catalog, library/entitlements,
playback, audit) while preserving ``Repository`` as the single public entrypoint.
"""
from __future__ import annotations

from .audit import AuditRepository
from .base import _jsonable
from .catalog import CatalogRepository
from .identity import IdentityRepository
from .ingestion import IngestRepository
from .library import LibraryRepository
from .metadata import MetadataRepository
from .playback import PlaybackRepository
from .recommendations import RecommendationsRepository


class Repository(
    IdentityRepository,
    CatalogRepository,
    IngestRepository,
    LibraryRepository,
    MetadataRepository,
    PlaybackRepository,
    AuditRepository,
    RecommendationsRepository,
):
    """Facade repository composing all audiobook persistence concerns."""


__all__ = ["Repository", "_jsonable"]
