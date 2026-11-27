"""Auth routes extracted from api.main (#342)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .audit import audit_event
from .auth import new_token
from .authz import authorize, effective_scopes, master_mode_active
from .config import settings
from .store import repo


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Bounded so a failed attempt can never inject megabytes into the audit
    # trail (the username is recorded on every failure).
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


router = APIRouter()


@router.post("/api/v1/login")
def login(body: LoginIn, request: Request, response: Response):
    from .main import (
        _DUMMY_PASS_HASH, _client_ip, _login_blocked, _login_clear, _login_record_failure,
        verify_password,
    )
    client_ip = _client_ip(request)
    if _login_blocked(client_ip):
        audit_event("login", body.username, "rate_limited")
        # Honor-your-limits (#86): tell the client when it may retry.
        raise HTTPException(status_code=429, detail="too many login attempts",
                            headers={"Retry-After": str(settings.login_rate_window)})
    row = repo.get_user_by_name(body.username)
    # An unknown username still pays one argon2 verification, so response time
    # does not reveal which usernames exist.
    stored_hash = row["pass_hash"] if row is not None else _DUMMY_PASS_HASH
    if not verify_password(stored_hash, body.password) or row is None:
        _login_record_failure(client_ip)
        audit_event("login", body.username, "failure")
        raise HTTPException(status_code=401, detail="invalid credentials")
    _login_clear(client_ip)
    csrf = new_token(16)
    sid = repo.create_session(
        row["id"], csrf, int(time.time()) + settings.session_ttl
    )
    response.set_cookie(
        "aura_session", sid, httponly=True, secure=settings.cookie_secure,
        samesite="lax", max_age=settings.session_ttl, path="/",
    )
    audit_event("login", body.username, "success", {"user_id": row["id"]})
    return {"csrf_token": csrf}


@router.post("/api/v1/logout")
def logout(principal: dict = Depends(authorize(human=True))):
    repo.delete_session(principal["session_id"])
    audit_event("logout", principal["id"], "success")
    out = JSONResponse(content={"status": "logged out"})
    out.delete_cookie(
        "aura_session", path="/", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return out


@router.get("/api/v1/me")
def me(request: Request, response: Response, principal: dict = Depends(authorize())):
    # ``csrf_token`` is additive and human-only: the token is issued once at
    # login and kept in the frontend's memory, so a refresh or a new tab used to
    # lose it while the ``aura_session`` cookie stayed valid, making every
    # mutation fail CSRF. Re-exposing it here lets the client recover the token
    # from its still-valid session without a new login. A CSRF token is not a
    # secret in the double-submit model (it is only meaningful paired with the
    # HttpOnly cookie and unreadable cross-origin); service identities have no
    # session and therefore receive ``null``.
    if principal["kind"] == "user":
        sid = request.cookies.get("aura_session")
        session_id = principal.get("session_id")
        if sid and session_id:
            now = int(time.time())
            expires_at = now + settings.session_ttl
            repo.extend_session(session_id, expires_at)
            response.set_cookie(
                "aura_session", sid, httponly=True, secure=settings.cookie_secure,
                samesite="lax", max_age=settings.session_ttl, path="/",
            )
    return {
        "id": principal["id"],
        "kind": principal["kind"],
        # Display name (additive): username for a person, identity name for a
        # service. Lets the UI say who is signed in instead of a generic label.
        "name": principal.get("name"),
        "role": principal["role"],
        "space_id": principal["space_id"],
        "application_id": principal["application_id"],
        "scopes": sorted(effective_scopes(principal)),
        "csrf_token": principal.get("csrf") if principal["kind"] == "user" else None,
        # Master mode expiry (epoch seconds) while active on this session, else null.
        "master_until": principal["master_until"] if master_mode_active(principal) else None,
    }
