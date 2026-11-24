"""AURA integration boundary.

The audiobook service never reads AURA tables and never builds an S3 URL. It
asks AURA for short-lived URLs after its own access decision, and imports new
bytes through the documented upload-intent/commit contract. This keeps AURA as
storage/delivery infrastructure and the audiobook service as the only policy
decision point.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPSConnection
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .errors import UnavailableError

_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PlaybackUrl:
    url: str
    expires_at: datetime
    content_type: str = ""


@dataclass(frozen=True)
class UploadIntent:
    object_id: str
    idempotency_key: str
    upload_url: str
    headers: dict[str, str]
    size_bytes: int
    expires_in: int


@dataclass(frozen=True)
class CommitResult:
    object_id: str
    status: str
    size_bytes: int
    checksum_sha256: str
    checksum_algorithm: str = "sha256"


class StoragePort(Protocol):
    def presigned_playback_url(self, asset: dict) -> PlaybackUrl:
        """Return a short-lived URL for one ready audio asset."""

    def create_upload_intent(
        self,
        *,
        display_name: str,
        content_type: str,
        size_bytes: int,
        idempotency_key: str,
    ) -> UploadIntent:
        """Create an AURA upload intent using a service identity."""

    def upload_bytes(self, intent: UploadIntent, source_path: Path) -> None:
        """Stream local bytes to the presigned URL; never log that URL."""

    def commit_upload(
        self, object_id: str, *, idempotency_key: str
    ) -> CommitResult:
        """Ask AURA to verify stored bytes and mark the object available."""


class FakeStoragePort:
    """Deterministic adapter for tests and local demos."""

    def __init__(self, base_url: str = "https://media.invalid") -> None:
        self.base_url = base_url.rstrip("/")
        self.uploads: dict[str, dict] = {}
        self.commit_failures: dict[str, int] = {}

    def presigned_playback_url(self, asset: dict) -> PlaybackUrl:
        object_id = str(asset["storage_object_id"])
        expires = datetime.fromtimestamp(int(time.time()) + 60, tz=timezone.utc)
        return PlaybackUrl(
            url=f"{self.base_url}/{quote(object_id)}?signature=fake",
            expires_at=expires,
            content_type=str(asset.get("content_type") or ""),
        )

    def create_upload_intent(
        self,
        *,
        display_name: str,
        content_type: str,
        size_bytes: int,
        idempotency_key: str,
    ) -> UploadIntent:
        existing = self.uploads.get(idempotency_key)
        if existing is not None:
            object_id = existing["object_id"]
        else:
            object_id = f"fake-{secrets.token_hex(16)}"
            self.uploads[idempotency_key] = {
                "object_id": object_id,
                "size_bytes": size_bytes,
                "path": None,
                "content_type": content_type,
                "display_name": display_name,
            }
        return UploadIntent(
            object_id=object_id,
            idempotency_key=idempotency_key,
            upload_url=f"{self.base_url}/upload/{object_id}?signature=fake",
            headers={},
            size_bytes=size_bytes,
            expires_in=900,
        )

    def upload_bytes(self, intent: UploadIntent, source_path: Path) -> None:
        record = self.uploads.setdefault(
            intent.idempotency_key,
            {
                "object_id": intent.object_id,
                "size_bytes": intent.size_bytes,
                "path": None,
                "content_type": "",
                "display_name": "",
            },
        )
        record["path"] = str(source_path)

    def commit_upload(
        self, object_id: str, *, idempotency_key: str
    ) -> CommitResult:
        remaining = self.commit_failures.get(idempotency_key, 0)
        if remaining > 0:
            self.commit_failures[idempotency_key] = remaining - 1
            raise UnavailableError("commit temporarily unavailable", code="COMMIT_PENDING")
        record = self.uploads.get(idempotency_key)
        if record is None or record["object_id"] != object_id or not record["path"]:
            raise UnavailableError("upload not found", code="AURA_UPLOAD_REJECTED")
        digest = hashlib.sha256()
        total = 0
        with Path(record["path"]).open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
                total += len(chunk)
        return CommitResult(
            object_id=object_id,
            status="available",
            size_bytes=total,
            checksum_sha256=digest.hexdigest(),
        )


class AuraStoragePort:
    """Call AURA's management API with a dedicated service identity."""

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
        payload = self._post_json(f"/api/v1/objects/{quote(object_id)}/preview-intent")
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

    def create_upload_intent(
        self,
        *,
        display_name: str,
        content_type: str,
        size_bytes: int,
        idempotency_key: str,
    ) -> UploadIntent:
        payload = self._post_json(
            "/api/v1/objects/upload-intents",
            body={
                "display_name": display_name,
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            idempotency_key=idempotency_key,
        )
        object_id = str(payload.get("id") or "")
        upload_url = str(payload.get("upload_url") or "")
        if payload.get("multipart_upload_id") or not upload_url:
            raise UnavailableError(
                "multipart ingestion is not supported by this adapter",
                code="MULTIPART_NOT_SUPPORTED",
            )
        headers = payload.get("headers")
        if not object_id or not isinstance(headers, dict):
            raise UnavailableError(
                "storage returned an invalid upload intent",
                code="STORAGE_INVALID_RESPONSE",
            )
        return UploadIntent(
            object_id=object_id,
            idempotency_key=idempotency_key,
            upload_url=upload_url,
            headers={str(key): str(value) for key, value in headers.items()},
            size_bytes=size_bytes,
            expires_in=int(payload.get("expires_in") or 0),
        )

    def upload_bytes(self, intent: UploadIntent, source_path: Path) -> None:
        parsed = urlparse(intent.upload_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UnavailableError("unsafe upload URL", code="STORAGE_INVALID_RESPONSE")
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        connection = HTTPSConnection(parsed.hostname, parsed.port, timeout=self.timeout_seconds)
        try:
            connection.putrequest("PUT", target)
            for key, value in intent.headers.items():
                connection.putheader(key, value)
            connection.putheader("Content-Length", str(intent.size_bytes))
            connection.endheaders()
            with source_path.open("rb") as handle:
                while True:
                    chunk = handle.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    connection.send(chunk)
            response = connection.getresponse()
            response.read()
            if response.status not in {200, 201, 204}:
                raise UnavailableError(
                    "storage refused the upload", code="AURA_UPLOAD_REJECTED"
                )
        except (OSError, TimeoutError) as exc:
            raise UnavailableError("storage unavailable", code="STORAGE_UNAVAILABLE") from exc
        finally:
            connection.close()

    def commit_upload(
        self, object_id: str, *, idempotency_key: str
    ) -> CommitResult:
        payload = self._post_json(
            f"/api/v1/objects/{quote(object_id)}/commit",
            idempotency_key=idempotency_key,
            allow_accepted=False,
        )
        if payload.get("status") == "verifying":
            raise UnavailableError("verification still running", code="COMMIT_PENDING")
        checksum = str(payload.get("checksum_sha256") or "")
        if payload.get("status") != "available" or not checksum:
            raise UnavailableError(
                "storage returned an invalid commit result",
                code="STORAGE_INVALID_RESPONSE",
            )
        return CommitResult(
            object_id=object_id,
            status="available",
            size_bytes=int(payload.get("size_bytes") or 0),
            checksum_sha256=checksum,
            checksum_algorithm=str(payload.get("checksum_algorithm") or "sha256"),
        )

    def _post_json(
        self,
        path: str,
        *,
        body: dict | None = None,
        idempotency_key: str | None = None,
        allow_accepted: bool = True,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.service_token}",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if allow_accepted and response.status == 202:
                    return {"status": "verifying"}
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {409, 410, 422}:
                raise UnavailableError(
                    f"AURA refused the operation (HTTP {exc.code})",
                    code="AURA_UPLOAD_REJECTED",
                ) from exc
            raise UnavailableError("storage unavailable", code="STORAGE_UNAVAILABLE") from exc
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            raise UnavailableError("storage unavailable", code="STORAGE_UNAVAILABLE") from exc
        if not isinstance(payload, dict):
            raise UnavailableError(
                "storage returned an invalid response", code="STORAGE_INVALID_RESPONSE"
            )
        return payload
