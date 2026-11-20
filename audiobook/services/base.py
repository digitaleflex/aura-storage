"""Service base and shared dependencies."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..config import Settings
from ..repository import Repository
from ..storage import StoragePort


class BaseService:
    def __init__(self, repo: Repository, settings: Settings, storage: StoragePort) -> None:
        self.repo = repo
        self.settings = settings
        self.storage = storage

