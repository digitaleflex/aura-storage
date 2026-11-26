"""Public library/progress/favorites routes extracted from api.main (#346)."""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from . import ids
from .audit import audit_event, set_request_principal
from .authz import require_public
from .store import repo
from .transfer import AVAILABLE


def _canonical_uuid(value: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


router = APIRouter()


@router.get("/api/public/library")
def public_library(principal: dict = Depends(require_public)):
    from .main import _public_collections
    collections = _public_collections(principal)
    set_request_principal(principal.get("space_id"), principal.get("application_id"))
    audit_event("public-library", principal["id"], "success")
    return {"collections": collections}


@router.post("/api/public/progress")
def public_progress(body: ProgressIn, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check
    _public_rate_check("progress", request)
    oid = _canonical_id(body.object_id, "object id")
    row = repo.get_object_unscoped(oid)
    row = _as_dict(row) if row is not None else None
    if row is None or not row.get("published_at") or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="object not found")
    repo.save_progress(principal["id"], oid, body.position_seconds, int(time.time()))
    return {"object_id": oid, "position_seconds": body.position_seconds}


@router.get("/api/public/progress")
def public_progress_get(object_id: str, principal: dict = Depends(require_public)):
    from .main import _published_book_or_404
    oid = _published_book_or_404(object_id)
    position = repo.get_progress_map(principal["id"], [oid]).get(oid, 0)
    return {"object_id": oid, "position_seconds": position}


def _set_public_favorite(oid: str, request: Request, principal: dict, favorite: bool) -> dict:
    from .main import _public_rate_check
    _public_rate_check("progress", request)
    oid = _canonical_id(oid, "object id")
    row = repo.get_object_unscoped(oid)
    row = _as_dict(row) if row is not None else None
    if row is None or not row.get("published_at") or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="object not found")
    repo.set_favorite(principal["id"], oid, favorite, int(time.time()))
    return {"object_id": oid, "favorite": favorite}


@router.put("/api/public/favorites/{oid}")
def public_favorite_add(oid: str, request: Request, principal: dict = Depends(require_public)):
    return _set_public_favorite(oid, request, principal, True)


@router.delete("/api/public/favorites/{oid}")
def public_favorite_remove(oid: str, request: Request, principal: dict = Depends(require_public)):
    return _set_public_favorite(oid, request, principal, False)
