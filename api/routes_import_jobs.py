"""Import job routes extracted from api.main (#348)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import ids
from .audit import audit_event
from .authz import OBJECTS_READ, OBJECTS_WRITE, authorize
from .store import repo


def _canonical_id(value: str, field: str) -> str:
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


class ImportJobIn(BaseModel):
    """Create a bulk import job. The API records the job; a worker (future)
    will process each item. The response omits secrets and storage paths."""
    model_config = ConfigDict(extra="forbid")
    total_items: int = Field(ge=1, le=10_000)


class ImportJobOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    space_id: str
    application_id: str
    created_by: str
    status: str
    total_items: int
    processed_items: int
    failed_items: int
    summary: str | None = None
    created_at: int
    updated_at: int


router = APIRouter()


@router.post("/api/v1/import-jobs")
def create_import_job(
    body: ImportJobIn, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Create a bulk import job for the caller's space.

    The job is recorded in ``queued`` state. A background worker (future work)
    will process each item; this endpoint only books the batch.
    """
    space_id = principal["space_id"]
    application_id = principal.get("application_id")
    jid = ids.new_id()
    repo.create_import_job(
        jid, space_id, application_id or "", principal["id"], body.total_items,
    )
    audit_event("import_job.create", principal["id"], "success", {
        "import_job_id": jid, "space_id": space_id, "total_items": body.total_items,
    })
    row = repo.get_import_job(jid, space_id=space_id)
    return ImportJobOut(**row)


@router.get("/api/v1/import-jobs")
def list_import_jobs(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    principal: dict = Depends(authorize(OBJECTS_READ)),
):
    """List import jobs for the caller's space, newest first."""
    space_id = principal["space_id"]
    if status is not None and status not in (
        "queued", "running", "done", "failed", "cancelled",
    ):
        raise HTTPException(status_code=422, detail="unknown import job status")
    rows = repo.list_import_jobs(
        space_id=space_id, status=status, limit=limit,
    )
    return [ImportJobOut(**r) for r in rows]


@router.post("/api/v1/import-jobs/{jid}/cancel")
def cancel_import_job(
    jid: str, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Cancel a queued or running import job. Idempotent."""
    jid = _canonical_id(jid, "import job id")
    space_id = principal["space_id"]
    ok = repo.cancel_import_job(jid, space_id=space_id)
    if not ok:
        raise HTTPException(status_code=404, detail="import job not found or not cancellable")
    audit_event("import_job.cancel", principal["id"], "success", {
        "import_job_id": jid, "space_id": space_id,
    })
    row = repo.get_import_job(jid, space_id=space_id)
    return ImportJobOut(**row)
