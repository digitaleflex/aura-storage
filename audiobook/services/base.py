"""Service base and shared dependencies."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..config import Settings
from ..repository import Repository
from ..storage import StoragePort


class BaseService:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        storage: StoragePort,
        *,
        metadata_providers: Iterable[Any] | None = None,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.storage = storage
        self.metadata_providers = tuple(metadata_providers or ())
        self._metadata_aggregator: Any | None = None

