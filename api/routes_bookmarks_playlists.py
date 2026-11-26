"""Bookmark and playlist routes extracted from api.main (#347)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from . import ids
from .authz import require_public
from .store import repo


def _canonical_uuid(value: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]


class BookmarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)
    note: str = Field(default="", max_length=200)


class PlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


router = APIRouter()


@router.get("/api/public/bookmarks")
def public_bookmarks(object_id: str, principal: dict = Depends(require_public)):
    from .main import _published_book_or_404
    oid = _published_book_or_404(object_id)
    return {"object_id": oid, "bookmarks": repo.list_bookmarks(principal["id"], oid)}


@router.post("/api/public/bookmarks")
def public_bookmark_add(body: BookmarkIn, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check, _published_book_or_404, _BOOKMARKS_PER_BOOK
    _public_rate_check("progress", request)
    oid = _published_book_or_404(body.object_id)
    note = "".join(ch for ch in body.note if ch.isprintable()).strip()
    saved = repo.add_bookmark(
        principal["id"], oid, round(body.position_seconds, 1), note, int(time.time()),
        _BOOKMARKS_PER_BOOK,
    )
    if saved is None:
        raise HTTPException(status_code=409, detail="too many bookmarks on this book")
    return saved


@router.delete("/api/public/bookmarks/{bookmark_id}")
def public_bookmark_delete(bookmark_id: str, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check
    _public_rate_check("progress", request)
    bid = _canonical_id(bookmark_id, "bookmark id")
    if not repo.delete_bookmark(principal["id"], bid):
        raise HTTPException(status_code=404, detail="bookmark not found")
    return {"ok": True}


@router.get("/api/public/playlists")
def public_playlists(principal: dict = Depends(require_public)):
    return {"playlists": repo.list_listen_playlists(principal["id"])}


@router.post("/api/public/playlists")
def public_playlist_create(body: PlaylistIn, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check
    _public_rate_check("progress", request)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    return {"playlist": repo.create_listen_playlist(principal["id"], name, int(time.time()))}


@router.patch("/api/public/playlists/{pid}")
def public_playlist_rename(pid: str, body: PlaylistIn, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check, _own_playlist_or_404
    _public_rate_check("progress", request)
    current = _own_playlist_or_404(pid, principal)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    if not repo.rename_listen_playlist(principal["id"], current["id"], name, int(time.time())):
        raise HTTPException(status_code=404, detail="playlist not found")
    return {"playlist": {"id": current["id"], "name": name}}


@router.delete("/api/public/playlists/{pid}")
def public_playlist_delete(pid: str, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check, _own_playlist_or_404
    _public_rate_check("progress", request)
    current = _own_playlist_or_404(pid, principal)
    if not repo.delete_listen_playlist(principal["id"], current["id"]):
        raise HTTPException(status_code=404, detail="playlist not found")
    return {"ok": True}


@router.get("/api/public/playlists/{pid}/items")
def public_playlist_items(pid: str, principal: dict = Depends(require_public)):
    from .main import _own_playlist_or_404
    current = _own_playlist_or_404(pid, principal)
    return {"playlist_id": current["id"], "items": repo.list_listen_playlist_items(current["id"])}


@router.put("/api/public/playlists/{pid}/items/{oid}")
def public_playlist_add_item(pid: str, oid: str, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check, _own_playlist_or_404, _published_book_or_404
    _public_rate_check("progress", request)
    current = _own_playlist_or_404(pid, principal)
    oid = _published_book_or_404(oid)
    items = repo.list_listen_playlist_items(current["id"])
    position = max((int(i["position"]) for i in items), default=-1) + 1
    added = repo.add_listen_playlist_item(current["id"], oid, position, int(time.time()))
    return {"object_id": oid, "added": added}


@router.delete("/api/public/playlists/{pid}/items/{oid}")
def public_playlist_remove_item(pid: str, oid: str, request: Request, principal: dict = Depends(require_public)):
    from .main import _public_rate_check, _own_playlist_or_404
    _public_rate_check("progress", request)
    current = _own_playlist_or_404(pid, principal)
    oid = _canonical_id(oid, "object id")
    if not repo.remove_listen_playlist_item(current["id"], oid, int(time.time())):
        raise HTTPException(status_code=404, detail="item not found in playlist")
    return {"ok": True}
