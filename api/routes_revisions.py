"""Object revision routes extracted from api.main (#348)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from . import ids, shares
from .audit import audit_event
from .authz import ADMIN_READ, ADMIN_WRITE, OBJECTS_READ, OBJECTS_WRITE, authorize, effective_scopes
from .config import settings
from .s3 import copy_object, presigned_get
from .store import repo


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

# --- Content revisions (Lot 3, additive read/manage API; no replace/restore flow yet) ---

_REVISION_KEEP_FOREVER_MAX_PER_OWNER = 200


def _revision_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "object_id": row["object_id"],
        "revision_number": int(row["revision_number"]),
        "size_bytes": int(row["size_bytes"]),
        "checksum_sha256": row.get("checksum_sha256") or "",
        "checksum_algorithm": "sha256",
        "content_type": row.get("content_type") or "application/octet-stream",
        "created_at": row["created_at"],
        "created_by_id": row.get("created_by_id"),
        "created_by_kind": row.get("created_by_kind"),
        "keep_forever": bool(row.get("keep_forever")),
        "purged_at": row.get("purged_at"),
    }


def _load_scoped_object(oid: str, principal: dict) -> dict:
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    return _as_dict(row)


def _load_scoped_revision(oid: str, rid: str, principal: dict) -> tuple[dict, dict]:
    obj = _load_scoped_object(oid, principal)
    rid = _canonical_id(rid, "revision id")
    rev = repo.get_revision(obj["id"], rid)
    if rev is None:
        raise HTTPException(status_code=404, detail="revision not found")
    rev = _as_dict(rev)
    if rev.get("purged_at") is not None:
        raise HTTPException(status_code=404, detail="revision not found")
    return obj, rev


@router.get("/api/v1/objects/{oid}/revisions")
def list_object_revisions(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    """List archived revisions for an object, newest generation first.

    Revisions are exposed without storage keys. This endpoint is additive and
    does not require any replace/archive flow to have run.
    """
    obj = _load_scoped_object(oid, principal)
    rows = repo.list_revisions(obj["id"])
    items = [_revision_public(_as_dict(r)) for r in rows if _as_dict(r).get("purged_at") is None]
    return {"object_id": obj["id"], "items": items}


@router.get("/api/v1/objects/{oid}/revisions/{rid}")
def get_object_revision(oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    obj, rev = _load_scoped_revision(oid, rid, principal)
    return _revision_public(rev)


@router.get("/api/v1/objects/{oid}/revisions/{rid}/download-intent")
def download_revision_intent(
    oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_READ)),
):
    """Return a short-lived presigned GET for a specific revision's bytes.

    Served as an attachment to avoid rendering user-controlled content inline on
    the storage origin. Storage keys are never exposed.
    """
    obj, rev = _load_scoped_revision(oid, rid, principal)
    # Revisions are historical bytes: they are downloadable even if the current
    # head is no longer available, provided they have not been purged.
    name = obj.get("display_name") or "download"
    from .main import s3
    url = presigned_get(
        s3, rev["bucket"], rev["storage_key"], settings.intent_ttl,
        content_disposition=shares.content_disposition_header(
            "attachment", f"{name}.rev{int(rev['revision_number'])}"
        ),
    )
    audit_event("revision.download_intent", principal["id"], "success", {
        "object_id": obj["id"], "revision_id": rev["id"],
    })
    return {
        "object_id": obj["id"],
        "revision_id": rev["id"],
        "revision_number": int(rev["revision_number"]),
        "download_url": url,
        "method": "GET",
        "expires_in": settings.intent_ttl,
        "expires_at": int(time.time()) + settings.intent_ttl,
        "content_type": rev.get("content_type") or "application/octet-stream",
        "size_bytes": int(rev["size_bytes"]),
        "checksum_sha256": rev.get("checksum_sha256") or "",
        "checksum_algorithm": "sha256",
    }


@router.delete("/api/v1/objects/{oid}/revisions/{rid}")
def delete_object_revision(
    oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Delete a revision record and its stored bytes.

    Revisions marked keep-forever must be unpinned first. Best-effort storage
    deletion: if the bytes are already gone, the catalogue record is still
    removed so the state is consistent.
    """
    obj, rev = _load_scoped_revision(oid, rid, principal)
    if rev.get("keep_forever"):
        raise HTTPException(
            status_code=409,
            detail="revision is marked keep-forever; unpin it before deletion",
        )
    try:
        from .main import s3ops
        s3ops.delete_object(Bucket=rev["bucket"], Key=rev["storage_key"])
    except Exception:
        # Best-effort: a missing/failed backend delete must not strand the
        # catalogue row. Orphan reconciliation can clean up leftovers.
        pass
    deleted = repo.delete_revision(rev["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="revision not found")
    audit_event("revision.delete", principal["id"], "success", {
        "object_id": obj["id"], "revision_id": rev["id"],
    })
    return {"object_id": obj["id"], "revision_id": rev["id"], "deleted": True}


@router.put("/api/v1/objects/{oid}/revisions/{rid}/keep-forever")
def set_revision_keep_forever(
    oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    obj, rev = _load_scoped_revision(oid, rid, principal)
    if not rev.get("keep_forever"):
        owner_id = obj.get("owner_id")
        if owner_id:
            current = repo.count_keep_forever(owner_id)
            if current >= _REVISION_KEEP_FOREVER_MAX_PER_OWNER:
                raise HTTPException(
                    status_code=409,
                    detail="keep-forever limit reached for this owner",
                )
    updated = repo.set_revision_keep_forever(rev["id"], True)
    if not updated:
        raise HTTPException(status_code=404, detail="revision not found")
    audit_event("revision.keep_forever", principal["id"], "success", {
        "object_id": obj["id"], "revision_id": rev["id"], "keep_forever": True,
    })
    return {"object_id": obj["id"], "revision_id": rev["id"], "keep_forever": True}


@router.delete("/api/v1/objects/{oid}/revisions/{rid}/keep-forever")
def unset_revision_keep_forever(
    oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    obj, rev = _load_scoped_revision(oid, rid, principal)
    updated = repo.set_revision_keep_forever(rev["id"], False)
    if not updated:
        raise HTTPException(status_code=404, detail="revision not found")
    audit_event("revision.keep_forever", principal["id"], "success", {
        "object_id": obj["id"], "revision_id": rev["id"], "keep_forever": False,
    })
    return {"object_id": obj["id"], "revision_id": rev["id"], "keep_forever": False}


@router.post("/api/v1/objects/{oid}/revisions/{rid}/restore")
def restore_object_revision(
    oid: str, rid: str, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Restore a revision as the new head.

    Pragmatic implementation (Lot 3): archives the current head bytes as a new
    revision (copy-on-write to a revision key) then copies the selected
    revision bytes to a fresh head object key and updates the object. This
    preserves history without moving bytes in place. Best-effort toward the
    crash-recovery invariant described in docs/CONTENT-REVISIONS.md.
    """
    obj, rev = _load_scoped_revision(oid, rid, principal)
    if obj.get("status") != "available":
        raise HTTPException(status_code=409, detail="object not available")
    if int(rev.get("size_bytes", -1)) < 0:
        raise HTTPException(status_code=409, detail="revision bytes unavailable")

    now = int(time.time())
    space_id = obj["space_id"]
    # 1) Archive current head as a new revision (copy bytes to a revision key).
    existing = repo.list_revisions(obj["id"])
    next_no = (max((int(r.get("revision_number") or 0) for r in existing), default=0) + 1)
    archive_key = f"aura/{space_id}/revisions/{obj['id']}/{ids.new_id()}"
    from .main import s3ops
    copy_object(s3ops, obj["bucket"], obj["object_key"], archive_key, obj.get("content_type"))
    archive_rid = repo.create_revision(
        object_id=obj["id"], revision_number=next_no, bucket=obj["bucket"],
        storage_key=archive_key, size_bytes=int(obj.get("size_bytes") or 0),
        checksum_sha256=obj.get("checksum_sha256") or "",
        content_type=obj.get("content_type") or "application/octet-stream",
        created_by_id=principal["id"], created_by_kind=principal.get("kind"),
        keep_forever=False,
    )
    # 2) Promote restored revision bytes to a fresh head key.
    new_head_key = f"aura/{space_id}/{principal['id']}/{ids.new_id()}"
    copy_object(s3ops, obj["bucket"], rev["storage_key"], new_head_key, rev.get("content_type"))
    repo.conn.execute if False else None  # keep linters calm in generated contexts
    # Update object head fields (SQLite/PG repos share a .conn for sqlite; PG path
    # handled via repo._run fallback below).
    try:
        if hasattr(repo, "_run"):
            repo._run(
                "UPDATE objects SET bucket = %s, object_key = %s, size_bytes = %s, "
                "checksum_sha256 = %s, content_type = %s, version = COALESCE(version,0)+1, "
                "revision_count = %s, current_revision_id = %s, replaced_at = %s, "
                "status = 'available', updated_at = %s WHERE id = %s",
                (rev["bucket"], new_head_key, int(rev["size_bytes"]),
                 rev.get("checksum_sha256") or "",
                 rev.get("content_type") or "application/octet-stream",
                 next_no, archive_rid, now, now, obj["id"]),
            )
        else:
            repo.conn.execute(
                "UPDATE objects SET bucket = ?, object_key = ?, size_bytes = ?, "
                "checksum_sha256 = ?, content_type = ?, version = COALESCE(version,0)+1, "
                "revision_count = ?, current_revision_id = ?, replaced_at = ?, "
                "status = 'available', updated_at = ? WHERE id = ?",
                (rev["bucket"], new_head_key, int(rev["size_bytes"]),
                 rev.get("checksum_sha256") or "",
                 rev.get("content_type") or "application/octet-stream",
                 next_no, archive_rid, now, now, obj["id"]),
            )
            repo.conn.commit()
    except Exception:
        # Do not lose the archived revision: surface a conflict so operators can
        # inspect; the object may need manual reconciliation.
        raise HTTPException(status_code=500, detail="failed to update object head after restore")

    audit_event("revision.restore", principal["id"], "success", {
        "object_id": obj["id"], "revision_id": rev["id"],
        "archived_revision_id": archive_rid, "new_revision_number": next_no,
    })
    return {
        "object_id": obj["id"],
        "restored_revision_id": rev["id"],
        "archived_revision_id": archive_rid,
        "revision_number": int(rev["revision_number"]),
        "head_revision_number": next_no,
        "status": "available",
    }
