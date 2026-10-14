"""AURA Management API (#18; authz #35/#36, M2M #38, streaming commit #37).

Catalogue metadata lives here; object bytes travel directly between the client
and S3 through short-lived presigned URLs. The API never stores a browser session
token in the response body and never puts S3 credentials in the frontend.
"""
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import authz, netinfo
from .audit import audit_event
from .auth import hash_password, new_token, verify_password
from .authz import (
    ADMIN_READ,
    ADMIN_WRITE,
    ALL_SCOPES,
    OBJECTS_DELETE,
    OBJECTS_PURGE,
    OBJECTS_READ,
    OBJECTS_WRITE,
    SERVICE_SCOPES,
    authorize,
    effective_scopes,
)
from .config import settings
from .identity import fingerprint, format_token, new_secret
from .lifecycle import purge_object, reconcile_pending
from .s3 import (
    ObjectTooLarge,
    is_valid_bucket_name,
    make_clients,
    presigned_get,
    presigned_put,
    stream_sha256,
)
from .store import repo

app = FastAPI(title="AURA Management API", version="0.2.0")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# In-memory login rate limiter: {client_ip: [failure_epoch, ...]}.
# Only *failed* attempts are counted, so a burst of legitimate logins cannot
# lock out everyone sharing a proxy/NAT address.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    # Trusted-proxy aware: browsers arrive through Traefik and nginx, so the
    # socket peer is a proxy; see api/netinfo.py (#35/#38).
    return netinfo.client_ip(request)


def _login_blocked(client_ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    window = settings.login_rate_window
    attempts = [t for t in _LOGIN_ATTEMPTS.get(client_ip, []) if now - t < window]
    if attempts:
        _LOGIN_ATTEMPTS[client_ip] = attempts
    else:
        _LOGIN_ATTEMPTS.pop(client_ip, None)
    return len(attempts) >= settings.login_rate_limit


def _login_record_failure(client_ip: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(client_ip, []).append(time.time())


def _login_clear(client_ip: str) -> None:
    # A successful login resets the failure budget for that client.
    _LOGIN_ATTEMPTS.pop(client_ip, None)


def reset_login_attempts() -> None:
    _LOGIN_ATTEMPTS.clear()

s3, s3ops = make_clients(
    settings.s3_endpoint, settings.s3_internal_endpoint,
    settings.s3_access_key, settings.s3_secret_key, settings.s3_region,
)


def _ensure_bootstrap_admin() -> None:
    """Create, or promote, the single bootstrap administrator (hashed password)."""
    row = repo.get_user_by_name(settings.admin_user)
    if row is None:
        repo.create_user(
            settings.admin_user, hash_password(settings.admin_password), role="admin"
        )
    else:
        repo.ensure_admin(row["id"])


_ensure_bootstrap_admin()


def _as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _object_scope(principal: dict) -> dict:
    """Catalogue filter for the caller: space always, owner for human users."""
    return {
        "space_id": principal["space_id"],
        "owner_id": principal["id"] if principal["kind"] == "user" else None,
    }


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class UploadIntentIn(BaseModel):
    # `bucket` is optional and validated against the caller's space (#36). Object
    # keys are always generated server-side; no client field can choose them.
    model_config = ConfigDict(extra="forbid")
    bucket: str | None = Field(default=None, max_length=63)
    display_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=127)
    # Declared upload size. It is bound into the presigned URL as a signed
    # Content-Length so an uploader cannot exceed it (#40); the API refuses a
    # declared size above the configured object cap before presigning.
    size_bytes: int = Field(ge=1)
    folder_id: str | None = None

    @field_validator("size_bytes")
    @classmethod
    def _within_object_cap(cls, value: int) -> int:
        if value > settings.max_object_bytes:
            raise ValueError("size_bytes exceeds the maximum allowed object size")
        return value


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)


class SpaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=63)
    environment: str = Field(min_length=1, max_length=32)
    default_bucket: str | None = Field(default=None, max_length=63)


class IdentityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=63)
    scopes: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=1)


@app.get("/health/live")
def live():
    return {"status": "live"}


@app.get("/health/ready")
def ready():
    try:
        s3ops.list_buckets()
        return {"status": "ready"}
    except Exception:  # never leak backend details
        return JSONResponse(status_code=503, content={"status": "not ready"})


@app.post("/api/v1/login")
def login(body: LoginIn, request: Request, response: Response):
    client_ip = _client_ip(request)
    if _login_blocked(client_ip):
        audit_event("login", body.username, "rate_limited")
        raise HTTPException(status_code=429, detail="too many login attempts")
    row = repo.get_user_by_name(body.username)
    if row is None or not verify_password(row["pass_hash"], body.password):
        _login_record_failure(client_ip)
        audit_event("login", body.username, "failure")
        raise HTTPException(status_code=401, detail="invalid credentials")
    _login_clear(client_ip)
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
def logout(principal: dict = Depends(authorize(human=True))):
    repo.delete_session(principal["session_id"])
    audit_event("logout", principal["id"], "success")
    out = JSONResponse(content={"status": "logged out"})
    out.delete_cookie("aura_session", path="/")
    return out


@app.get("/api/v1/me")
def me(principal: dict = Depends(authorize())):
    return {
        "id": principal["id"],
        "kind": principal["kind"],
        "role": principal["role"],
        "space_id": principal["space_id"],
        "application_id": principal["application_id"],
        "scopes": sorted(effective_scopes(principal)),
    }


@app.post("/api/v1/objects/upload-intents")
def upload_intent(body: UploadIntentIn, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    space_id = principal["space_id"]
    if not space_id:
        raise HTTPException(status_code=403, detail="forbidden")

    if body.bucket:
        if repo.get_bucket_for_space(space_id, body.bucket) is None:
            # A client-supplied bucket that is not registered for this space is
            # refused outright (#36): no arbitrary bucket selection.
            raise HTTPException(status_code=403, detail="forbidden")
        bucket = body.bucket
    else:
        default_bucket = repo.get_default_bucket(space_id)
        if default_bucket is None:
            raise HTTPException(status_code=409, detail="no storage bucket configured")
        bucket = default_bucket["name"]

    if repo.count_pending(**_object_scope(principal)) >= settings.max_pending_intents:
        raise HTTPException(status_code=429, detail="too many pending uploads")

    owner_id = principal["id"] if principal["kind"] == "user" else None
    key = f"aura/{space_id}/{principal['id']}/{uuid.uuid4()}"
    intent_expires_at = int(time.time()) + settings.intent_ttl
    oid = repo.create_pending_object(
        space_id=space_id, application_id=principal["application_id"],
        environment=principal["environment"], bucket=bucket, object_key=key,
        display_name=body.display_name, content_type=body.content_type,
        owner_id=owner_id, actor_id=principal["id"], actor_kind=principal["kind"],
        intent_expires_at=intent_expires_at, folder_id=body.folder_id,
    )
    url = presigned_put(
        s3, bucket, key, body.content_type, settings.intent_ttl, body.size_bytes
    )
    audit_event("upload-intent", principal["id"], "success", {
        "object_id": oid, "bucket": bucket, "expires_in": settings.intent_ttl,
        "size_bytes": body.size_bytes,
    })
    return {
        "id": oid, "upload_url": url, "size_bytes": body.size_bytes,
        "expires_in": settings.intent_ttl,
    }


@app.post("/api/v1/objects/{oid}/commit")
def commit_object(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)

    if row["status"] == "available":
        # Idempotent: a repeated commit returns the already-verified object (#37).
        return {
            "id": oid, "status": "available", "size_bytes": row["size_bytes"],
            "checksum_sha256": row["checksum_sha256"],
        }
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="object not committable")

    expires_at = row.get("intent_expires_at")
    if expires_at and int(time.time()) > int(expires_at) + settings.intent_grace_s:
        repo.set_status(oid, "expired")
        audit_event("commit", principal["id"], "expired", {"object_id": oid})
        raise HTTPException(status_code=410, detail="upload intent expired")

    try:
        head = s3ops.head_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception:
        raise HTTPException(status_code=422, detail="upload not found at storage")

    size = int(head.get("ContentLength", -1))
    if size < 0:
        raise HTTPException(status_code=422, detail="upload size unknown")
    if size > settings.max_object_bytes:
        repo.set_status(oid, "failed")
        raise HTTPException(status_code=413, detail="object exceeds maximum allowed size")

    try:
        body = s3ops.get_object(Bucket=row["bucket"], Key=row["object_key"])["Body"]
        total, digest = stream_sha256(
            body, settings.max_object_bytes, settings.commit_chunk_bytes
        )
    except ObjectTooLarge:
        repo.set_status(oid, "failed")
        raise HTTPException(status_code=413, detail="object exceeds maximum allowed size")
    except Exception:
        raise HTTPException(status_code=422, detail="upload not readable at storage")

    if total != size:
        # Truncated or mismatched upload is never marked available (#37).
        repo.set_status(oid, "failed")
        raise HTTPException(status_code=422, detail="uploaded size does not match storage")

    repo.mark_available(oid, size, digest)
    audit_event("commit", principal["id"], "success", {"object_id": oid, "size_bytes": size})
    return {"id": oid, "status": "available", "size_bytes": size, "checksum_sha256": digest}


@app.get("/api/v1/objects")
def list_objects(
    principal: dict = Depends(authorize(OBJECTS_READ)), limit: int = 50, offset: int = 0
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    rows = repo.list_objects(**_object_scope(principal), limit=limit, offset=offset)
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
def get_object(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    return {
        "id": row["id"], "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"],
        "checksum_sha256": row["checksum_sha256"], "status": row["status"],
    }


@app.delete("/api/v1/objects/{oid}")
def soft_delete_object(oid: str, principal: dict = Depends(authorize(OBJECTS_DELETE))):
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] not in ("available", "pending"):
        raise HTTPException(status_code=409, detail="object not deletable")
    repo.set_status(oid, "deleted")
    audit_event("delete", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "deleted"}


@app.post("/api/v1/objects/{oid}/purge")
def purge(oid: str, principal: dict = Depends(authorize(OBJECTS_PURGE))):
    # Destructive: requires objects:purge (operator/admin), not merely a session.
    if not purge_object(repo, s3ops, oid, **_object_scope(principal)):
        raise HTTPException(status_code=404, detail="object not found")
    audit_event("purge", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "purged"}


@app.post("/api/v1/objects/{oid}/download-intent")
def download_intent(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    url = presigned_get(s3, row["bucket"], row["object_key"], settings.intent_ttl)
    audit_event("download-intent", principal["id"], "success", {"object_id": oid})
    return {"download_url": url, "expires_in": settings.intent_ttl}


# ---------------------------------------------------------------------------
# Administration (#35, #36, #38): require the admin:* capabilities.
# ---------------------------------------------------------------------------
@app.post("/api/v1/admin/reconcile")
def reconcile(principal: dict = Depends(authorize(ADMIN_WRITE))):
    out = reconcile_pending(repo, s3ops)
    audit_event("admin.reconcile", principal["id"], "success", out)
    return out


@app.get("/api/v1/admin/stats")
def admin_stats(principal: dict = Depends(authorize(ADMIN_READ))):
    return repo.stats()


@app.post("/api/v1/admin/applications")
def create_application(body: ApplicationIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    if repo.get_application_by_name(body.name) is not None:
        raise HTTPException(status_code=409, detail="application already exists")
    aid = repo.create_application(body.name)
    audit_event("admin.application.create", principal["id"], "success", {"application_id": aid})
    return {"id": aid, "name": body.name}


@app.get("/api/v1/admin/applications")
def list_applications(principal: dict = Depends(authorize(ADMIN_READ))):
    return {"items": [
        {"id": a["id"], "name": a["name"], "status": a["status"]}
        for a in repo.list_applications()
    ]}


@app.post("/api/v1/admin/spaces")
def create_space(body: SpaceIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    if repo.get_application(body.application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")
    bucket = body.default_bucket or f"aura-{body.name}-{body.environment}"
    if not is_valid_bucket_name(bucket):
        # Refuse up front rather than register a bucket name S3 will reject (#41).
        raise HTTPException(status_code=422, detail="invalid bucket name")
    if repo.get_bucket_by_name(bucket) is not None:
        raise HTTPException(status_code=409, detail="bucket name already in use")
    sid = repo.create_space(body.application_id, body.name, body.environment)
    repo.create_bucket(sid, bucket, is_default=True)
    audit_event("admin.space.create", principal["id"], "success", {"space_id": sid})
    return {"id": sid, "bucket": bucket}


@app.get("/api/v1/admin/spaces")
def list_spaces(principal: dict = Depends(authorize(ADMIN_READ))):
    return {"items": [
        {"id": s["id"], "application_id": s["application_id"], "name": s["name"],
         "environment": s["environment"]}
        for s in repo.list_spaces()
    ]}


@app.post("/api/v1/admin/identities")
def create_identity(body: IdentityIn, principal: dict = Depends(authorize(ADMIN_WRITE))):
    space = repo.get_space(body.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    scopes = set(body.scopes)
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
    identity_id = repo.new_id()
    secret = new_secret()
    expires_at = int(time.time()) + body.ttl_seconds if body.ttl_seconds else None
    repo.create_identity(
        identity_id, space["application_id"], body.space_id, body.name,
        fingerprint(secret), ",".join(sorted(scopes)), expires_at,
    )
    token = format_token(identity_id, secret)
    audit_event("admin.identity.create", principal["id"], "success",
                {"identity_id": identity_id, "space_id": body.space_id})
    # The token is returned exactly once; it is never logged or stored in clear.
    return {
        "id": identity_id, "name": body.name, "space_id": body.space_id,
        "application_id": space["application_id"], "scopes": sorted(scopes),
        "expires_at": expires_at, "token": token,
    }


@app.get("/api/v1/admin/identities")
def list_identities(space_id: str | None = None,
                    principal: dict = Depends(authorize(ADMIN_READ))):
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


@app.post("/api/v1/admin/identities/{iid}/rotate")
def rotate_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    row = repo.get_identity(iid)
    if row is None or row.get("revoked_at"):
        raise HTTPException(status_code=404, detail="identity not found")
    secret = new_secret()
    repo.update_identity_secret(iid, fingerprint(secret))
    audit_event("admin.identity.rotate", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "token": format_token(iid, secret)}


@app.post("/api/v1/admin/identities/{iid}/revoke")
def revoke_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    row = repo.get_identity(iid)
    if row is None:
        raise HTTPException(status_code=404, detail="identity not found")
    repo.revoke_identity(iid)
    audit_event("admin.identity.revoke", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "revoked": True}
