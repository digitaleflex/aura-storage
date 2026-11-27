"""Admin routes extracted from api.main (#345)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from . import ids
from .audit import audit_event
from .authz import ADMIN_READ, ADMIN_WRITE, authorize, effective_scopes
from .config import settings
from .lifecycle import purge_object, purge_transfer_history, reconcile_pending, reconcile_reverse, reconcile_terminal, resume_purges
from .store import repo
from .transfer import EXPIRED

# This extracted route module is not registered by api.main, so importing its
# helpers back from main is safe and keeps the extraction faithful to the
# original endpoint bodies.
from .main import (  # noqa: E402
    ALL_SCOPES, AVAILABLE, SERVICE_SCOPES,
    ApplicationIn, ApplicationPatchIn, BucketIn, BucketPatchIn, IdentityIn,
    ObjectTooLarge, PartnerSiteIn, PartnerSitePatchIn, SpaceIn, SpacePatchIn,
    SpaceQuotasIn,
    _BOOT_TIME, _application_public, _bucket_public, _capacity,
    _space_month_usage, _space_public, _space_quota, _split_audio_name,
    _upload_ceiling, _usage_period,
    JSONResponse, app, audit_path, fingerprint, format_token,
    is_valid_bucket_name, new_secret, prune_audit_log, query_audit_log,
    recent_error_events, s3probe, shutil, stream_sha256,
)


def _main():
    import api.main as m
    return m




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

# ---------------------------------------------------------------------------
# Administration (#35, #36, #38): require the admin:* capabilities.
# ---------------------------------------------------------------------------
@router.post("/api/v1/admin/reconcile")
def reconcile(limit: int = 500,
              principal: dict = Depends(authorize(ADMIN_WRITE))):
    # Bounded sweep (#87): at most `limit` stale intents per run so a huge
    # backlog cannot monopolize the API; repeat until expired is 0.
    limit = max(1, min(limit, 5000))
    # Derive the staleness window from the same settings that govern intent
    # death (commit is accepted until intent_ttl + intent_grace_s), plus the
    # same safety margin as the automatic sweep. Without the extra margin a
    # commit starting at the last second could be deleted under itself.
    expire_after_s = (
        settings.intent_ttl + settings.intent_grace_s + settings.reconcile_extra_grace_s
    )
    out = reconcile_pending(
        repo, _main.s3ops, expire_after_s=expire_after_s, limit=limit,
        multipart_expired_before=int(time.time()) - settings.intent_grace_s,
    )
    # Finish purges a crashed process left half-done (two-phase purge).
    out.update(resume_purges(repo, _main.s3ops, limit=limit))
    # Retention window for the append-only transfer journal (#246).
    out.update(purge_transfer_history(
        repo, retention_days=settings.transfer_history_retention_days,
        limit=limit,
    ))
    audit_event("admin.reconcile", principal["id"], "success", out)
    return out


@router.post("/api/v1/admin/reconcile-terminal")
def reconcile_terminal_route(limit: int = 500,
                            principal: dict = Depends(authorize(ADMIN_WRITE))):
    limit = max(1, min(limit, 5000))
    out = reconcile_terminal(repo, _main.s3ops, limit=limit)
    audit_event("admin.reconcile_terminal", principal["id"], "success", out)
    return out


@router.post("/api/v1/admin/reconcile-reverse")
def reconcile_reverse_route(dry_run: bool = True,
                           principal: dict = Depends(authorize(ADMIN_WRITE))):
    out = reconcile_reverse(repo, _main.s3ops, dry_run=dry_run)
    audit_event("admin.reconcile_reverse", principal["id"], "success", out)
    return out


@router.get("/api/v1/admin/integrity")
def integrity_report(limit: int = 100,
                     principal: dict = Depends(authorize(ADMIN_READ))):
    """Periodic scrub results: counts per result and the objects at fault.

    ``mismatch`` means the stored bytes no longer match the SHA-256 verified at
    import; ``missing`` means the storage lost the object. Both call for a
    restore from backup; nothing is changed automatically.
    """
    limit = max(1, min(limit, 500))
    summary = repo.integrity_summary()
    problems = [_as_dict(r) for r in repo.list_integrity_problems(limit=limit)]
    return {
        "interval_days": settings.scrub_interval_days,
        "results": summary,
        "problems": problems,
    }


@router.post("/api/v1/admin/integrity/scrub")
def integrity_scrub_now(principal: dict = Depends(authorize(ADMIN_WRITE))):
    """Run one bounded scrub pass now (same byte budget as the periodic one)."""
    from .scrubber import scrub_run
    out = scrub_run(repo, _main.s3ops, settings, audit=audit_event)
    audit_event("admin.scrub", principal["id"], "success", out)
    return out


@router.post("/api/v1/admin/objects/{oid}/reverify")
def reverify_object(oid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    """Re-hash one published object and leave ``suspect``/``failed`` if it matches.

    A single divergent HEAD used to freeze an object forever: no route could
    restore it. The operator re-reads the bytes from storage (never trusting a
    cached copy), compares the SHA-256 with the catalogue and either publishes
    it again or leaves it ``suspect`` with an explicit 409.
    """
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] not in ("available", "suspect", "failed"):
        raise HTTPException(status_code=409, detail="object is not published")
    max_bytes = settings.max_object_bytes
    if row.get("multipart_part_bytes"):
        max_bytes = max(max_bytes, settings.multipart_max_object_bytes)
    try:
        head = _main.s3ops.head_object(Bucket=row["bucket"], Key=row["object_key"])
        body = _main.s3ops.get_object(Bucket=row["bucket"], Key=row["object_key"])["Body"]
        total, digest = stream_sha256(body, max_bytes, settings.commit_chunk_bytes)
    except ObjectTooLarge:
        raise HTTPException(status_code=413, detail="object exceeds the configured cap")
    except Exception:
        audit_event("admin.reverify", principal["id"], "storage_failure",
                    {"object_id": oid})
        raise HTTPException(status_code=502, detail="storage unavailable")

    expected = (row.get("checksum_sha256") or "").lower()
    size_ok = int(head.get("ContentLength", -1)) == total
    if not size_ok or (expected and digest != expected):
        repo.set_status(oid, "suspect", allowed_from=("available", "suspect", "failed"))
        audit_event("admin.reverify", principal["id"], "mismatch", {
            "object_id": oid, "size_bytes": total,
        })
        return JSONResponse(status_code=409, content={
            "id": oid, "status": "suspect", "reason": "checksum_mismatch",
            "size_bytes": total, "checksum_sha256": digest,
        })
    repo.mark_reverified(oid, total, digest)
    audit_event("admin.reverify", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "available", "size_bytes": total,
            "checksum_sha256": digest}


@router.get("/api/v1/admin/orphans")
def list_orphan_candidates(limit: int = 100,
                           principal: dict = Depends(authorize(ADMIN_READ))):
    """Read-only orphan candidates (#87): `available` rows whose bytes are
    missing at storage. Candidates only — nothing is ever deleted on this
    signal alone; a transient outage also produces candidates, so an operator
    confirms before any destructive action. Bounded scan, oldest first.
    """
    limit = max(1, min(limit, 1000))
    checked = 0
    candidates = []
    for row in repo.list_available(limit=limit):
        row = _as_dict(row)
        checked += 1
        try:
            _main.s3ops.head_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            candidates.append({
                "id": row["id"], "display_name": row["display_name"],
                "space_id": row["space_id"],
                "application_id": row["application_id"],
                "size_bytes": row["size_bytes"],
                "updated_at": row["updated_at"],
            })
    return {"checked": checked, "candidates": candidates,
            "checked_at": int(time.time())}


@router.get("/api/v1/admin/storage-orphans")
def storage_orphans(
    bucket: str | None = Query(default=None, max_length=63),
    start_after: str | None = Query(default=None, max_length=1024),
    max_keys: int = 5000,
    principal: dict = Depends(authorize(ADMIN_READ)),
):
    """Read-only: storage bytes the catalogue does not account for (#87).

    Bounded per call (``max_keys`` per bucket) and resumable with the returned
    ``next_start_after``. Only registered buckets are scanned.
    """
    from .storage_reconcile import scan_bucket, scan_multipart
    max_keys = max(1, min(max_keys, 50_000))
    names = [b["name"] for b in repo.list_all_buckets()]
    if bucket is not None:
        if bucket not in names:
            raise HTTPException(status_code=404, detail="bucket not registered")
        names = [bucket]
    out = []
    for name in names:
        try:
            report = scan_bucket(repo, _main.s3ops, name, grace_s=settings.orphan_grace_s,
                                 max_keys=max_keys, start_after=start_after)
            report["stale_uploads"] = scan_multipart(
                repo, _main.s3ops, name, grace_s=settings.orphan_grace_s,
            )
        except Exception:
            out.append({"bucket": name, "error": "storage unavailable"})
            continue
        out.append(report)
    return {"grace_seconds": settings.orphan_grace_s, "buckets": out,
            "checked_at": int(time.time())}


class OrphanUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=1024)
    upload_id: str = Field(min_length=1, max_length=1024)


class OrphanCleanupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: str = Field(min_length=1, max_length=63)
    keys: list[str] = Field(default_factory=list, max_length=100)
    uploads: list[OrphanUploadIn] = Field(default_factory=list, max_length=100)


@router.post("/api/v1/admin/storage-orphans/cleanup")
def storage_orphans_cleanup(
    body: OrphanCleanupIn, principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Destructive, explicit: remove listed orphan keys / abort listed uploads.

    Each item is re-checked just before acting (still unaccounted for, older
    than the grace period, inside the AURA key prefix); anything else is
    skipped with a reason. At most 100 keys and 100 uploads per call.
    """
    from .storage_reconcile import remove_orphans
    if body.bucket not in {b["name"] for b in repo.list_all_buckets()}:
        raise HTTPException(status_code=404, detail="bucket not registered")
    out = remove_orphans(
        repo, _main.s3ops, body.bucket, body.keys,
        [u.model_dump() for u in body.uploads], grace_s=settings.orphan_grace_s,
    )
    audit_event("admin.storage-orphans.cleanup", principal["id"], "success", {
        "bucket": body.bucket, "removed": len(out["removed"]),
        "aborted_uploads": len(out["aborted_uploads"]), "skipped": len(out["skipped"]),
    })
    return out


@router.get("/api/v1/admin/stats")
def admin_stats(principal: dict = Depends(authorize(ADMIN_READ))):
    return repo.stats()


# ---------------------------------------------------------------------------
# Observability (M07): audit search, usage, supervision. Reads require
# admin:read; retention pruning requires admin:write. Every value returned is
# measured live from the catalogue, the audit file or the OS — see
# docs/OBSERVABILITY.md for what is (and is not) available.
# ---------------------------------------------------------------------------
@router.get("/api/v1/admin/audit")
def search_audit(
    since: int | None = Query(default=None, ge=0),
    until: int | None = Query(default=None, ge=0),
    actor: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=100),
    result: str | None = Query(default=None, max_length=50),
    space_id: str | None = None,
    application_id: str | None = None,
    request_id: str | None = Query(default=None, max_length=128),
    limit: int = 100,
    offset: int = 0,
    principal: dict = Depends(authorize(ADMIN_READ)),
):
    # Search the append-only audit log newest-first. `total` counts matches
    # inside the scanned tail window; `truncated` warns that older history
    # exists beyond it. A missing log file is an empty history, never an
    # error. Pagination: limit is clamped to 1..500, offset counts matches.
    if space_id is not None:
        space_id = _canonical_id(space_id, "space id")
    if application_id is not None:
        application_id = _canonical_id(application_id, "application id")
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=422, detail="since must not exceed until"
        )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    out = query_audit_log(
        since=since, until=until, actor=actor or None, action=action or None,
        result=result or None, space_id=space_id,
        application_id=application_id, request_id=request_id or None,
        limit=limit, offset=offset,
        max_scan_lines=settings.audit_max_scan_lines,
    )
    return {
        **out, "retention_days": settings.audit_retention_days,
        "queried_at": int(time.time()),
    }


@router.post("/api/v1/admin/audit/prune")
def prune_audit(principal: dict = Depends(authorize(ADMIN_WRITE))):
    # Enforce the retention window: drop lines older than
    # AURA_AUDIT_RETENTION_DAYS. Lines without a valid timestamp are kept,
    # so audit data is never deleted silently.
    try:
        out = prune_audit_log(retention_days=settings.audit_retention_days)
    except OSError:
        raise HTTPException(status_code=503, detail="audit log unavailable")
    audit_event("admin.audit.prune", principal["id"], "success", out)
    return out


@router.get("/api/v1/admin/portal-stats")
def admin_portal_stats(principal: dict = Depends(authorize(ADMIN_READ))):
    """What the public portal is used for: per-book listeners, completions, favourites.

    Counts only, computed from the listening-progress and favourites tables; no
    visitor, e-mail or listening history is returned or stored for this purpose.
    A book is "completed" once a visitor reached 90 % of its duration.
    """
    period = _usage_period()
    raw = repo.portal_stats(period, AVAILABLE)
    books = []
    for row in raw["books"]:
        author, title = _split_audio_name(row["display_name"])
        listeners, completed = int(row["listeners"]), int(row["completed"])
        books.append({
            "id": row["id"], "title": title or row["display_name"], "author": author or "",
            "listeners": listeners, "completed": completed,
            "completion_rate": round(completed / listeners, 3) if listeners else 0.0,
            "favorites": int(row["favorites"]), "views_month": int(row["views_month"]),
        })
    books.sort(key=lambda b: (-b["listeners"], -b["favorites"], -b["views_month"], b["title"].lower()))
    return {
        "measured_at": int(time.time()), "period": period,
        "totals": {
            "accounts": int(raw["accounts"]), "published_books": len(books),
            "listeners": sum(b["listeners"] for b in books),
            "completed": sum(b["completed"] for b in books),
            "favorites": sum(b["favorites"] for b in books),
            "views_month": sum(b["views_month"] for b in books),
        },
        "books": books[:50],
    }


@router.get("/api/v1/admin/usage")
def admin_usage(
    space_id: str | None = None,
    principal: dict = Depends(authorize(ADMIN_READ)),
):
    # Real consumption from the catalogue (M07): verified bytes are
    # `available` objects only; pending intents carry no committed bytes.
    # `measured_at` is the live query time (freshness), `limits` the
    # configured technical ceilings. No bandwidth or capacity figures exist
    # offline — they are documented as unavailable, never invented.
    if space_id is not None:
        space_id = _canonical_id(space_id, "space id")
        space = repo.get_space(space_id)
        if space is None:
            raise HTTPException(status_code=404, detail="space not found")
        spaces = [space]
    else:
        spaces = repo.list_spaces()
    applications = {a["id"]: a for a in repo.list_applications()}
    items = []
    totals_by_status: dict[str, int] = {}
    total_bytes = 0
    total_available = 0
    total_pending = 0
    period = _usage_period()
    total_egress = 0
    for space in spaces:
        space = _as_dict(space)
        usage = repo.space_usage(space["id"])
        for status, count in usage["objects_by_status"].items():
            totals_by_status[status] = totals_by_status.get(status, 0) + count
        total_bytes += usage["stored_bytes"]
        total_available += usage["available_count"]
        total_pending += usage["pending_count"]
        month = _space_month_usage(space["id"], period)
        total_egress += month["egress_bytes"]
        application = applications.get(space["application_id"])
        items.append({
            "space_id": space["id"], "space_name": space["name"],
            "environment": space["environment"],
            "application_id": space["application_id"],
            "application_name": application["name"] if application else None,
            **usage,
            # Monthly counters are estimates from issued intents/redemptions
            # (the API never proxies bytes). Quotas are null when unset.
            "month": month,
            "quota": _space_quota(space["id"]),
        })
    return {
        "measured_at": int(time.time()),
        "period": period,
        "limits": {
            # Multipart lifts the declarable ceiling to its own cap; reporting
            # the single-PUT limit here would make the client guard reject
            # files the API would accept.
            "max_object_bytes": _upload_ceiling(),
            "max_pending_intents": settings.max_pending_intents,
            "intent_ttl": settings.intent_ttl,
            "allow_empty_objects": settings.allow_empty_objects,
        },
        # Capacity guard (null when AURA_STORAGE_CAPACITY_BYTES is not set).
        "capacity": _capacity(),
        "totals": {
            "objects_by_status": totals_by_status,
            "available_count": total_available,
            "pending_count": total_pending,
            "stored_bytes": total_bytes,
            "egress_bytes_month": total_egress,
        },
        "spaces": items,
    }


@router.get("/api/v1/admin/health")
def admin_health(principal: dict = Depends(authorize(ADMIN_READ))):
    """Supervision snapshot (M07): process, database, storage, local disk.

    Always 200 with per-component statuses (`ok`/`down`); the top-level
    status is `degraded` when any dependency fails. The storage check proves
    S3 reachability, not a full upload/download round-trip — that proof is
    the live S3 smoke test, unavailable offline.
    """
    checked_at = int(time.time())
    components: dict[str, dict] = {
        "api": {
            "status": "ok", "uptime_s": checked_at - _BOOT_TIME,
            "version": app.version,
        },
    }
    start = time.monotonic()
    try:
        repo.ping()
        components["database"] = {
            "status": "ok",
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    except Exception:
        components["database"] = {"status": "down", "error": "unreachable"}
    start = time.monotonic()
    try:
        s3probe.list_buckets()
        components["storage"] = {
            "status": "ok",
            "latency_ms": int((time.monotonic() - start) * 1000),
            "note": "S3 reachable; not a full upload/download round-trip",
        }
    except Exception:
        components["storage"] = {"status": "down", "error": "unreachable"}
    try:
        disk = shutil.disk_usage(audit_path())
        components["disk"] = {
            "status": "ok", "total_bytes": disk.total,
            "used_bytes": disk.used, "free_bytes": disk.free,
            "note": "local process volume; not the object-store capacity",
        }
    except OSError:
        components["disk"] = {"status": "down", "error": "unreadable"}
    # The automatic reconciliation sweep (#144): its last counters show that it
    # runs without an operator. Never fatal for the service: a failed sweep is
    # reported, the next one retries.
    from .reconciler import last_sweep
    sweep = last_sweep()
    components["reconcile"] = {
        "status": "ok",
        "enabled": settings.reconcile_enabled,
        "interval_s": settings.reconcile_interval_s,
        "last_sweep": sweep,
        "note": None if sweep else "no sweep yet",
    }
    errors, scanned = recent_error_events(
        window_s=settings.audit_error_window_s, limit=5,
        max_scan_lines=settings.audit_error_scan_lines,
    )
    degraded = any(c.get("status") != "ok" for c in components.values())
    return {
        "status": "degraded" if degraded else "ok",
        "checked_at": checked_at,
        "components": components,
        "recent_errors": {
            "window_s": settings.audit_error_window_s,
            "events": errors, "scanned": scanned,
        },
        "note": (
            "Degraded storage means uploads/downloads will fail; full "
            "data-plane proof requires the live S3 smoke test."
        ),
    }


@router.post("/api/v1/admin/applications")
def create_application(body: ApplicationIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    if repo.get_application_by_name(body.name) is not None:
        raise HTTPException(status_code=409, detail="application already exists")
    aid = repo.create_application(body.name)
    audit_event("admin.application.create", principal["id"], "success", {"application_id": aid})
    return _application_public(repo.get_application(aid))


@router.get("/api/v1/admin/applications")
def list_applications(principal: dict = Depends(authorize(ADMIN_READ))):
    return {"items": [_application_public(a) for a in repo.list_applications()]}


@router.get("/api/v1/admin/applications/{aid}")
def get_application(aid: str, principal: dict = Depends(authorize(ADMIN_READ))):
    aid = _canonical_id(aid, "application id")
    row = repo.get_application(aid)
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    # The stable identifier is returned verbatim; it is never derived from name.
    out = _application_public(row)
    out["space_count"] = repo.count_spaces_for_application(aid)
    return out


@router.patch("/api/v1/admin/applications/{aid}")
def update_application(
    aid: str, body: ApplicationPatchIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    aid = _canonical_id(aid, "application id")
    row = repo.get_application(aid)
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    if "name" in fields and body.name is None:
        raise HTTPException(status_code=422, detail="name cannot be null")
    if "status" in fields and body.status is None:
        raise HTTPException(status_code=422, detail="status cannot be null")
    if "name" in fields and body.name != row["name"]:
        if repo.application_name_exists(body.name, exclude_id=aid):
            raise HTTPException(status_code=409, detail="application name already exists")
    repo.update_application(
        aid,
        name=body.name if "name" in fields else None,
        status=body.status if "status" in fields else None,
    )
    audit_event("admin.application.update", principal["id"], "success",
                {"application_id": aid})
    out = _application_public(repo.get_application(aid))
    out["space_count"] = repo.count_spaces_for_application(aid)
    return out


def _space_detail(sid: str) -> dict:
    """Space detail with its application, buckets and attachment counts."""
    row = repo.get_space(sid)
    out = _space_public(row)
    application = repo.get_application(row["application_id"])
    out["application_name"] = application["name"] if application else None
    out["buckets"] = [_bucket_public(b) for b in repo.list_buckets(sid)]
    out["counts"] = repo.space_counts(sid)
    return out


@router.post("/api/v1/admin/spaces")
def create_space(body: SpaceIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    application = repo.get_application(body.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")
    if application["status"] != "active":
        # A space may only be attached to an allowed (active) application.
        raise HTTPException(status_code=409, detail="application is not active")
    if repo.space_exists(body.application_id, body.name, body.environment):
        # The unique (application_id, name, environment) is enforced up front so a
        # duplicate is a 409, never a database integrity error.
        raise HTTPException(status_code=409, detail="space already exists")
    bucket = body.default_bucket or f"aura-{body.name}-{body.environment}"
    if not is_valid_bucket_name(bucket):
        # Refuse up front rather than register a bucket name S3 will reject (#41).
        raise HTTPException(status_code=422, detail="invalid bucket name")
    if repo.get_bucket_by_name(bucket) is not None:
        raise HTTPException(status_code=409, detail="bucket name already in use")
    sid = repo.create_space(body.application_id, body.name, body.environment)
    repo.create_bucket(sid, bucket, is_default=True)
    audit_event("admin.space.create", principal["id"], "success", {"space_id": sid})
    return {**_space_detail(sid), "bucket": bucket}


@router.get("/api/v1/admin/spaces")
def list_spaces(principal: dict = Depends(authorize(ADMIN_READ))):
    return {"items": [_space_public(s) for s in repo.list_spaces()]}


@router.get("/api/v1/admin/spaces/{sid}")
def get_space(sid: str, principal: dict = Depends(authorize(ADMIN_READ))):
    sid = _canonical_id(sid, "space id")
    if repo.get_space(sid) is None:
        raise HTTPException(status_code=404, detail="space not found")
    return _space_detail(sid)


@router.patch("/api/v1/admin/spaces/{sid}")
def update_space(
    sid: str, body: SpacePatchIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    sid = _canonical_id(sid, "space id")
    row = repo.get_space(sid)
    if row is None:
        raise HTTPException(status_code=404, detail="space not found")
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    if "name" in fields and body.name is None:
        raise HTTPException(status_code=422, detail="name cannot be null")
    if "environment" in fields and body.environment is None:
        raise HTTPException(status_code=422, detail="environment cannot be null")
    if "status" in fields and body.status is None:
        raise HTTPException(status_code=422, detail="status cannot be null")
    new_name = body.name if "name" in fields else row["name"]
    new_environment = (
        body.environment if "environment" in fields else row["environment"]
    )
    # `application_id` is immutable (it is not an editable field), so uniqueness
    # is only ever re-checked inside the same application.
    if (new_name, new_environment) != (row["name"], row["environment"]):
        if repo.space_exists(
            row["application_id"], new_name, new_environment, exclude_id=sid
        ):
            raise HTTPException(status_code=409, detail="space already exists")
    repo.update_space(
        sid,
        name=new_name if "name" in fields else None,
        environment=new_environment if "environment" in fields else None,
        status=body.status if "status" in fields else None,
    )
    audit_event("admin.space.update", principal["id"], "success", {"space_id": sid})
    return _space_detail(sid)


@router.put("/api/v1/admin/spaces/{sid}/quotas")
def set_space_quotas(
    sid: str, body: SpaceQuotasIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Replace the monthly quotas of a space. Null clears a ceiling."""
    sid = _canonical_id(sid, "space id")
    if repo.get_space(sid) is None:
        raise HTTPException(status_code=404, detail="space not found")
    repo.set_space_quotas(
        sid, body.storage_bytes, body.egress_bytes_monthly, principal["id"]
    )
    audit_event("admin.space.quotas", principal["id"], "success", {
        "space_id": sid,
        "storage_bytes": body.storage_bytes,
        "egress_bytes_monthly": body.egress_bytes_monthly,
    })
    return {"space_id": sid, **_space_quota(sid)}


@router.post("/api/v1/admin/spaces/{sid}/buckets")
def create_space_bucket(
    sid: str, body: BucketIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    # Register an extra bucket for a space. The bucket name is validated against
    # the S3 rules and must be globally unique; a bucket is never made the default
    # here (that is an explicit, separate action) and never deleted (#M04).
    sid = _canonical_id(sid, "space id")
    if repo.get_space(sid) is None:
        raise HTTPException(status_code=404, detail="space not found")
    if not is_valid_bucket_name(body.name):
        raise HTTPException(status_code=422, detail="invalid bucket name")
    if repo.get_bucket_by_name(body.name) is not None:
        raise HTTPException(status_code=409, detail="bucket name already in use")
    bid = repo.create_bucket(sid, body.name, is_default=False)
    audit_event("admin.bucket.create", principal["id"], "success",
                {"bucket_id": bid, "space_id": sid})
    return _bucket_public(repo.get_bucket(bid))


@router.get("/api/v1/admin/buckets")
def list_buckets(principal: dict = Depends(authorize(ADMIN_READ))):
    # Every registered bucket with its space/application attachment. The payload
    # has no S3 credential field: only the bucket name and its owner are exposed.
    spaces = {s["id"]: s for s in repo.list_spaces()}
    applications = {a["id"]: a for a in repo.list_applications()}
    items = []
    for bucket in repo.list_all_buckets():
        space = spaces.get(bucket["space_id"])
        application = applications.get(space["application_id"]) if space else None
        items.append({
            **_bucket_public(bucket),
            "space_name": space["name"] if space else None,
            "environment": space["environment"] if space else None,
            "application_id": space["application_id"] if space else None,
            "application_name": application["name"] if application else None,
        })
    return {"items": items}


@router.patch("/api/v1/admin/buckets/{bid}")
def update_bucket(
    bid: str, body: BucketPatchIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    # Toggle the default flag. Setting a bucket default clears the flag on the
    # other buckets of the same space, so exactly one default is possible; the
    # existing objects keep their own bucket locator, so the change is reversible.
    bid = _canonical_id(bid, "bucket id")
    bucket = repo.get_bucket(bid)
    if bucket is None:
        raise HTTPException(status_code=404, detail="bucket not found")
    repo.set_default_bucket(bucket["space_id"], bid, is_default=body.is_default)
    audit_event("admin.bucket.default", principal["id"], "success", {
        "bucket_id": bid, "space_id": bucket["space_id"],
        "is_default": body.is_default,
    })
    return _bucket_public(repo.get_bucket(bid))


def _create_service_identity(
    principal: dict, space_id: str, name: str, scopes_in: list[str],
    ttl_seconds: int | None,
) -> dict:
    """Validate and persist a data-plane identity; returns its one-time token.

    Shared by the identity route and the partner-site route so both enforce the
    same rules (active space, known scopes, service scopes only).
    """
    space = repo.get_space(space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    if space.get("status") not in (None, "active"):
        # No new identity may be minted for a disabled space (#M04).
        raise HTTPException(status_code=409, detail="space is not active")
    scopes = set(scopes_in)
    unknown = scopes - ALL_SCOPES
    if unknown:
        raise HTTPException(status_code=422, detail="unknown scopes requested")
    forbidden = scopes - SERVICE_SCOPES
    if forbidden:
        # Machine identities are data-plane only: administration stays with a
        # human operator/admin session (see docs/AUTHORIZATION-MATRIX.md).
        raise HTTPException(
            status_code=422, detail="scopes not allowed for service identities"
        )
    if not scopes:
        raise HTTPException(status_code=422, detail="at least one scope is required")
    identity_id = repo.new_id()
    secret = new_secret()
    expires_at = int(time.time()) + ttl_seconds if ttl_seconds else None
    repo.create_identity(
        identity_id, space["application_id"], space_id, name,
        fingerprint(secret), ",".join(sorted(scopes)), expires_at,
    )
    audit_event("admin.identity.create", principal["id"], "success",
                {"identity_id": identity_id, "space_id": space_id})
    return {
        "id": identity_id, "name": name, "space_id": space_id,
        "application_id": space["application_id"], "scopes": sorted(scopes),
        "expires_at": expires_at,
        # The token is returned exactly once; it is never logged or stored in clear.
        "token": format_token(identity_id, secret),
    }


@router.post("/api/v1/admin/identities")
def create_identity(body: IdentityIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    return _create_service_identity(
        principal, body.space_id, body.name, body.scopes, body.ttl_seconds
    )


@router.get("/api/v1/admin/identities")
def list_identities(space_id: str | None = None,
                    principal: dict = Depends(authorize(ADMIN_READ))):
    if space_id is not None:
        space_id = _canonical_id(space_id, "space id")
    items = []
    for i in repo.list_identities(space_id):
        items.append({
            "id": i["id"], "name": i["name"], "space_id": i["space_id"],
            "application_id": i["application_id"],
            "scopes": sorted(s for s in (i.get("scopes") or "").split(",") if s),
            "created_at": i["created_at"], "expires_at": i.get("expires_at"),
            "last_used_at": i.get("last_used_at"), "revoked_at": i.get("revoked_at"),
            "rotated_at": i.get("rotated_at"),
        })
    return {"items": items}


def _partner_public(row: dict) -> dict:
    """Site metadata plus the live state of its identity (never the secret)."""
    return {
        "id": row["id"], "name": row["name"], "site_url": row["site_url"],
        "space_id": row["space_id"], "identity_id": row["identity_id"],
        "default_ttl_seconds": row.get("default_ttl_seconds"),
        "notes": row.get("notes") or "",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "identity": {
            "name": row.get("identity_name"),
            "scopes": sorted(
                s for s in (row.get("identity_scopes") or "").split(",") if s
            ),
            "expires_at": row.get("identity_expires_at"),
            "last_used_at": row.get("identity_last_used_at"),
            "revoked_at": row.get("identity_revoked_at"),
            "rotated_at": row.get("identity_rotated_at"),
        },
    }


@router.get("/api/v1/admin/partner-sites")
def list_partner_sites(principal: dict = Depends(authorize(ADMIN_READ))):
    """Partner integrations with the state of their service identity."""
    return {"items": [_partner_public(r) for r in repo.list_partner_sites()]}


@router.post("/api/v1/admin/partner-sites")
def create_partner_site(
    body: PartnerSiteIn, principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Create the site metadata and its dedicated identity in one step.

    The identity token is returned exactly once, like the identity route. A
    failed metadata insert revokes the fresh identity so no orphan credential
    keeps working without a visible owner.
    """
    for existing in repo.list_partner_sites():
        if (
            existing["space_id"] == body.space_id
            and existing["name"].casefold() == body.name.casefold()
        ):
            raise HTTPException(
                status_code=409,
                detail="a partner site with this name already exists in the space",
            )
    identity = _create_service_identity(
        principal, body.space_id, body.name, body.scopes, body.ttl_seconds
    )
    pid = repo.new_id()
    try:
        repo.create_partner_site(
            pid, body.space_id, identity["id"], body.name, body.site_url,
            body.default_ttl_seconds, body.notes, principal["id"],
        )
    except Exception:
        repo.revoke_identity(identity["id"])
        raise
    audit_event("admin.partner.create", principal["id"], "success", {
        "partner_id": pid, "space_id": body.space_id,
        "identity_id": identity["id"],
    })
    return {**_partner_public(repo.get_partner_site(pid)), "token": identity["token"]}


@router.patch("/api/v1/admin/partner-sites/{pid}")
def update_partner_site(
    pid: str, body: PartnerSitePatchIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Edit metadata only. Moving the trust to another space means a new key."""
    pid = _canonical_id(pid, "partner id")
    row = repo.get_partner_site(pid)
    if row is None:
        raise HTTPException(status_code=404, detail="partner site not found")
    fields = body.model_fields_set
    name = body.name if "name" in fields and body.name is not None else row["name"]
    site_url = (
        body.site_url if "site_url" in fields and body.site_url is not None
        else row["site_url"]
    )
    ttl = (
        body.default_ttl_seconds if "default_ttl_seconds" in fields
        else row.get("default_ttl_seconds")
    )
    notes = body.notes if "notes" in fields and body.notes is not None else row.get("notes") or ""
    if name.casefold() != row["name"].casefold():
        for existing in repo.list_partner_sites():
            if (
                existing["id"] != pid
                and existing["space_id"] == row["space_id"]
                and existing["name"].casefold() == name.casefold()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="a partner site with this name already exists in the space",
                )
    repo.update_partner_site(pid, name, site_url, ttl, notes)
    audit_event("admin.partner.update", principal["id"], "success", {
        "partner_id": pid, "space_id": row["space_id"],
    })
    return _partner_public(repo.get_partner_site(pid))


@router.delete("/api/v1/admin/partner-sites/{pid}")
def delete_partner_site(
    pid: str, principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Remove an integration and revoke its key in one step.

    Revocation comes first so a failure to delete the metadata can never leave a
    working credential without a visible owner. The identity row is kept
    (revoked) so the audit trail still resolves; only the site metadata is
    deleted.
    """
    pid = _canonical_id(pid, "partner id")
    row = repo.get_partner_site(pid)
    if row is None:
        raise HTTPException(status_code=404, detail="partner site not found")
    repo.revoke_identity(row["identity_id"])
    repo.delete_partner_site(pid)
    audit_event("admin.partner.delete", principal["id"], "success", {
        "partner_id": pid, "space_id": row["space_id"],
        "identity_id": row["identity_id"],
    })
    return {"id": pid, "deleted": True, "identity_revoked": True}


@router.post("/api/v1/admin/identities/{iid}/rotate")
def rotate_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    iid = _canonical_id(iid, "identity id")
    row = repo.get_identity(iid)
    if row is None or row.get("revoked_at"):
        raise HTTPException(status_code=404, detail="identity not found")
    secret = new_secret()
    repo.update_identity_secret(iid, fingerprint(secret))
    audit_event("admin.identity.rotate", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "token": format_token(iid, secret)}


@router.post("/api/v1/admin/identities/{iid}/revoke")
def revoke_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    iid = _canonical_id(iid, "identity id")
    row = repo.get_identity(iid)
    if row is None:
        raise HTTPException(status_code=404, detail="identity not found")
    repo.revoke_identity(iid)
    audit_event("admin.identity.revoke", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "revoked": True}


