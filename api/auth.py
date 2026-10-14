"""Password hashing (argon2) and opaque session tokens (server-side store)."""
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Return True only for an exact match; never raise on a bad stored hash.

    A wrong password raises ``VerificationError`` (an ``Argon2Error``), while a
    malformed or unsupported stored hash raises ``InvalidHashError`` /
    ``UnsupportedParametersError`` (both ``ValueError``). All of these mean
    "no match" — surfacing a 500 would both leak that the hash is unusable and
    mask the real 401.
    """
    try:
        return _ph.verify(stored_hash, password)
    except (Argon2Error, ValueError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
