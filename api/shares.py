"""Public object share links.

A share is an unauthenticated, revocable, read-only capability for exactly one
object. It exists so an object can be handed to someone outside AURA without
giving them an account, a machine token or a long-lived URL.

Deliberate design constraints (documented in ``docs/AUTHORIZATION-MATRIX.md``):

- **The token is never stored.** Only its SHA-256 fingerprint is, so a catalogue
  copy cannot be replayed as working links.
- **Redemption is a redirect, not a proxy.** The link answers 302 to a
  short-lived presigned S3 URL, so object bytes never pass through the API and
  the public link itself carries no S3 credential.
- **Expiry is mandatory and bounded**, revocation is immediate, and ``max_uses``
  is enforced atomically by the catalogue (``Repository.consume_share``).
- **Every failure is the same 404**: unknown, malformed, expired, exhausted and
  revoked links are indistinguishable, so the endpoint cannot be used to probe
  which objects or shares exist.
- **``inline`` is restricted to types a browser can render without executing
  script.** The bytes are served from the S3 host, but an ``text/html`` or
  ``image/svg+xml`` payload would turn a share link into an active document on a
  domain the operator controls. Those stay download-only.
"""
import hashlib
import re
import secrets
from urllib.parse import quote

# 32 random bytes -> 43 url-safe characters. 256 bits means guessing is not a
# threat model; the guards that matter are expiry, revocation and max_uses.
TOKEN_BYTES = 32
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

# Types allowed with Content-Disposition: inline. Everything else -- notably
# text/html, image/svg+xml and the application/xhtml+xml family -- is refused at
# creation so a share link can never serve an active document.
SAFE_INLINE_TYPES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "text/plain",
})

DISPOSITIONS = ("attachment", "inline")


def new_token() -> str:
    """Return a fresh link token. Shown once, never persisted or logged."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def fingerprint(token: str) -> str:
    """SHA-256 hex of the token, the only form the catalogue stores."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_well_formed(token: str) -> bool:
    """Cheap shape check before touching the catalogue.

    A malformed token cannot match a stored fingerprint, so rejecting it early
    saves a lookup and keeps obvious scanner noise out of the audit trail.
    """
    return bool(_TOKEN_RE.match(token or ""))


def inline_allowed(content_type: str) -> bool:
    """True when ``content_type`` may be rendered inline without executing code."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return normalized in SAFE_INLINE_TYPES


def content_disposition_header(disposition: str, display_name: str) -> str:
    """Build a header-safe Content-Disposition value for the presigned GET.

    The display name is user-controlled, so quotes, backslashes and control
    characters are stripped, then the value is ASCII-folded for the legacy
    ``filename`` parameter with the real name carried through RFC 5987.
    """
    cleaned = "".join(
        ch for ch in (display_name or "") if ch.isprintable() and ch not in '"\\'
    )
    cleaned = " ".join(cleaned.split())[:120]
    ascii_name = cleaned.encode("ascii", "ignore").decode().strip() or "download"
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(cleaned or 'download')}"
    )
