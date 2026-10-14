"""AURA Management API (#18). Catalogue metadata here; bytes via presigned S3 URLs."""
import hashlib
import time
import uuid

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import settings
from .lifecycle import purge_object, reconcile_pending
from .s3 import make_client, presigned_get, presigned_put

if settings.db_backend == "postgres":
    if not settings.db_dsn:
        raise RuntimeError("AURA_API_DSN is required with AURA_API_BACKEND=postgres")
    from .db_pg import Repository

    repo = Repository(settings.db_dsn)
else:
    from .db import Repository

    repo = Repository(settings.db_path)

app = FastAPI(title="AURA Management API", version="0.1.0")

s3 = make_client(
    settings.s3_endpoint, settings.s3_access_key, settings.s3_secret_key,
    settings.s3_region,
)

# Users and sessions are owned by Better Auth (auth/ service + session table).
# This API only maps a live Better Auth session to an owner id.


class UploadIntentIn(BaseModel):
    bucket: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=127)
    folder_id: str | None = None


def current_user(
    aura_session_token: str | None = Cookie(default=None, alias="aura.session_token"),
) -> dict:
    """Authenticate via the Better Auth session cookie (HttpOnly).

    The cookie holds <token>.<signature>; the token part is looked up in the
    better-auth `session` table with freshness check. No S3 material involved.
    """
    from .ba_session import extract_token, lookup_session

    user = lookup_session(repo, extract_token(aura_session_token))
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_origin(
    user: dict = Depends(current_user),
    origin: str | None = Header(default=None),
) -> dict:
    """CSRF guard for mutations: allow-listed Origin required (fail closed)."""
    from .ba_session import TRUSTED_ORIGINS

    if not origin or origin not in TRUSTED_ORIGINS:
        raise HTTPException(status_code=403, detail="untrusted origin")
    return user


@app.get("/health/live")
def live():
    return {"status": "live"}


@app.get("/health/ready")
def ready():
    try:
        s3.list_buckets()
        return {"status": "ready"}
    except Exception as exc:  # never leak backend details
        return JSONResponse(status_code=503, content={"status": "not ready"})


@app.post("/api/v1/objects/upload-intents")
def upload_intent(body: UploadIntentIn, user: dict = Depends(require_origin)):
    key = f"aura/{user['id']}/{uuid.uuid4()}"
    oid = repo.create_pending_object(
        body.bucket, key, body.display_name, body.content_type, user["id"],
        body.folder_id,
    )
    url = presigned_put(s3, body.bucket, key, body.content_type, settings.intent_ttl)
    return {"id": oid, "upload_url": url, "expires_in": settings.intent_ttl}


@app.post("/api/v1/objects/{oid}/commit")
def commit_object(oid: str, user: dict = Depends(require_origin)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="object already committed")
    try:
        head = s3.head_object(Bucket=row["bucket"], Key=row["object_key"])
        body = s3.get_object(Bucket=row["bucket"], Key=row["object_key"])["Body"].read()
    except Exception:
        raise HTTPException(status_code=422, detail="upload not found at storage")
    digest = hashlib.sha256(body).hexdigest()
    size = head.get("ContentLength", len(body))
    repo.mark_available(oid, size, digest)
    return {"id": oid, "status": "available", "size_bytes": size, "checksum_sha256": digest}


@app.get("/api/v1/objects")
def list_objects(
    user: dict = Depends(current_user), limit: int = 50, offset: int = 0
):
    limit = max(1, min(limit, 100))
    rows = repo.list_objects(user["id"], limit, offset)
    return {
        "items": [
            {
                "id": r["id"], "display_name": r["display_name"],
                "content_type": r["content_type"], "size_bytes": r["size_bytes"],
                "checksum_sha256": r["checksum_sha256"], "status": r["status"],
            }
            for r in rows
        ]
    }


@app.get("/api/v1/objects/{oid}")
def get_object(oid: str, user: dict = Depends(current_user)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    return {
        "id": row["id"], "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"],
        "checksum_sha256": row["checksum_sha256"], "status": row["status"],
    }


@app.delete("/api/v1/objects/{oid}")
def soft_delete_object(oid: str, user: dict = Depends(require_origin)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    status = row["status"] if isinstance(row, dict) else row["status"]
    if status not in ("available", "pending"):
        raise HTTPException(status_code=409, detail="object not deletable")
    repo.set_status(oid, "deleted")
    return {"id": oid, "status": "deleted"}


@app.post("/api/v1/objects/{oid}/purge")
def purge(oid: str, user: dict = Depends(require_origin)):
    if not purge_object(repo, s3, oid, user["id"]):
        raise HTTPException(status_code=404, detail="object not found")
    return {"id": oid, "status": "purged"}


@app.post("/api/v1/admin/reconcile")
def reconcile(user: dict = Depends(require_origin)):
    return reconcile_pending(repo, s3)


@app.post("/api/v1/objects/{oid}/download-intent")
def download_intent(oid: str, user: dict = Depends(require_origin)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    url = presigned_get(s3, row["bucket"], row["object_key"], settings.intent_ttl)
    return {"download_url": url, "expires_in": settings.intent_ttl}
