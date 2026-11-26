"""Object admin/public ops routes extracted from api.main (#343)."""
from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import ids
from .audit import audit_event
from .authz import OBJECTS_PURGE, OBJECTS_WRITE, authorize
from .config import settings
from .store import repo
from .transfer import AVAILABLE, DELETED


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _object_scope(principal: dict) -> dict:
    from .authz import ADMIN_READ, ADMIN_WRITE, effective_scopes
    owner_id = principal["id"] if principal["kind"] == "user" else None
    if principal["kind"] == "user" and effective_scopes(principal) & {ADMIN_READ, ADMIN_WRITE}:
        owner_id = None
    return {"space_id": principal["space_id"], "owner_id": owner_id}


class BulkIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1)


class PublicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str | None = Field(default=None, max_length=63)
    published: bool = True

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from .main import _normalize_slug
        return _normalize_slug(value)


router = APIRouter()


@router.post("/api/v1/objects/bulk-purge")
def bulk_purge(body: BulkIdsIn, principal: dict = Depends(authorize(OBJECTS_PURGE, human=True))):
    from .main import _require_master, _bulk_purge
    _require_master(principal)
    if len(body.ids) > settings.master_bulk_max:
        raise HTTPException(status_code=422, detail=f"at most {settings.master_bulk_max} ids per call")
    return _bulk_purge(body.ids, principal)


@router.post("/api/v1/objects/trash/empty")
def empty_trash(principal: dict = Depends(authorize(OBJECTS_PURGE, human=True))):
    from .main import _require_master, _bulk_purge
    _require_master(principal)
    scope = {"space_id": principal["space_id"], "owner_id": principal["id"]}
    rows = repo.list_objects(**scope, status=DELETED, limit=settings.master_bulk_max)
    ids_ = [_as_dict(r)["id"] for r in rows]
    out = _bulk_purge(ids_, principal)
    out["more"] = bool(repo.list_objects(**scope, status=DELETED, limit=1))
    return out


@router.post("/api/v1/objects/{oid}/public-access")
def create_public_access(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    from .main import _require_public_access_scopes
    _require_public_access_scopes(principal)
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE:
        raise HTTPException(status_code=409, detail="object not available")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + settings.public_access_grant_ttl
    repo.create_public_access_grant(
        hashlib.sha256(token.encode("utf-8")).hexdigest(),
        oid, row["space_id"], principal["id"], now, expires_at,
    )
    audit_event("public-access-grant", principal["id"], "created", {"object_id": oid, "expires_at": expires_at})
    return {"token": token, "url": f"/a/{token}", "expires_at": expires_at}


@router.delete("/api/v1/objects/{oid}/public-access")
def revoke_public_access(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    from .main import _require_public_access_scopes
    _require_public_access_scopes(principal)
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    revoked = repo.revoke_public_access_grants_for_object(oid, int(time.time()))
    audit_event("public-access-grant", principal["id"], "revoked", {"object_id": oid, "count": revoked})
    return {"revoked": revoked}


@router.put("/api/v1/objects/{oid}/publication")
def set_object_publication(oid: str, body: PublicationIn, principal: dict = Depends(authorize(OBJECTS_WRITE, human=True))):
    from .main import _object_public
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE:
        raise HTTPException(status_code=409, detail="object not available")
    if body.published and not body.slug:
        raise HTTPException(status_code=422, detail="slug is required to publish")
    if body.slug:
        existing = repo.get_object_by_slug(body.slug)
        if existing is not None and existing["id"] != oid:
            raise HTTPException(status_code=409, detail="slug already in use")
    published_at = int(time.time()) if body.published else None
    repo.set_object_publication(oid, body.slug, published_at)
    audit_event("object.publish" if body.published else "object.unpublish", principal["id"], "success", {"object_id": oid, "slug": body.slug})
    return _object_public(repo.get_object(oid, **_object_scope(principal)))
