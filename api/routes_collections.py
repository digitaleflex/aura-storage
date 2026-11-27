"""Collection/tag routes extracted from api.main (#347)."""
from __future__ import annotations

import re
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from . import ids
from .audit import audit_event, set_request_principal
from .authz import ADMIN_READ, ADMIN_WRITE, OBJECTS_READ, OBJECTS_WRITE, authorize, effective_scopes
from .store import repo
from .transfer import AVAILABLE


def _canonical_uuid(value: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]
_PUBLIC_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
_TAG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _PUBLIC_SLUG_RE.fullmatch(slug):
        raise ValueError("slug must be 2-63 characters: lowercase letters, digits and dashes")
    return slug


def _normalize_tags(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        tag = raw.strip().lower()
        if not tag:
            continue
        if not _TAG_RE.fullmatch(tag):
            raise ValueError("tags must be 1-32 characters: lowercase letters, digits and dashes")
        if tag not in out:
            out.append(tag)
    if len(out) > 20:
        raise ValueError("at most 20 tags per object")
    return out


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


class TagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)


class CollectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=2, max_length=63)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str) -> str:
        return _normalize_slug(value)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class CollectionPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    published: bool | None = None


class CollectionItemsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[Uuid4] = Field(default_factory=list, max_length=500)


def _collection_public(col: dict) -> dict:
    row = _as_dict(col)
    return {
        "id": row["id"],
        "space_id": row["space_id"],
        "owner_id": row["owner_id"],
        "slug": row["slug"],
        "title": row["title"],
        "description": row.get("description") or "",
        "published_at": row.get("published_at"),
        "item_count": int(row.get("item_count") or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _owned_collection(cid: str, principal: dict) -> dict:
    cid = _canonical_id(cid, "collection id")
    col = repo.get_collection(cid)
    if col is None or col["owner_id"] != principal["id"]:
        raise HTTPException(status_code=404, detail="collection not found")
    return _as_dict(col)


router = APIRouter()


@router.get("/api/v1/objects/tags")
def list_object_tags(
    principal: dict = Depends(authorize(OBJECTS_READ)),
    limit: int = Query(default=200, ge=1, le=500),
):
    rows = repo.list_tag_counts(**_object_scope(principal), limit=limit)
    return {"items": [{"tag": row["tag"], "count": row["n"]} for row in rows]}


@router.put("/api/v1/objects/{oid}/tags")
def set_object_tags(
    oid: str, body: TagsIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    repo.set_object_tags(oid, body.tags)
    audit_event("object.tags", principal["id"], "success",
                {"object_id": oid, "tags": body.tags})
    fresh = repo.get_object(oid, **_object_scope(principal))
    from .main import _object_public
    return _object_public(fresh, repo.get_object_tags(oid))


@router.get("/api/v1/collections")
def list_collections(principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    items = repo.list_collections(principal["space_id"], owner_id=principal["id"])
    return {"items": [_collection_public(c) for c in items]}


@router.post("/api/v1/collections")
def create_collection(
    body: CollectionIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    if repo.get_collection_by_slug(body.slug) is not None:
        raise HTTPException(status_code=409, detail="slug already in use")
    cid = repo.new_id()
    repo.create_collection(
        cid, principal["space_id"], principal["id"], body.slug,
        body.title, body.description,
    )
    audit_event("collection.create", principal["id"], "success",
                {"collection_id": cid, "slug": body.slug})
    return _collection_public(repo.get_collection(cid))


@router.get("/api/v1/collections/{cid}")
def get_collection(cid: str, principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    col = _owned_collection(cid, principal)
    items = repo.get_collection_items(col["id"])
    from .main import _object_public
    return {
        **_collection_public({**col, "item_count": len(items)}),
        "items": [_object_public(row) for row in items],
    }


@router.patch("/api/v1/collections/{cid}")
def update_collection(
    cid: str, body: CollectionPatchIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    col = _owned_collection(cid, principal)
    fields = body.model_fields_set
    title = body.title if "title" in fields and body.title is not None else col["title"]
    description = (
        body.description if "description" in fields and body.description is not None
        else (col.get("description") or "")
    )
    published_at = col.get("published_at")
    if "published" in fields and body.published is not None:
        if body.published:
            if not repo.get_collection_items(col["id"]):
                raise HTTPException(status_code=422, detail="a pack needs items to be published")
            published_at = published_at or int(time.time())
        else:
            published_at = None
    repo.update_collection(col["id"], " ".join(title.split()), description, published_at)
    audit_event("collection.update", principal["id"], "success", {
        "collection_id": col["id"], "published": published_at is not None,
    })
    return _collection_public(repo.get_collection(col["id"]))


@router.put("/api/v1/collections/{cid}/items")
def set_collection_items(
    cid: str, body: CollectionItemsIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    col = _owned_collection(cid, principal)
    seen: list[str] = []
    for oid in body.object_ids:
        row = repo.get_object(oid, **_object_scope(principal))
        if row is None or row["status"] != AVAILABLE:
            raise HTTPException(status_code=404, detail="object not found or available")
        if oid not in seen:
            seen.append(oid)
    repo.replace_collection_items(col["id"], seen)
    audit_event("collection.items", principal["id"], "success", {
        "collection_id": col["id"], "count": len(seen),
    })
    fresh = repo.get_collection(col["id"])
    return _collection_public({**fresh, "item_count": len(seen)})


@router.delete("/api/v1/collections/{cid}")
def delete_collection(cid: str, principal: dict = Depends(authorize(OBJECTS_WRITE, human=True))):
    col = _owned_collection(cid, principal)
    repo.delete_collection(col["id"])
    audit_event("collection.delete", principal["id"], "success",
                {"collection_id": col["id"], "slug": col["slug"]})
    return {"id": col["id"], "deleted": True}


@router.get("/p/{slug}.json")
def public_collection_manifest(slug: str):
    if not _PUBLIC_SLUG_RE.fullmatch(slug or ""):
        raise HTTPException(status_code=404, detail="not found")
    col = repo.get_collection_by_slug(slug)
    if col is None or not col.get("published_at"):
        raise HTTPException(status_code=404, detail="not found")
    set_request_principal(col["space_id"], None)
    from .main import _library_items
    items = _library_items(col)
    audit_event("collection.access", None, "success", {
        "collection_id": col["id"], "slug": slug,
    })
    return {
        "slug": col["slug"], "title": col["title"],
        "description": col.get("description") or "",
        "updated_at": col["updated_at"], "items": items,
    }
