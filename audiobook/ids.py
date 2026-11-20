"""Small pure helpers shared by the service."""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timezone


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def token_hash(token: str) -> str:
    """Store only the digest of an opaque session/CSRF token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def constant_time_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(str(left), str(right))


def slugify(value: str, suffix: str | None = None) -> str:
    """ASCII, lowercase, URL-safe slug; never relies on the caller's locale."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    value = value[:80].strip("-") or "livre"
    if suffix:
        value = f"{value}-{suffix[:12]}"
    return value


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
