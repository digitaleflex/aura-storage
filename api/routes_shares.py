"""Share, transfer, and public serving routes extracted from api.main (#344)."""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from . import ids, shares
from .audit import audit_event, set_request_principal
from .authz import ADMIN_READ, ADMIN_WRITE, OBJECTS_READ, authorize, effective_scopes
from .config import settings
from .s3 import presigned_get
from .store import repo
from .transfer import AVAILABLE


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in: int | None = Field(default=None, ge=60)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    content_disposition: Literal["attachment", "inline"] = "attachment"


PREVIEWABLE_CONTENT_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
    "application/pdf",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg",
    "audio/webm", "audio/mp4", "audio/aac", "audio/flac",
    "video/mp4", "video/webm", "video/ogg",
})


def is_previewable(content_type: str) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() in PREVIEWABLE_CONTENT_TYPES


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


def _share_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


router = APIRouter()


@router.get("/s/{token}")
def redeem_share(token: str, request: Request):
    if not shares.is_well_formed(token):
        raise _share_not_found()
    found = repo.get_share_by_token_hash(shares.fingerprint(token))
    now = int(time.time())
    if found is None:
        audit_event("share-access", None, "denied", {"reason": "unknown"})
        raise _share_not_found()
    row = _as_dict(found)
    if row.get("revoked_at"):
        audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "revoked"})
        raise _share_not_found()
    if int(row["expires_at"]) <= now:
        audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "expired"})
        raise _share_not_found()
    set_request_principal(row["space_id"], None)
    target = repo.get_object(row["object_id"], space_id=row["space_id"])
    if target is None or target["status"] != AVAILABLE:
        audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "object_unavailable"})
        raise _share_not_found()
    obj = _as_dict(target)
    from .main import _require_premium, _check_egress_quota, _record_egress, _record_object_event, s3
    if settings.public_download_require_premium and obj.get("published_at"):
        try:
            _require_premium(request)
        except HTTPException:
            audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "premium_required"})
            raise _share_not_found()
    try:
        _check_egress_quota(row["space_id"], int(obj["size_bytes"]))
    except HTTPException:
        audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "egress_quota"})
        raise _share_not_found()
    if not repo.consume_share(row["id"], now):
        audit_event("share-access", None, "denied", {"share_id": row["id"], "reason": "exhausted"})
        raise _share_not_found()
    url = presigned_get(
        s3, obj["bucket"], obj["object_key"], settings.share_presign_ttl,
        content_disposition=shares.content_disposition_header(row["content_disposition"], obj["display_name"]),
        content_type=obj["content_type"],
    )
    _record_egress(row["space_id"], int(obj["size_bytes"]), "share")
    _record_object_event(obj["id"], int(obj["size_bytes"]), "share")
    audit_event("share-access", None, "success", {"share_id": row["id"], "object_id": obj["id"], "use_count": int(row["use_count"]) + 1})
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/api/v1/objects/{oid}/share")
def create_object_share(oid: str, body: ShareIn, principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    oid = _canonical_id(oid, "object id")
    found = repo.get_object(oid, **_object_scope(principal))
    if found is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(found)
    if row["status"] != AVAILABLE:
        raise HTTPException(status_code=409, detail="object not available")
    expires_in = settings.share_ttl_default if body.expires_in is None else body.expires_in
    if expires_in > settings.share_ttl_max:
        raise HTTPException(status_code=422, detail="expires_in exceeds the maximum share lifetime")
    if body.content_disposition == "inline" and not shares.inline_allowed(row["content_type"]):
        raise HTTPException(status_code=422, detail="inline is not allowed for this content type; use attachment")
    token = shares.new_token()
    expires_at = int(time.time()) + expires_in
    sid = repo.create_share(
        object_id=oid, space_id=row["space_id"], created_by=principal["id"],
        created_by_kind=principal["kind"], token_hash=shares.fingerprint(token),
        expires_at=expires_at, content_disposition=body.content_disposition, max_uses=body.max_uses,
    )
    audit_event("share-create", principal["id"], "success", {"object_id": oid, "share_id": sid, "expires_in": expires_in, "max_uses": body.max_uses, "content_disposition": body.content_disposition})
    path = f"/s/{token}"
    return {"id": sid, "object_id": oid, "url": f"{settings.share_base_url}{path}" if settings.share_base_url else path, "token": token, "expires_in": expires_in, "expires_at": expires_at, "max_uses": body.max_uses, "content_disposition": body.content_disposition}


@router.get("/api/v1/objects/{oid}/shares")
def list_object_shares(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    if repo.get_object(oid, **_object_scope(principal)) is None:
        raise HTTPException(status_code=404, detail="object not found")
    now = int(time.time())
    items = []
    for row in repo.list_shares(oid):
        row = _as_dict(row)
        max_uses = row["max_uses"]
        items.append({
            "id": row["id"], "object_id": row["object_id"], "created_by": row["created_by"], "created_by_kind": row["created_by_kind"],
            "content_disposition": row["content_disposition"], "created_at": row["created_at"], "expires_at": row["expires_at"],
            "max_uses": max_uses, "use_count": row["use_count"], "last_used_at": row["last_used_at"], "revoked_at": row["revoked_at"],
            "active": (row["revoked_at"] is None and int(row["expires_at"]) > now and (max_uses is None or int(row["use_count"]) < int(max_uses))),
        })
    return {"items": items}


@router.delete("/api/v1/objects/{oid}/shares/{sid}")
def revoke_object_share(oid: str, sid: str, principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    oid = _canonical_id(oid, "object id")
    sid = _canonical_id(sid, "share id")
    if repo.get_object(oid, **_object_scope(principal)) is None:
        raise HTTPException(status_code=404, detail="object not found")
    found = repo.get_share(sid)
    if found is None or found["object_id"] != oid:
        raise HTTPException(status_code=404, detail="share not found")
    row = _as_dict(found)
    if row["created_by"] != principal["id"]:
        raise HTTPException(status_code=403, detail="forbidden")
    if row["revoked_at"] is not None:
        return {"id": sid, "revoked": True, "revoked_at": row["revoked_at"]}
    now = int(time.time())
    repo.revoke_share(sid, now)
    audit_event("share-revoke", principal["id"], "success", {"object_id": oid, "share_id": sid})
    return {"id": sid, "revoked": True, "revoked_at": now}


@router.get("/api/v1/transfers")
def list_transfers(
    principal: dict = Depends(authorize(OBJECTS_READ)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Literal["available", "failed", "aborted", "expired"] | None = None,
    session_id: str | None = Query(default=None, max_length=64),
    created_after: int | None = Query(default=None, ge=0),
    created_before: int | None = Query(default=None, ge=0),
    from_ts: int | None = Query(default=None, ge=0),
    to_ts: int | None = Query(default=None, ge=0),
    date_from: int | None = Query(default=None, ge=0, alias="from"),
    date_to: int | None = Query(default=None, ge=0, alias="to"),
):
    from .main import _transfer_public
    session = _canonical_id(session_id, "transfer session id") if session_id else None
    lower_bounds = [v for v in (created_after, from_ts, date_from) if v is not None]
    upper_bounds = [v for v in (created_before, to_ts, date_to) if v is not None]
    rows = repo.list_transfer_records(
        **_object_scope(principal), status=status, transfer_session_id=session,
        created_after=max(lower_bounds) if lower_bounds else None,
        created_before=min(upper_bounds) if upper_bounds else None,
        limit=limit, offset=offset,
    )
    has_more = len(rows) == limit
    return {"items": [_transfer_public(row) for row in rows], "next_offset": offset + len(rows) if has_more else None, "has_more": has_more}


@router.get("/api/v1/transfers/{tid}")
def get_transfer(tid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    from .main import _transfer_public
    tid = _canonical_id(tid, "transfer id")
    row = repo.get_transfer_record(tid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="transfer not found")
    return _transfer_public(row)


@router.post("/api/v1/objects/{oid}/download-intent")
def download_intent(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    from .main import _assert_bytes_intact, _check_egress_quota, _record_egress, _record_object_event, s3
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    _assert_bytes_intact(oid, row)
    _check_egress_quota(row["space_id"], int(row["size_bytes"]))
    url = presigned_get(
        s3, row["bucket"], row["object_key"], settings.intent_ttl,
        content_disposition=shares.content_disposition_header("attachment", row["display_name"]),
    )
    _record_egress(row["space_id"], int(row["size_bytes"]), "download")
    _record_object_event(oid, int(row["size_bytes"]), "download")
    audit_event("download-intent", principal["id"], "success", {"object_id": oid})
    return {
        "id": oid, "download_url": url, "method": "GET", "expires_in": settings.intent_ttl,
        "expires_at": int(time.time()) + settings.intent_ttl, "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"], "checksum_sha256": row["checksum_sha256"],
        "checksum_algorithm": "sha256", "range_supported": True, "accept_ranges": "bytes", "content_encoding": row.get("content_encoding"),
    }


@router.post("/api/v1/objects/{oid}/preview-intent")
def preview_intent(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    from .main import _assert_bytes_intact, _check_egress_quota, _record_egress, _record_object_event, s3
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    _assert_bytes_intact(oid, row)
    if not is_previewable(row["content_type"]):
        raise HTTPException(status_code=415, detail="preview not supported for this content type")
    _check_egress_quota(row["space_id"], int(row["size_bytes"]))
    url = presigned_get(
        s3, row["bucket"], row["object_key"], settings.intent_ttl,
        content_disposition="inline", content_type=row["content_type"],
    )
    _record_egress(row["space_id"], int(row["size_bytes"]), "preview")
    _record_object_event(oid, int(row["size_bytes"]), "view")
    audit_event("preview-intent", principal["id"], "success", {"object_id": oid})
    return {
        "id": oid, "preview_url": url, "method": "GET", "expires_in": settings.intent_ttl,
        "expires_at": int(time.time()) + settings.intent_ttl, "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"],
    }
