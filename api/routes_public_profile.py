"""Public profile/stats routes extracted from api.main (#346)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .audit import audit_event
from .authz import require_public
from .config import settings
from .store import repo


class PublicProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=120)


router = APIRouter()


@router.get("/api/public/me")
def public_me(request: Request, response: Response, principal: dict = Depends(require_public)):
    sid = request.cookies.get(settings.public_session_cookie)
    session_id = principal.get("session_id")
    if sid and session_id:
        now = int(time.time())
        expires_at = now + settings.public_session_ttl
        repo.extend_session(session_id, expires_at)
        response.set_cookie(
            settings.public_session_cookie, sid, httponly=True,
            secure=settings.cookie_secure, samesite="lax",
            max_age=settings.public_session_ttl, path="/",
        )
    return {
        "id": principal["id"],
        "name": principal.get("name"),
        "display_name": principal.get("display_name", ""),
        "email": principal.get("email"),
        "role": principal["role"],
        "plan": principal.get("plan", "free"),
        "csrf_token": principal["csrf"],
    }


@router.patch("/api/public/me")
def public_me_patch(body: PublicProfilePatch, principal: dict = Depends(require_public)):
    from .main import _clean_display_name
    display_name = _clean_display_name(body.display_name)
    repo.update_user_display_name(principal["id"], display_name)
    audit_event("public-profile", principal["id"], "success", {"action": "update"})
    return {"ok": True, "display_name": display_name}


@router.delete("/api/public/me")
def public_me_delete(principal: dict = Depends(require_public)):
    uid = principal["id"]
    repo.delete_public_account(uid)
    audit_event("public-account-delete", uid, "success")
    out = JSONResponse({"ok": True})
    out.delete_cookie(
        settings.public_session_cookie, path="/", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return out


@router.post("/api/public/logout")
def public_logout(principal: dict = Depends(require_public)):
    repo.delete_session(principal["session_id"])
    audit_event("public-logout", principal["id"], "success")
    out = RedirectResponse("/", status_code=303)
    out.delete_cookie(
        settings.public_session_cookie, path="/", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return out


@router.get("/api/public/stats")
def public_stats(principal: dict = Depends(require_public)):
    from .main import _public_listening_stats
    return _public_listening_stats(principal)
