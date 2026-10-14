"""Server-side authentication and authorization (#35, #36, #38).

Two principal kinds:

- **user** — a human browser session (HttpOnly cookie). Mutating requests must
  also carry the session CSRF token. Effective capabilities come from the user's
  role (default-deny map below).
- **service** — a machine-to-machine identity authenticated by a Bearer token.
  Capabilities are the explicit, minimal scope set stored on the identity.

Every sensitive route declares the scope it needs via ``authorize(scope)``; a
route that is not classified stays closed because no dependency grants access.
Unauthenticated calls yield 401, insufficient rights yield 403, and neither
reveals whether an object exists.
"""
import time

from fastapi import Header, HTTPException, Request

from . import identity, netinfo
from .config import settings
from .store import repo

OBJECTS_READ = "objects:read"
OBJECTS_WRITE = "objects:write"
OBJECTS_DELETE = "objects:delete"
OBJECTS_PURGE = "objects:purge"
ADMIN_READ = "admin:read"
ADMIN_WRITE = "admin:write"

ALL_SCOPES = frozenset({
    OBJECTS_READ, OBJECTS_WRITE, OBJECTS_DELETE, OBJECTS_PURGE, ADMIN_READ, ADMIN_WRITE,
})

# Platform administration. These capabilities create spaces, applications and
# further identities, i.e. they can escalate a principal's reach.
ADMIN_SCOPES = frozenset({ADMIN_READ, ADMIN_WRITE})

# Machine-to-machine identities are data-plane principals: they may only ever
# hold object capabilities, never platform administration. A leaked machine
# token must not be able to mint spaces/identities. Enforced twice: on creation
# (``api/main.py`` refuses admin scopes) and here, so a row that somehow carries
# an admin scope (legacy data) is never *effective*.
SERVICE_SCOPES = frozenset({OBJECTS_READ, OBJECTS_WRITE, OBJECTS_DELETE, OBJECTS_PURGE})

# Default-deny role -> capability map (documented in docs/AUTHORIZATION-MATRIX.md).
ROLE_SCOPES = {
    "user": frozenset({OBJECTS_READ, OBJECTS_WRITE, OBJECTS_DELETE}),
    "operator": frozenset({
        OBJECTS_READ, OBJECTS_WRITE, OBJECTS_DELETE, OBJECTS_PURGE, ADMIN_READ,
    }),
    "admin": ALL_SCOPES,
}

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Machine-to-machine authentication failure rate limiter: {client_ip: [ts, ...]}.
_M2M_ATTEMPTS: dict[str, list[float]] = {}


def reset_m2m_attempts() -> None:
    _M2M_ATTEMPTS.clear()


def _client_ip(request: Request) -> str:
    # Trusted-proxy aware: a browser reaches the API through Traefik and nginx,
    # so the socket peer is a proxy, not the client (#35/#38).
    return netinfo.client_ip(request)


def _m2m_blocked(client_ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    window = settings.m2m_rate_window
    attempts = [t for t in _M2M_ATTEMPTS.get(client_ip, []) if now - t < window]
    _M2M_ATTEMPTS[client_ip] = attempts
    return len(attempts) >= settings.m2m_rate_limit


def _m2m_record_failure(client_ip: str) -> None:
    _M2M_ATTEMPTS.setdefault(client_ip, []).append(time.time())


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    key = request.headers.get("x-aura-key")
    return key.strip() if key and key.strip() else None


def authenticate(request: Request) -> dict:
    """Resolve the request principal or raise 401. Never reveals the reason."""
    token = _bearer_token(request)
    if token:
        client_ip = _client_ip(request)
        if _m2m_blocked(client_ip):
            raise HTTPException(status_code=429, detail="too many requests")
        row = identity.authenticate(repo, token)
        if row is None:
            _m2m_record_failure(client_ip)
            raise HTTPException(status_code=401, detail="authentication required")
        space = repo.get_space(row["space_id"]) or {}
        scopes = {s for s in (row.get("scopes") or "").split(",") if s}
        return {
            "kind": "service",
            "id": row["id"],
            "role": row.get("role") or "service",
            "scopes": scopes,
            "space_id": row["space_id"],
            "application_id": row["application_id"],
            "environment": space.get("environment"),
            "csrf": None,
        }

    sid = request.cookies.get("aura_session")
    if not sid:
        raise HTTPException(status_code=401, detail="authentication required")
    session = repo.get_session(sid)
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    user = repo.get_user(session["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    space = repo.get_space(user["space_id"]) if user["space_id"] else None
    return {
        "kind": "user",
        "id": user["id"],
        "role": user["role"] or "user",
        "scopes": set(),
        "space_id": user["space_id"],
        "application_id": user["application_id"],
        "environment": space.get("environment") if space else None,
        "session_id": session["id"],
        "csrf": session["csrf"],
    }


def effective_scopes(principal: dict) -> frozenset:
    if principal["kind"] == "user":
        return ROLE_SCOPES.get(principal["role"], frozenset())
    # Service identities can never exercise an admin capability, even if one is
    # stored on the row (defence in depth; creation already refuses them).
    return frozenset(principal["scopes"]) & SERVICE_SCOPES


def has_scope(principal: dict, scope: str) -> bool:
    return scope in effective_scopes(principal)


def authorize(scope: str | None = None, human: bool = False):
    """FastAPI dependency factory.

    ``scope``    — capability required for the route (None = any authenticated).
    ``human``    — only browser sessions are accepted (e.g. logout).
    """

    def dependency(
        request: Request,
        x_csrf_token: str | None = Header(default=None),
    ) -> dict:
        principal = authenticate(request)
        if human and principal["kind"] != "user":
            raise HTTPException(status_code=403, detail="forbidden")
        if principal["kind"] == "user":
            if request.method not in SAFE_METHODS:
                if not x_csrf_token or x_csrf_token != principal["csrf"]:
                    raise HTTPException(status_code=403, detail="csrf validation failed")
        if scope is not None and not has_scope(principal, scope):
            raise HTTPException(status_code=403, detail="forbidden")
        return principal

    return dependency
