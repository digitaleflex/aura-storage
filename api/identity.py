"""Machine-to-machine service identities (#38).

Token format: ``aura_<identity_id>_<secret>`` where ``identity_id`` is a UUID and
``secret`` is 64 hex characters. ``aura_`` and ``_`` are separators; the secret
is hex-only so it never collides with the separator.

Only the SHA-256 fingerprint of the secret is stored. The clear-text token is
returned exactly once, at creation or rotation, and never logged or persisted.
"""
import hashlib
import hmac
import secrets
import time

from . import ids

PREFIX = "aura_"
SECRET_BYTES = 32  # 256 bits -> 64 hex characters


def new_secret() -> str:
    return secrets.token_hex(SECRET_BYTES)


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def format_token(identity_id: str, secret: str) -> str:
    return f"{PREFIX}{identity_id}_{secret}"


def parse_token(token: str):
    if not token or not token.startswith(PREFIX):
        return None
    rest = token[len(PREFIX):]
    if "_" not in rest:
        return None
    identity_id, secret = rest.split("_", 1)
    if not identity_id or not secret:
        return None
    if not ids.is_canonical(identity_id):
        return None
    return identity_id, secret


def authenticate(repo, token: str, now: int | None = None):
    """Return the identity row for a valid token, else None.

    Revoked and expired identities are rejected on every call. The comparison is
    constant-time and errors are indistinguishable from an unknown token.
    """
    parsed = parse_token(token)
    if parsed is None:
        return None
    identity_id, secret = parsed
    row = repo.get_identity(identity_id)
    if row is None:
        return None
    if row.get("revoked_at"):
        return None
    expires_at = row.get("expires_at")
    current = int(time.time()) if now is None else now
    if expires_at is not None and int(expires_at) <= current:
        return None
    if not hmac.compare_digest(row["secret_hash"], fingerprint(secret)):
        return None
    repo.touch_identity(identity_id, current)
    return row
