"""Object mutation routes extracted from api.main (#343)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict

from . import ids
from .audit import audit_event
from .authz import ADMIN_READ, ADMIN_WRITE, OBJECTS_DELETE, OBJECTS_READ, OBJECTS_WRITE, authorize, effective_scopes
from .store import repo
from .transfer import AVAILABLE, DELETED


def _canonical_uuid(value: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]


class ObjectPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: Uuid4 | None = None


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _object_scope(principal: dict) -> dict:
    owner_id = principal["id"] if principal["kind"] == "user" else None
    if principal["kind"] == "user" and effective_scopes(principal) & {ADMIN_READ, ADMIN_WRITE}:
        owner_id = None
    return {"space_id": principal["space_id"], "owner_id": owner_id}


router = APIRouter()


@router.get("/api/v1/objects/{oid}/analytics")
def object_analytics(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    from .main import _usage_period
    oid = _canonical_id(oid, "object id")
    if repo.get_object(oid, **_object_scope(principal)) is None:
        raise HTTPException(status_code=404, detail="object not found")
    period = _usage_period()
    month = repo.get_object_usage(oid, period) or {}
    totals = repo.get_object_usage_totals(oid)
    return {
        "object_id": oid, "period": period,
        "month": {
            "views": int(month.get("views") or 0),
            "downloads": int(month.get("downloads") or 0),
            "share_opens": int(month.get("share_opens") or 0),
            "egress_bytes": int(month.get("egress_bytes") or 0),
        },
        "totals": {
            "views": int(totals.get("views") or 0),
            "downloads": int(totals.get("downloads") or 0),
            "share_opens": int(totals.get("share_opens") or 0),
            "egress_bytes": int(totals.get("egress_bytes") or 0),
        },
        "last_access_at": totals.get("last_access_at"),
    }


@router.delete("/api/v1/objects/{oid}")
def soft_delete_object(oid: str, principal: dict = Depends(authorize(OBJECTS_DELETE))):
    from .main import _abort_multipart_session
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] not in ("available", "pending"):
        raise HTTPException(status_code=409, detail="object not deletable")
    if row["status"] == "pending":
        _abort_multipart_session(row)
    repo.set_status(oid, "deleted")
    audit_event("delete", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "deleted"}


@router.post("/api/v1/objects/{oid}/restore")
def restore_object(oid: str, principal: dict = Depends(authorize(OBJECTS_DELETE))):
    from .main import _object_public
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != DELETED:
        raise HTTPException(status_code=409, detail="object is not in the trash")
    if row["size_bytes"] < 0:
        raise HTTPException(status_code=409, detail="object was never uploaded")
    repo.set_status(oid, AVAILABLE)
    audit_event("restore", principal["id"], "success", {"object_id": oid})
    return _object_public(repo.get_object(oid, **_object_scope(principal)))


@router.patch("/api/v1/objects/{oid}")
def update_object(oid: str, body: ObjectPatchIn, principal: dict = Depends(authorize(OBJECTS_WRITE, human=True))):
    from .main import _object_public
    oid = _canonical_id(oid, "object id")
    if "folder_id" not in body.model_fields_set:
        raise HTTPException(status_code=422, detail="no fields to update")
    if repo.get_object(oid, **_object_scope(principal)) is None:
        raise HTTPException(status_code=404, detail="object not found")
    if body.folder_id is not None and repo.get_folder(body.folder_id, owner_id=principal["id"]) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    repo.set_object_folder(oid, folder_id=body.folder_id)
    audit_event("object.move", principal["id"], "success", {"object_id": oid, "folder_id": body.folder_id})
    return _object_public(repo.get_object(oid, **_object_scope(principal)))
