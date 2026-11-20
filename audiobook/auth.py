"""Opaque listener sessions and CSRF checks.

The database stores only SHA-256 digests of session and CSRF tokens. Bearer
tokens are for native clients and are never accepted from a cookie jar; cookie
sessions additionally require the ``X-CSRF-Token`` header on mutations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from .config import Settings
from .errors import ForbiddenError, UnauthorizedError
from .ids import constant_time_equal, new_token, token_hash, utcnow
from .repository import Repository


@dataclass(frozen=True)
class Principal:
    listener: dict
    session_id: UUID
    csrf_hash: str
    auth_source: str

    @property
    def listener_id(self) -> UUID:
        return self.listener["id"]


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    session: dict
    expires_at: datetime


def issue_session(
    repo: Repository,
    listener_id: UUID,
    settings: Settings,
    *,
    device_id: UUID | None = None,
) -> IssuedSession:
    token = new_token(32)
    csrf_token = new_token(24)
    expires_at = utcnow() + timedelta(seconds=settings.session_ttl_seconds)
    session = repo.create_session(
        listener_id,
        token_hash(token),
        token_hash(csrf_token),
        expires_at,
        device_id=device_id,
    )
    return IssuedSession(token, csrf_token, session, expires_at)


def authenticate(
    repo: Repository,
    raw_token: str,
    *,
    source: str,
) -> Principal:
    if not raw_token or len(raw_token) > 512:
        raise UnauthorizedError("authentication required")
    row = repo.get_session_by_token_hash(token_hash(raw_token))
    now = utcnow()
    if row is None:
        raise UnauthorizedError("invalid or expired session", code="SESSION_INVALID")
    if row["revoked_at"] is not None:
        raise UnauthorizedError("session revoked", code="SESSION_REVOKED")
    if row["expires_at"] <= now:
        raise UnauthorizedError("session expired", code="SESSION_EXPIRED")
    listener = {
        "id": row["listener_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "status": row["listener_status"],
        "locale": row["locale"],
        "timezone": row["timezone"],
    }
    if listener["status"] != "active":
        raise ForbiddenError(
            "listener account is not active",
            code=f"ACCOUNT_{str(listener['status']).upper()}",
        )
    repo.touch_session(row["id"])
    return Principal(
        listener=listener,
        session_id=row["id"],
        csrf_hash=row["csrf_hash"],
        auth_source=source,
    )


def require_csrf(principal: Principal, supplied: str) -> None:
    if principal.auth_source != "cookie":
        return
    if not supplied or not constant_time_equal(token_hash(supplied), principal.csrf_hash):
        raise ForbiddenError("invalid CSRF token", code="CSRF_INVALID")


def session_ttl(settings: Settings) -> int:
    return settings.session_ttl_seconds
