"""Public library/progress/favorites routes extracted from api.main (#346)."""
from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from . import ids, listen_events
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
    """Playback position posted by the public player (CSRF-protected).

    ``kind`` is advisory: the server decides ``start`` for a first sample or a
    backward seek, and only accepts ``end`` from the player. ``client_event_id``
    is an optional deduplication key for retried samples (#320).
    """
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)
    kind: Literal["start", "position", "end"] = "position"
    client_event_id: str = Field(default="", max_length=120)


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
    # Public users are not scoped to the publisher's space: they may only save
    # progress for an object that is actually published, nothing else.
    row = repo.get_object_unscoped(oid)
    row = _as_dict(row) if row is not None else None
    if row is None or not row.get("published_at") or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="object not found")
    now = int(time.time())
    uid = principal["id"]
    previous_position = repo.get_progress_map(uid, [oid]).get(oid, 0.0)
    last_event_at = repo.last_listen_event_at(uid, oid)
    # A first sample, or a backward seek (a new playback session), starts a
    # session; the player may explicitly close one with ``end``. A plain sample
    # counts at most the elapsed wall-clock time, so seeking forward cannot be
    # reported as listening (#320).
    if last_event_at <= 0 or body.position_seconds < float(previous_position):
        kind = "start"
    elif body.kind == "end":
        kind = "end"
    else:
        kind = "position"
    elapsed = max(0, now - last_event_at) if last_event_at else 0
    delta = (
        listen_events.listened_delta(
            float(previous_position), body.position_seconds, elapsed,
        )
        if kind != "start" else 0.0
    )
    repo.record_listen_event(
        uid, oid, kind, body.position_seconds, delta, now, body.client_event_id,
    )
    repo.save_progress(uid, oid, body.position_seconds, now)
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
