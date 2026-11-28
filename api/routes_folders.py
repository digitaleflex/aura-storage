"""Logical folder CRUD and folder share routes extracted from api.main (#346).

Folders are human-owned catalogue metadata: no bytes, no host directories.
The public redemption routes (/f/{token}) stay in api.main.
"""
from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from . import ids, shares
from .audit import audit_event
from .authz import OBJECTS_DELETE, OBJECTS_READ, OBJECTS_WRITE, authorize
from .config import settings
from .store import repo

MAX_FOLDER_DEPTH = 32


def _canonical_uuid(value: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]


def _validate_folder_name(value: str) -> str:
    name = value.strip()
    if not name or name in (".", ".."):
        raise ValueError("invalid folder name")
    if any(ch in name for ch in ("/", "\\")) or any(ord(ch) < 32 for ch in name):
        raise ValueError("invalid folder name")
    return name


def _as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _folder_public(row, size_bytes: int | None = None) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "created_at": row["created_at"],
        "size_bytes": size_bytes,
    }


def _folder_owner(principal: dict) -> str:
    # ``folders.owner_id`` references ``users.id`` (NOT NULL): folder management
    # is a human-user capability, enforced by authorize(..., human=True).
    return principal["id"]


def _folder_depth(fid: str, owner_id: str) -> int:
    depth = 0
    current: str | None = fid
    while current is not None:
        depth += 1
        if depth > MAX_FOLDER_DEPTH:
            return depth
        row = repo.get_folder(current, owner_id=owner_id)
        current = row["parent_id"] if row else None
    return depth


def _folder_subtree_height(fid: str, owner_id: str) -> int:
    height = 1
    frontier = [fid]
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            nxt.extend(
                c["id"] for c in repo.list_folders(owner_id=owner_id, parent_id=node)
            )
        if nxt:
            height += 1
        frontier = nxt
    return height


class FolderShareIn(BaseModel):
    """Create a public read-only link for a whole folder subtree."""
    model_config = ConfigDict(extra="forbid")
    expires_in: int | None = Field(default=None, ge=60)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)


class FolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_id: Uuid4 | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _validate_folder_name(value)


class FolderPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: Uuid4 | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_folder_name(value)


router = APIRouter()


@router.get("/api/v1/folders")
def list_folders(
    parent_id: str | None = None,
    all: bool = False,
    principal: dict = Depends(authorize(OBJECTS_READ, human=True)),
):
    owner_id = _folder_owner(principal)
    if all and parent_id is not None:
        raise HTTPException(
            status_code=422, detail="all cannot be combined with parent_id"
        )
    if all:
        rows = repo.list_all_folders(owner_id=owner_id)
        return {
            "items": [
                _folder_public(r, size_bytes=repo.get_folder_size(folder_id=r["id"], owner_id=owner_id))
                for r in rows
            ]
        }
    if parent_id is not None:
        parent_id = _canonical_id(parent_id, "parent id")
        if repo.get_folder(parent_id, owner_id=owner_id) is None:
            raise HTTPException(status_code=404, detail="folder not found")
    rows = repo.list_folders(owner_id=owner_id, parent_id=parent_id)
    return {
        "items": [
            _folder_public(r, size_bytes=repo.get_folder_size(folder_id=r["id"], owner_id=owner_id))
            for r in rows
        ]
    }


@router.get("/api/v1/folders/{fid}")
def get_folder(fid: str, principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    fid = _canonical_id(fid, "folder id")
    owner_id = _folder_owner(principal)
    row = repo.get_folder(fid, owner_id=owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return _folder_public(
        row, size_bytes=repo.get_folder_size(folder_id=fid, owner_id=owner_id)
    )


@router.post("/api/v1/folders")
def create_folder(body: FolderIn, principal: dict = Depends(authorize(OBJECTS_WRITE, human=True))):
    owner_id = _folder_owner(principal)
    if body.parent_id is not None:
        if repo.get_folder(body.parent_id, owner_id=owner_id) is None:
            raise HTTPException(status_code=404, detail="parent folder not found")
        if _folder_depth(body.parent_id, owner_id) >= MAX_FOLDER_DEPTH:
            raise HTTPException(status_code=409, detail="folder depth limit reached")
    if repo.folder_name_exists(owner_id=owner_id, parent_id=body.parent_id, name=body.name):
        raise HTTPException(status_code=409, detail="folder name already exists")
    fid = repo.create_folder(owner_id, body.name, body.parent_id)
    audit_event("folder.create", principal["id"], "success", {"folder_id": fid})
    return _folder_public(repo.get_folder(fid, owner_id=owner_id))


@router.patch("/api/v1/folders/{fid}")
def update_folder(
    fid: str, body: FolderPatchIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    fid = _canonical_id(fid, "folder id")
    owner_id = _folder_owner(principal)
    row = repo.get_folder(fid, owner_id=owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder not found")
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    if "name" in fields and body.name is None:
        raise HTTPException(status_code=422, detail="name cannot be null")
    new_name = body.name if "name" in fields else row["name"]
    new_parent = body.parent_id if "parent_id" in fields else row["parent_id"]

    if "parent_id" in fields and new_parent is not None:
        if new_parent == fid:
            raise HTTPException(status_code=409, detail="folder cannot be its own parent")
        current: str | None = new_parent
        depth = 0
        while current is not None:
            if current == fid:
                raise HTTPException(
                    status_code=409, detail="cannot move a folder into its own subtree"
                )
            depth += 1
            if depth > MAX_FOLDER_DEPTH:
                raise HTTPException(status_code=409, detail="folder depth limit reached")
            parent_row = repo.get_folder(current, owner_id=owner_id)
            if parent_row is None:
                raise HTTPException(status_code=404, detail="parent folder not found")
            current = parent_row["parent_id"]
        if depth + _folder_subtree_height(fid, owner_id) > MAX_FOLDER_DEPTH:
            raise HTTPException(status_code=409, detail="folder depth limit reached")

    if (new_name != row["name"] or new_parent != row["parent_id"]) and (
        repo.folder_name_exists(
            owner_id=owner_id, parent_id=new_parent, name=new_name, exclude_id=fid
        )
    ):
        raise HTTPException(status_code=409, detail="folder name already exists")

    if "name" in fields and new_name != row["name"]:
        repo.rename_folder(fid, owner_id=owner_id, name=new_name)
    if "parent_id" in fields and new_parent != row["parent_id"]:
        repo.set_folder_parent(fid, owner_id=owner_id, parent_id=new_parent)
    audit_event("folder.update", principal["id"], "success", {"folder_id": fid})
    return _folder_public(repo.get_folder(fid, owner_id=owner_id))


@router.delete("/api/v1/folders/{fid}")
def delete_folder(fid: str, principal: dict = Depends(authorize(OBJECTS_DELETE, human=True))):
    fid = _canonical_id(fid, "folder id")
    owner_id = _folder_owner(principal)
    if repo.get_folder(fid, owner_id=owner_id) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    if repo.folder_child_count(fid, owner_id=owner_id) > 0:
        raise HTTPException(status_code=409, detail="folder is not empty")
    if repo.folder_object_count(fid, owner_id=owner_id) > 0:
        raise HTTPException(status_code=409, detail="folder is not empty")
    # Hidden leftovers are detached before the row disappears so the FK does
    # not refuse the delete; they survive until an explicit trash purge.
    repo.release_folder_objects(fid, owner_id=owner_id)
    repo.delete_folder(fid, owner_id=owner_id)
    audit_event("folder.delete", principal["id"], "success", {"folder_id": fid})
    return {"id": fid, "status": "deleted"}


@router.post("/api/v1/folders/{fid}/share")
def create_folder_share(
    fid: str, body: FolderShareIn,
    principal: dict = Depends(authorize(OBJECTS_READ, human=True)),
):
    fid = _canonical_id(fid, "folder id")
    if repo.get_folder(fid, owner_id=_folder_owner(principal)) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    if not principal.get("space_id"):
        raise HTTPException(status_code=409, detail="account has no space")

    expires_in = (
        settings.share_ttl_default if body.expires_in is None else body.expires_in
    )
    if expires_in > settings.share_ttl_max:
        raise HTTPException(
            status_code=422, detail="expires_in exceeds the maximum share lifetime"
        )

    token = shares.new_token()
    expires_at = int(time.time()) + expires_in
    sid = repo.create_folder_share(
        folder_id=fid,
        space_id=principal["space_id"],
        created_by=principal["id"],
        created_by_kind=principal["kind"],
        token_hash=shares.fingerprint(token),
        expires_at=expires_at,
        max_uses=body.max_uses,
    )
    audit_event("folder-share-create", principal["id"], "success", {
        "folder_id": fid, "folder_share_id": sid, "expires_in": expires_in,
        "max_uses": body.max_uses,
    })
    path = f"/f/{token}"
    return {
        "id": sid, "folder_id": fid,
        "url": f"{settings.share_base_url}{path}" if settings.share_base_url else path,
        "token": token,
        "expires_in": expires_in, "expires_at": expires_at,
        "max_uses": body.max_uses,
    }


@router.get("/api/v1/folders/{fid}/shares")
def list_folder_shares(
    fid: str, principal: dict = Depends(authorize(OBJECTS_READ, human=True)),
):
    fid = _canonical_id(fid, "folder id")
    if repo.get_folder(fid, owner_id=_folder_owner(principal)) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    now = int(time.time())
    items = []
    for row in repo.list_folder_shares(fid):
        row = _as_dict(row)
        max_uses = row["max_uses"]
        items.append({
            "id": row["id"], "folder_id": row["folder_id"],
            "created_by": row["created_by"], "created_by_kind": row["created_by_kind"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "max_uses": max_uses, "use_count": row["use_count"],
            "last_used_at": row["last_used_at"], "revoked_at": row["revoked_at"],
            "active": (
                row["revoked_at"] is None
                and int(row["expires_at"]) > now
                and (max_uses is None or int(row["use_count"]) < int(max_uses))
            ),
        })
    return {"items": items}


@router.delete("/api/v1/folders/{fid}/shares/{sid}")
def revoke_folder_share(
    fid: str, sid: str,
    principal: dict = Depends(authorize(OBJECTS_READ, human=True)),
):
    fid = _canonical_id(fid, "folder id")
    sid = _canonical_id(sid, "share id")
    if repo.get_folder(fid, owner_id=_folder_owner(principal)) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    found = repo.get_folder_share(sid)
    if found is None or found["folder_id"] != fid:
        raise HTTPException(status_code=404, detail="share not found")
    row = _as_dict(found)
    if row["created_by"] != principal["id"]:
        raise HTTPException(status_code=403, detail="forbidden")
    if row["revoked_at"] is not None:
        return {"id": sid, "revoked": True, "revoked_at": row["revoked_at"]}
    now = int(time.time())
    repo.revoke_folder_share(sid, now)
    audit_event("folder-share-revoke", principal["id"], "success", {
        "folder_id": fid, "folder_share_id": sid,
    })
    return {"id": sid, "revoked": True, "revoked_at": now}
