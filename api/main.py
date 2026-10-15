"""AURA Management API (#18; authz #35/#36, M2M #38, streaming commit #37).

Catalogue metadata lives here; object bytes travel directly between the client
and S3 through short-lived presigned URLs. The API never stores a browser session
token in the response body and never puts S3 credentials in the frontend.
"""
import time
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from . import authz, ids, netinfo
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
from .transfer import (
    ABORTED,
    AVAILABLE,
    DELETED,
    EXPIRED,
    PENDING,
    validate_upload_policy,
    valid_idempotency_key,
)

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


def _canonical_id(value: str, field: str) -> str:
    """Return ``value`` as a canonical UUID v4, or raise 422.

    Identifiers AURA issues are always canonical UUID v4 (``api/ids.py``), so a
    request carrying anything else is a client error, not a lookup miss.
    """
    canonical = ids.canonical(value)
    if canonical is None:
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return canonical


def _canonical_uuid(value: str) -> str:
    """Pydantic validator helper: canonicalize or fail with 422."""
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical


# Canonical identifier type for request bodies. Accepts the alternate spellings
# ``uuid.UUID`` understands (case, braces, ``urn:``) and normalizes them, but
# rejects anything that is not a UUID v4.
Uuid4 = Annotated[str, AfterValidator(_canonical_uuid)]


def _object_scope(principal: dict) -> dict:
    """Catalogue filter for the caller: space always, owner for human users."""
    return {
        "space_id": principal["space_id"],
        "owner_id": principal["id"] if principal["kind"] == "user" else None,
    }


# Folders (#61) are logical catalogue entities owned by a human user. Names are
# flat labels (no path semantics): a separator or control character is refused.
MAX_FOLDER_DEPTH = 32


def _validate_folder_name(value: str) -> str:
    name = value.strip()
    if not name or name in (".", ".."):
        raise ValueError("invalid folder name")
    if any(ch in name for ch in ("/", "\\")) or any(ord(ch) < 32 for ch in name):
        raise ValueError("invalid folder name")
    return name


def _folder_public(row) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "created_at": row["created_at"],
    }


def _object_public(row) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"], "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"],
        "expected_size_bytes": row.get("expected_size_bytes"),
        "checksum_sha256": row["checksum_sha256"],
        "checksum_algorithm": "sha256",
        "status": row["status"],
        "folder_id": row["folder_id"],
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
    # declared size above the configured object cap before presigning. Zero is
    # accepted only when empty objects are enabled for this deployment.
    size_bytes: int = Field(ge=0)
    folder_id: Uuid4 | None = None


class ObjectPatchIn(BaseModel):
    # Object reassignment into a logical folder (#62). `model_fields_set`
    # distinguishes "not sent" from an explicit null (which unfiles the object
    # back to the root level).
    model_config = ConfigDict(extra="forbid")
    folder_id: Uuid4 | None = None


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)


class SpaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: Uuid4
    name: str = Field(min_length=1, max_length=63)
    environment: str = Field(min_length=1, max_length=32)
    default_bucket: str | None = Field(default=None, max_length=63)


class IdentityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: Uuid4
    name: str = Field(min_length=1, max_length=63)
    scopes: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=1)


class FolderIn(BaseModel):
    # Logical folder creation (#61). `parent_id` is omitted/null for a root folder.
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_id: Uuid4 | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _validate_folder_name(value)


class FolderPatchIn(BaseModel):
    # Partial update. `model_fields_set` distinguishes "not sent" from an explicit
    # null (which moves the folder back to the root level).
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: Uuid4 | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_folder_name(value)


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
def upload_intent(
    body: UploadIntentIn, request: Request,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    space_id = principal["space_id"]
    if not space_id:
        raise HTTPException(status_code=403, detail="forbidden")

    # Authoritative server-side transfer policy: media type, size ceiling and
    # empty-file rule. A malformed/blocked type or an out-of-range size is a 422
    # before any intent row or presigned URL exists. The browser checks are UX.
    try:
        content_type = validate_upload_policy(
            body.content_type, body.size_bytes,
            max_bytes=settings.max_object_bytes,
            allow_empty=settings.allow_empty_objects,
            allowed_types=settings.allowed_content_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    idem_key = request.headers.get("idempotency-key")
    if idem_key is not None and not valid_idempotency_key(
        idem_key, max_length=settings.idempotency_key_max
    ):
        raise HTTPException(status_code=422, detail="invalid idempotency key")

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

    # Idempotent replay: an accidental double submit carrying the same
    # Idempotency-Key returns the same pending intent with a freshly signed URL
    # instead of creating a second object row. The key is opaque and never
    # logged; only the replay outcome is audited.
    if idem_key:
        existing = repo.get_pending_by_idempotency(
            actor_id=principal["id"], idempotency_key=idem_key, space_id=space_id
        )
        if existing is not None:
            existing = _as_dict(existing)
            expires_at = existing.get("intent_expires_at")
            if not expires_at or int(time.time()) <= int(expires_at) + settings.intent_grace_s:
                expected = existing.get("expected_size_bytes")
                if expected is None or expected < 0:
                    expected = body.size_bytes
                url = presigned_put(
                    s3, existing["bucket"], existing["object_key"],
                    existing["content_type"], settings.intent_ttl, expected,
                )
                audit_event("upload-intent", principal["id"], "replay", {
                    "object_id": existing["id"], "bucket": existing["bucket"],
                })
                return {
                    "id": existing["id"], "status": PENDING, "method": "PUT",
                    "upload_url": url,
                    "headers": {"Content-Type": existing["content_type"]},
                    "content_type": existing["content_type"],
                    "size_bytes": expected, "expires_in": settings.intent_ttl,
                    "expires_at": expires_at, "idempotent_replay": True,
                }
            # The prior intent is past its grace window: retire it so the
            # catalogue never keeps two live intents for one key.
            repo.set_status(existing["id"], EXPIRED)

    if repo.count_pending(**_object_scope(principal)) >= settings.max_pending_intents:
        raise HTTPException(status_code=429, detail="too many pending uploads")

    if body.folder_id is not None:
        # A client-supplied folder must exist and be owned by the caller (#61).
        # Service identities own no folders, so any folder_id they send is refused.
        if principal["kind"] != "user" or repo.get_folder(
            body.folder_id, owner_id=principal["id"]
        ) is None:
            raise HTTPException(status_code=403, detail="forbidden")

    owner_id = principal["id"] if principal["kind"] == "user" else None
    key = f"aura/{space_id}/{principal['id']}/{ids.new_id()}"
    intent_expires_at = int(time.time()) + settings.intent_ttl
    oid = repo.create_pending_object(
        space_id=space_id, application_id=principal["application_id"],
        environment=principal["environment"], bucket=bucket, object_key=key,
        display_name=body.display_name, content_type=content_type,
        owner_id=owner_id, actor_id=principal["id"], actor_kind=principal["kind"],
        intent_expires_at=intent_expires_at, folder_id=body.folder_id,
        expected_size_bytes=body.size_bytes, idempotency_key=idem_key,
    )
    url = presigned_put(
        s3, bucket, key, content_type, settings.intent_ttl, body.size_bytes
    )
    audit_event("upload-intent", principal["id"], "success", {
        "object_id": oid, "bucket": bucket, "expires_in": settings.intent_ttl,
        "size_bytes": body.size_bytes,
    })
    return {
        "id": oid, "status": PENDING, "method": "PUT", "upload_url": url,
        "headers": {"Content-Type": content_type},
        "content_type": content_type, "size_bytes": body.size_bytes,
        "expires_in": settings.intent_ttl, "expires_at": intent_expires_at,
        "idempotent_replay": False,
    }


@app.post("/api/v1/objects/{oid}/commit")
def commit_object(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)

    if row["status"] == "available":
        # Idempotent: a repeated commit returns the already-verified object (#37).
        return {
            "id": oid, "status": "available", "size_bytes": row["size_bytes"],
            "checksum_sha256": row["checksum_sha256"],
            "checksum_algorithm": "sha256",
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
    return {
        "id": oid, "status": "available", "size_bytes": size,
        "checksum_sha256": digest, "checksum_algorithm": "sha256",
    }


@app.post("/api/v1/objects/{oid}/abort")
def abort_object(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    """Cancel a pending upload intent and best-effort remove its partial bytes.

    This is the explicit backend cancellation mechanism the UI is allowed to use
    (``OBJECTS_WRITE``). It is idempotent: aborting an already aborted/expired
    intent returns the same terminal state. A committed (available) object cannot
    be aborted — that would be a delete, not a transfer cancellation — so it is
    refused with 409. Only the caller's own space/scope is visible (404 else).
    """
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)

    if row["status"] in (AVAILABLE, DELETED):
        raise HTTPException(status_code=409, detail="object not abortable")
    if row["status"] in (ABORTED, EXPIRED):
        # Idempotent: a repeated abort returns the existing terminal state.
        return {"id": oid, "status": row["status"], "aborted": True}
    if row["status"] != PENDING:
        raise HTTPException(status_code=409, detail="object not abortable")

    try:
        s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception:
        # A transient storage error must not block the catalogue transition; the
        # reconciliation sweep retries orphan cleanup after its grace period.
        pass
    repo.set_status(oid, ABORTED)
    audit_event("abort", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": ABORTED, "aborted": True}


@app.get("/api/v1/objects")
def list_objects(
    principal: dict = Depends(authorize(OBJECTS_READ)), limit: int = 50, offset: int = 0,
    folder_id: str | None = None,
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    # ``folder_id`` is an optional catalogue filter (#62): the literal "root"
    # selects objects not filed in any folder; a canonical uuid selects that
    # folder. Unknown or foreign folder ids simply match nothing (no leak).
    folder_filter: str | None = None
    if folder_id is not None:
        folder_filter = "" if folder_id == "root" else _canonical_id(folder_id, "folder id")
    rows = repo.list_objects(
        **_object_scope(principal), folder_id=folder_filter, limit=limit, offset=offset
    )
    return {"items": [_object_public(r) for r in rows]}


@app.get("/api/v1/objects/{oid}")
def get_object(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    return _object_public(row)


@app.delete("/api/v1/objects/{oid}")
def soft_delete_object(oid: str, principal: dict = Depends(authorize(OBJECTS_DELETE))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] not in ("available", "pending"):
        raise HTTPException(status_code=409, detail="object not deletable")
    repo.set_status(oid, "deleted")
    audit_event("delete", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "deleted"}


@app.patch("/api/v1/objects/{oid}")
def update_object(
    oid: str, body: ObjectPatchIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    # File an object into a logical folder (or unfile it). Folders are owned by a
    # human user (#61), so this metadata move is a human-only capability; a
    # service identity has no folder to target and is refused by `human=True`.
    oid = _canonical_id(oid, "object id")
    if "folder_id" not in body.model_fields_set:
        raise HTTPException(status_code=422, detail="no fields to update")
    if repo.get_object(oid, **_object_scope(principal)) is None:
        # 404 (not 403) so the caller cannot probe for objects outside its scope.
        raise HTTPException(status_code=404, detail="object not found")
    if body.folder_id is not None and repo.get_folder(
        body.folder_id, owner_id=principal["id"]
    ) is None:
        # The target folder is owner-scoped: a foreign/unknown id is a 404.
        raise HTTPException(status_code=404, detail="folder not found")
    repo.set_object_folder(oid, folder_id=body.folder_id)
    audit_event("object.move", principal["id"], "success", {
        "object_id": oid, "folder_id": body.folder_id,
    })
    return _object_public(repo.get_object(oid, **_object_scope(principal)))


@app.post("/api/v1/objects/{oid}/purge")
def purge(oid: str, principal: dict = Depends(authorize(OBJECTS_PURGE))):
    # Destructive: requires objects:purge (operator/admin), not merely a session.
    oid = _canonical_id(oid, "object id")
    if not purge_object(repo, s3ops, oid, **_object_scope(principal)):
        raise HTTPException(status_code=404, detail="object not found")
    audit_event("purge", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "purged"}


@app.post("/api/v1/objects/{oid}/download-intent")
def download_intent(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != "available":
        raise HTTPException(status_code=409, detail="object not available")
    url = presigned_get(s3, row["bucket"], row["object_key"], settings.intent_ttl)
    audit_event("download-intent", principal["id"], "success", {"object_id": oid})
    return {
        "id": oid, "download_url": url, "method": "GET",
        "expires_in": settings.intent_ttl,
        "expires_at": int(time.time()) + settings.intent_ttl,
        "display_name": row["display_name"], "content_type": row["content_type"],
        "size_bytes": row["size_bytes"], "checksum_sha256": row["checksum_sha256"],
        "checksum_algorithm": "sha256",
    }


# ---------------------------------------------------------------------------
# Logical folders (#61). Human-owned catalogue metadata: no bytes, no host
# directories. A folder is addressed by its id and scoped to its owner, so one
# user can never observe or mutate another user's tree.
# ---------------------------------------------------------------------------
def _folder_owner(principal: dict) -> str:
    # ``folders.owner_id`` references ``users.id`` (NOT NULL), so folder
    # management is a human-user capability. Service identities are refused by
    # ``authorize(..., human=True)`` on every folder route below.
    return principal["id"]


def _folder_depth(fid: str, owner_id: str) -> int:
    """Number of ancestors+self for a folder; bounded by MAX_FOLDER_DEPTH."""
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
    """Longest downward path (in nodes) starting at ``fid``, including it."""
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


@app.get("/api/v1/folders")
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
        # Flat tree in a single request: the client rebuilds the hierarchy from
        # parent_id instead of walking the per-level endpoint (#62 follow-up).
        rows = repo.list_all_folders(owner_id=owner_id)
        return {"items": [_folder_public(r) for r in rows]}
    if parent_id is not None:
        parent_id = _canonical_id(parent_id, "parent id")
        if repo.get_folder(parent_id, owner_id=owner_id) is None:
            raise HTTPException(status_code=404, detail="folder not found")
    rows = repo.list_folders(owner_id=owner_id, parent_id=parent_id)
    return {"items": [_folder_public(r) for r in rows]}


@app.get("/api/v1/folders/{fid}")
def get_folder(fid: str, principal: dict = Depends(authorize(OBJECTS_READ, human=True))):
    fid = _canonical_id(fid, "folder id")
    row = repo.get_folder(fid, owner_id=_folder_owner(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return _folder_public(row)


@app.post("/api/v1/folders")
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


@app.patch("/api/v1/folders/{fid}")
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
        # Walk up from the prospective parent: reaching `fid` would create a cycle.
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
        # Moving the whole subtree here must not push any descendant past the cap.
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


@app.delete("/api/v1/folders/{fid}")
def delete_folder(fid: str, principal: dict = Depends(authorize(OBJECTS_DELETE, human=True))):
    fid = _canonical_id(fid, "folder id")
    owner_id = _folder_owner(principal)
    if repo.get_folder(fid, owner_id=owner_id) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    if repo.folder_child_count(fid, owner_id=owner_id) > 0:
        raise HTTPException(status_code=409, detail="folder is not empty")
    if repo.folder_object_count(fid, owner_id=owner_id) > 0:
        raise HTTPException(status_code=409, detail="folder is not empty")
    repo.delete_folder(fid, owner_id=owner_id)
    audit_event("folder.delete", principal["id"], "success", {"folder_id": fid})
    return {"id": fid, "status": "deleted"}


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


@app.post("/api/v1/admin/identities/{iid}/rotate")
def rotate_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    iid = _canonical_id(iid, "identity id")
    row = repo.get_identity(iid)
    if row is None or row.get("revoked_at"):
        raise HTTPException(status_code=404, detail="identity not found")
    secret = new_secret()
    repo.update_identity_secret(iid, fingerprint(secret))
    audit_event("admin.identity.rotate", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "token": format_token(iid, secret)}


@app.post("/api/v1/admin/identities/{iid}/revoke")
def revoke_identity(iid: str, principal: dict = Depends(authorize(ADMIN_WRITE))):
    iid = _canonical_id(iid, "identity id")
    row = repo.get_identity(iid)
    if row is None:
        raise HTTPException(status_code=404, detail="identity not found")
    repo.revoke_identity(iid)
    audit_event("admin.identity.revoke", principal["id"], "success", {"identity_id": iid})
    return {"id": iid, "revoked": True}
