"""AURA Management API (#18). Catalogue metadata here; bytes via presigned S3 URLs."""
import hashlib
import time
import uuid

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .audit import audit_event
from .auth import hash_password, new_token, verify_password
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# In-memory login rate limiter: {client_ip: [attempt_epoch, ...]}.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_allowed(client_ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    window = settings.login_rate_window
    limit = settings.login_rate_limit
    attempts = [t for t in _LOGIN_ATTEMPTS.get(client_ip, []) if now - t < window]
    if len(attempts) >= limit:
        _LOGIN_ATTEMPTS[client_ip] = attempts
        return False
    attempts.append(now)
    _LOGIN_ATTEMPTS[client_ip] = attempts
    return True


def reset_login_attempts() -> None:
    _LOGIN_ATTEMPTS.clear()

s3 = make_client(
    settings.s3_endpoint, settings.s3_access_key, settings.s3_secret_key,
    settings.s3_region,
)

# Bootstrap the single admin user on first boot (password hashed, never stored raw).
if repo.get_user_by_name(settings.admin_user) is None:
    repo.create_user(settings.admin_user, hash_password(settings.admin_password))


class LoginIn(BaseModel):
    username: str
    password: str


class UploadIntentIn(BaseModel):
    bucket: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=127)
    folder_id: str | None = None


def current_user(aura_session: str | None = Cookie(default=None)) -> dict:
    if not aura_session:
        raise HTTPException(status_code=401, detail="authentication required")
    row = repo.get_session(aura_session)
    if row is None:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return {"id": row["user_id"], "session_id": row["id"], "csrf": row["csrf"]}


def require_csrf(
    user: dict = Depends(current_user),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    if not x_csrf_token or x_csrf_token != user["csrf"]:
        raise HTTPException(status_code=403, detail="csrf validation failed")
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


@app.post("/api/v1/login")
def login(body: LoginIn, request: Request, response: Response):
    client_ip = _client_ip(request)
    if not _login_allowed(client_ip):
        audit_event("login", body.username, "rate_limited")
        raise HTTPException(status_code=429, detail="too many login attempts")
    row = repo.get_user_by_name(body.username)
    if row is None or not verify_password(row["pass_hash"], body.password):
        audit_event("login", body.username, "failure")
        raise HTTPException(status_code=401, detail="invalid credentials")
    csrf = new_token(16)
    sid = repo.create_session(
        row["id"], csrf, int(time.time()) + settings.session_ttl
    )
    response.set_cookie(
        "aura_session", sid, httponly=True, secure=settings.cookie_secure,
        samesite="strict", max_age=settings.session_ttl, path="/",
    )
    audit_event("login", body.username, "success", {"user_id": row["id"]})
    return {"csrf_token": csrf}


@app.post("/api/v1/logout")
def logout(user: dict = Depends(current_user), response: Response = None):
    repo.delete_session(user["session_id"])
    audit_event("logout", user["id"], "success")
    out = JSONResponse(content={"status": "logged out"})
    out.delete_cookie("aura_session", path="/")
    return out


@app.post("/api/v1/objects/upload-intents")
def upload_intent(body: UploadIntentIn, user: dict = Depends(require_csrf)):
    key = f"aura/{user['id']}/{uuid.uuid4()}"
    oid = repo.create_pending_object(
        body.bucket, key, body.display_name, body.content_type, user["id"],
        body.folder_id,
    )
    url = presigned_put(s3, body.bucket, key, body.content_type, settings.intent_ttl)
    audit_event("upload-intent", user["id"], "success", {
        "object_id": oid, "bucket": body.bucket,
        "expires_in": settings.intent_ttl,
    })
    return {"id": oid, "upload_url": url, "expires_in": settings.intent_ttl}


@app.post("/api/v1/objects/{oid}/commit")
def commit_object(oid: str, user: dict = Depends(require_csrf)):
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
    audit_event("commit", user["id"], "success", {"object_id": oid})
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
def soft_delete_object(oid: str, user: dict = Depends(require_csrf)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    status = row["status"] if isinstance(row, dict) else row["status"]
    if status not in ("available", "pending"):
        raise HTTPException(status_code=409, detail="object not deletable")
    repo.set_status(oid, "deleted")
    return {"id": oid, "status": "deleted"}


@app.post("/api/v1/objects/{oid}/purge")
def purge(oid: str, user: dict = Depends(require_csrf)):
    if not purge_object(repo, s3, oid, user["id"]):
        raise HTTPException(status_code=404, detail="object not found")
    return {"id": oid, "status": "purged"}


@app.post("/api/v1/admin/reconcile")
def reconcile(user: dict = Depends(require_csrf)):
    return reconcile_pending(repo, s3)


@app.post("/api/v1/objects/{oid}/download-intent")
def download_intent(oid: str, user: dict = Depends(require_csrf)):
    row = repo.get_object(oid, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    url = presigned_get(s3, row["bucket"], row["object_key"], settings.intent_ttl)
    audit_event("download-intent", user["id"], "success", {"object_id": oid})
    return {"download_url": url, "expires_in": settings.intent_ttl}
