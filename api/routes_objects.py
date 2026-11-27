"""Object catalogue routes extracted from api.main (#343)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from . import ids
from .authz import ADMIN_READ, ADMIN_WRITE, OBJECTS_READ, authorize, effective_scopes
from .store import repo

ObjectStatus = Literal["pending", "verifying", "available", "suspect", "deleted", "expired", "failed", "aborted", "purging"]
ObjectSort = Literal["created_at", "display_name", "size_bytes"]
SortOrder = Literal["asc", "desc"]


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _object_scope(principal: dict) -> dict:
    owner_id = principal["id"] if principal["kind"] == "user" else None
    if principal["kind"] == "user" and effective_scopes(principal) & {ADMIN_READ, ADMIN_WRITE}:
        owner_id = None
    return {"space_id": principal["space_id"], "owner_id": owner_id}


router = APIRouter()


@router.get("/api/v1/objects")
def list_objects(
    principal: dict = Depends(authorize(OBJECTS_READ)), limit: int = 50, offset: int = 0,
    folder_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
    status: ObjectStatus | None = None,
    content_type: str | None = Query(default=None, max_length=1000),
    min_size: int | None = Query(default=None, ge=0),
    max_size: int | None = Query(default=None, ge=0),
    created_after: int | None = Query(default=None, ge=0),
    created_before: int | None = Query(default=None, ge=0),
    tag: str | None = Query(default=None, max_length=32),
    tags: str | None = Query(default=None, max_length=400),
    tag_mode: Literal["all", "any"] = "all",
    sort: ObjectSort = "created_at",
    order: SortOrder = "desc",
):
    from .main import _object_public, _query_tags
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    folder_filter: str | None = None
    if folder_id is not None:
        folder_filter = "" if folder_id == "root" else _canonical_id(folder_id, "folder id")
    needle = (q or "").strip() or None
    search_needle = (search or "").strip() or None
    rows = repo.list_objects(
        **_object_scope(principal), folder_id=folder_filter, q=needle,
        search=search_needle,
        status=status, hide_deleted=status is None,
        content_type=(content_type or None),
        min_size=min_size, max_size=max_size,
        created_after=created_after, created_before=created_before,
        tag=(tag.strip().lower() or None) if tag else None,
        tags=_query_tags(tags), tag_mode=tag_mode,
        sort=sort, order=order, limit=limit, offset=offset,
    )
    tag_map = repo.list_tags_for_objects([r["id"] for r in rows])
    return {"items": [_object_public(r, tag_map.get(r["id"])) for r in rows]}


@router.get("/api/v1/objects/{oid}")
def get_object(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    from .main import _object_public
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    return _object_public(row, repo.get_object_tags(oid))
