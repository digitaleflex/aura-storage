"""AURA integration boundary.

The audiobook service never reads AURA tables and never builds an S3 URL. It
asks AURA for a short-lived, inline preview URL after its own access decision.
This keeps AURA as storage/delivery infrastructure and the audiobook service as
the only policy decision point.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .errors import UnavailableError


@dataclass(frozen=True)
class PlaybackUrl:
    url: str
    expires_at: datetime
    content_type: str = ""


class StoragePort(Protocol):
    def presigned_playback_url(self, asset: dict) -> PlaybackUrl:
        """Return a short-lived URL for one ready audio asset."""


class FakeStoragePort:
    """Deterministic adapter for tests and local demos."""

    def __init__(self, base_url: str = "https://media.invalid") -> None:
        self.base_url = base_url.rstrip("/")

    def presigned_playback_url(self, asset: dict) -> PlaybackUrl:
        object_id = str(asset["storage_object_id"])
        expires = datetime.fromtimestamp(int(time.time()) + 60, tz=timezone.utc)
        return PlaybackUrl(
            url=f"{self.base_url}/{quote(object_id)}?signature=fake",
            expires_at=expires,
            content_type=str(asset.get("content_type") or ""),
        )


class AuraStoragePort:
    """Call AURA's preview-intent endpoint with a dedicated service identity."""

    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        timeout_seconds: int = 10,
        fallback_ttl_seconds: int = 900,
    ) -> None:
        if not base_url or not service_token:
            raise UnavailableError(
                "AURA storage adapter is not configured",
                code="STORAGE_NOT_CONFIGURED",
            )
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout_seconds = timeout_seconds
        self.fallback_ttl_seconds = fallback_ttl_seconds

    def presigned_playback_url(self, asset: dict) -> PlaybackUrl:
        object_id = str(asset["storage_object_id"])
        request = Request(
            f"{self.base_url}/api/v1/objects/{quote(object_id)}/preview-intent",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise UnavailableError(
                "media backend unavailable",
                code="STORAGE_UNAVAILABLE",
            ) from exc
        if not isinstance(payload, dict) or not payload.get("preview_url"):
            raise UnavailableError(
                "media backend returned an invalid response",
                code="STORAGE_INVALID_RESPONSE",
            )
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)):
            expiry = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
        else:
            expiry = datetime.fromtimestamp(
                int(time.time()) + self.fallback_ttl_seconds, tz=timezone.utc
            )
        return PlaybackUrl(
            url=str(payload["preview_url"]),
            expires_at=expiry,
            content_type=str(payload.get("content_type") or asset.get("content_type") or ""),
        )
