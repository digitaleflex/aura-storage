"""Small HTTPS JSON transport used by metadata providers."""
from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class MetadataProviderError(RuntimeError):
    """Provider unavailable, invalid or returned an unsafe response."""


class JsonTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibJsonTransport:
    """HTTPS-only, redirect-refusing and size-bounded JSON transport."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        max_bytes: int = 2_000_000,
        user_agent: str = "AURA-Metadata/0.1",
    ) -> None:
        if timeout_seconds <= 0 or max_bytes <= 0:
            raise ValueError("timeout and max_bytes must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.user_agent = user_agent
        self._opener = build_opener(_NoRedirectHandler())

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise MetadataProviderError("metadata endpoint must use HTTPS")
        target = url
        if params:
            target += ("&" if "?" in target else "?") + urlencode(params)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            **(headers or {}),
        }
        request = Request(target, headers=request_headers)
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise MetadataProviderError("metadata provider request failed") from exc
        if len(raw) > self.max_bytes:
            raise MetadataProviderError("metadata provider response too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MetadataProviderError("metadata provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MetadataProviderError("metadata provider returned a non-object payload")
        return payload
