"""Password hashing (argon2) and opaque session tokens (server-side store)."""
import hashlib
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


def session_key(token: str) -> str:
    """Storage key for a session cookie value: its SHA-256 hex digest.

    The cookie carries a 256-bit random token; the catalogue only keeps this
    digest, so a database or backup leak does not hand out live sessions
    (same model as machine tokens in ``api/identity.py``). A fast hash is
    enough because the input is high-entropy, not a password.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# A throwaway Argon2 hash of an unguessable random string. Verifying against it
# performs the same work as verifying a real user's hash, so the "unknown
# username" branch of login (api/main.py) cannot be told apart from a wrong
# password by response time (user-enumeration hardening). Hashed once at import
# so it is never a guessable literal committed to the repo.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def verify_dummy() -> None:
    """Burn one password verification against the throwaway hash.

    Call this on the login path when no user row exists, so an unknown username
    costs the same Argon2 work as an existing one with a wrong password.
    """
    verify_password(_DUMMY_HASH, "aura-dummy-password")
