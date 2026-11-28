"""AURA Management API (#18; authz #35/#36, M2M #38, streaming commit #37).

Catalogue metadata lives here; object bytes travel directly between the client
and S3 through short-lived presigned URLs. The API never stores a browser session
token in the response body and never puts S3 credentials in the frontend.
"""
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal
from html import escape as html_escape
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from . import (
    authz, folder_shares, google_oauth, ids, listen_events, magic_link, netinfo,
    public_book, public_classification, public_facets, public_series, public_ui,
    shares,
)
from .audit import (
    audit_event,
    audit_path,
    bind_request_context,
    prune_audit_log,
    query_audit_log,
    recent_error_events,
    reset_request_context,
    set_request_principal,
)
from .auth import hash_password, new_token, verify_password
from .authz import (
    ADMIN_READ,
    ADMIN_WRITE,
    ALL_SCOPES,
    OBJECTS_DELETE,
    OBJECTS_PURGE,
    OBJECTS_READ,
    OBJECTS_WRITE,
    PUBLIC_ROLE,
    SERVICE_SCOPES,
    _row_get,
    authorize,
    authenticate_public,
    effective_scopes,
    master_mode_active,
    require_public,
)
from .config import settings
from . import audio_classification_worker, media_worker
from .identity import fingerprint, format_token, new_secret
from .lifecycle import (
    purge_object,
    purge_transfer_history,
    reconcile_pending,
    reconcile_terminal,
    reconcile_reverse,
)
from .avscan import INFECTED as AV_INFECTED, TIMEOUT as AV_TIMEOUT, scan_object as av_scan_object
from .s3 import (
    SSE_ALGORITHM,
    SSE_HEADER,
    CommitDeadlineExceeded,
    ObjectTooLarge,
    abort_multipart,
    complete_multipart,
    copy_object,
    create_multipart,
    is_no_such_upload,
    is_valid_bucket_name,
    list_uploaded_parts,
    make_clients,
    make_probe_client,
    part_length,
    plan_parts,
    presigned_get,
    presigned_put,
    presigned_upload_part,
    stream_sha256,
)
from .store import repo
from .transfer import (
    ABORTED,
    AVAILABLE,
    DELETED,
    EXPIRED,
    PENDING,
    VERIFYING,
    validate_upload_policy,
    valid_idempotency_key,
)

from .app_factory import create_app

app = create_app()

# `GET /api/v1/objects/tags` must be registered before the dynamic
# `/api/v1/objects/{oid}` route, so this router is included here rather than
# with the other extracted routers at the bottom of the module.
from .routes_collections import router as collections_router  # noqa: E402
app.include_router(collections_router)

# Server-side idempotent response cache (D2): short-lived memo of commit/abort
# results keyed by (route, idempotency-key, object id) so a client retry does
# not re-run the integrity check. TTL is short; the catalogue remains the truth.
_RESP_CACHE: dict = {}
_RESP_CACHE_TTL = 300
_RESP_CACHE_MAX = 1000
# FastAPI runs sync routes in a threadpool: get/set must not iterate and mutate
# the dict concurrently (RuntimeError: dictionary changed size during iteration).
_RESP_CACHE_LOCK = threading.Lock()

# Simple per-space daily quota (D3). 0 disables.
_QUOTA: dict = {}

_QUOTA_LOCK = threading.Lock()


def _charge_quota(space_id: str, size_bytes: int) -> None:
    """Daily quota (D3): 429 when the space exceeds its budget, else debit it.

    Called after every other refusal (pending cap, capacity, folder) so a
    request that is rejected anyway never consumes budget; the check-and-debit
    is atomic across request threads. The counter is in memory (per process).
    """
    if settings.quota_bytes_per_day <= 0 and settings.quota_files_per_day <= 0:
        return
    today = int(time.time()) // 86400
    with _QUOTA_LOCK:
        q = _QUOTA.setdefault(space_id, {"day": today, "bytes": 0, "files": 0})
        if q["day"] != today:
            q["day"] = today
            q["bytes"] = 0
            q["files"] = 0
        if (settings.quota_files_per_day > 0 and q["files"] >= settings.quota_files_per_day) or (
            settings.quota_bytes_per_day > 0 and q["bytes"] + size_bytes > settings.quota_bytes_per_day
        ):
            raise HTTPException(status_code=429, detail="quota exceeded")
        q["files"] += 1
        q["bytes"] += size_bytes


def _usage_period(now: float | None = None) -> str:
    """UTC month key (``YYYY-MM``) used by the monthly counters."""
    return time.strftime("%Y-%m", time.gmtime(time.time() if now is None else now))


def _space_month_usage(space_id: str, period: str | None = None) -> dict:
    """This month's counters for a space, zero-filled when nothing happened."""
    period = period or _usage_period()
    row = repo.get_space_usage_monthly(space_id, period) or {}
    return {
        "period": period,
        "egress_bytes": int(row.get("egress_bytes") or 0),
        "download_intents": int(row.get("download_intents") or 0),
        "preview_intents": int(row.get("preview_intents") or 0),
        "share_redemptions": int(row.get("share_redemptions") or 0),
    }


def _space_quota(space_id: str) -> dict:
    row = repo.get_space_quotas(space_id) or {}
    return {
        "storage_bytes": row.get("storage_bytes"),
        "egress_bytes_monthly": row.get("egress_bytes_monthly"),
        "updated_at": row.get("updated_at"),
        "updated_by": row.get("updated_by"),
    }


def _check_storage_quota(space_id: str, size_bytes: int) -> None:
    """Hard per-space storage ceiling (monthly quota table).

    Enforced at upload intent, after the global capacity/pending checks so a
    request refused for another reason never reports a quota error. Pending
    intents are not reserved against the quota: the next commit can overshoot by
    at most the bytes already reserved, which is bounded by the pending caps.
    """
    quota = repo.get_space_quotas(space_id)
    limit = int(quota["storage_bytes"]) if quota and quota.get("storage_bytes") else 0
    if limit <= 0:
        return
    used = int(repo.space_usage(space_id)["stored_bytes"])
    if used + size_bytes > limit:
        raise HTTPException(status_code=429, detail="storage quota exceeded")


def _check_egress_quota(space_id: str, size_bytes: int) -> None:
    """Soft-by-design but blocking monthly egress ceiling.

    AURA never sees the bytes (the client fetches the presigned S3 URL), so the
    counter is an estimate: one issued intent or share redemption counts the
    object's full size. The request that would cross the ceiling is refused, so
    a quota cannot be silently exceeded by one large object.
    """
    quota = repo.get_space_quotas(space_id)
    limit = (
        int(quota["egress_bytes_monthly"])
        if quota and quota.get("egress_bytes_monthly") else 0
    )
    if limit <= 0:
        return
    used = _space_month_usage(space_id)["egress_bytes"]
    if used + max(0, size_bytes) > limit:
        raise HTTPException(status_code=429, detail="monthly egress quota exceeded")


def _record_egress(space_id: str, size_bytes: int, kind: str) -> None:
    """Account one issued transfer. Called after success only."""
    try:
        repo.record_space_egress(space_id, _usage_period(), kind, size_bytes)
    except Exception:
        # Metering must never turn a successful download into a 500.
        log.warning("egress metering failed for space %s (%s)", space_id, kind)


def _record_object_event(object_id: str, size_bytes: int, kind: str) -> None:
    try:
        repo.record_object_event(
            object_id, _usage_period(), kind, size_bytes, int(time.time())
        )
    except Exception:
        log.warning("object metering failed for %s (%s)", object_id, kind)
# uvicorn installs handlers on its own loggers only and leaves the root logger
# handler-free, so an INFO record from "api.main" is dropped by logging's
# lastResort handler (WARNING). Route through the logger uvicorn configures so
# commit timings are visible in `docker logs`.
log = logging.getLogger("uvicorn.error")


@app.on_event("startup")
def _start_media_worker() -> None:
    media_worker.start()


@app.on_event("startup")
def _start_audio_classification_worker() -> None:
    audio_classification_worker.start()


@app.on_event("startup")
def _enforce_session_ttl() -> None:
    """Sign out sessions minted under a longer TTL than the current policy.

    Shortening AURA_SESSION_TTL must actually shorten live sessions; otherwise
    a stolen 90-day cookie survives the fix until its original expiry.
    """
    try:
        revoked = repo.revoke_sessions_beyond(int(time.time()) + settings.session_ttl)
        if revoked:
            logging.getLogger("uvicorn.error").warning(
                "revoked %d session(s) longer than AURA_SESSION_TTL=%ss",
                revoked, settings.session_ttl,
            )
    except Exception:
        # Never prevent the API from starting because of a session cleanup.
        pass


@app.on_event("startup")
def _warn_on_unbounded_multipart() -> None:
    """Make the unproven multipart + no-capacity-guard combination visible.

    Neither the disk reclaim after abort nor the ~10 000-part completion is a
    closed proof on the pinned SeaweedFS. With the capacity guard off nothing
    refuses uploads before the disk fills, so an operator must see this on
    every boot rather than discover it from a 507-less incident.
    """
    if settings.multipart_enabled and settings.storage_capacity_bytes <= 0:
        log.warning(
            "AURA_MULTIPART_ENABLED=1 with AURA_STORAGE_CAPACITY_BYTES=0: "
            "no capacity refusal (507) and unproven abort reclaim — "
            "set the usable capacity and monitor multipart sessions"
        )


@app.on_event("startup")
def _start_verifier() -> None:
    # Large objects are hashed outside the commit request (N5).
    if settings.verify_worker == "inline":
        from .verifier import start_background
        start_background(repo, s3ops, settings, audit=audit_event)
    # Stored bytes are re-hashed periodically to catch silent corruption.
    if settings.scrub_enabled:
        from .scrubber import start_background as start_scrubber
        start_scrubber(repo, s3ops, settings, audit=audit_event)
    # The reconciliation sweep runs on its own (#144): without it, stale
    # intents and half-done purges waited for a human to call the admin route.
    if settings.reconcile_enabled:
        from .reconciler import start_background as start_reconciler
        start_reconciler(repo, s3ops, settings, audit=audit_event)
    # Bulk import jobs booked by the API are processed in the background.
    if settings.import_worker_enabled:
        from .import_worker import start_background as start_import_worker
        start_import_worker(repo, settings, audit=audit_event)


# Process boot time for the M07 supervision endpoint (uptime is informational).
_BOOT_TIME = int(time.time())

from .http_middleware import register_http_middlewares

register_http_middlewares(app)


# Login failure counters live in the shared catalogue (public_rate_counters)
# so the limit holds across workers (#322). Only failures are counted.
_LOGIN_RATE_PREFIX = "login:"
_PUBLIC_LOGIN_RATE_PREFIX = "public-login:"


def _client_ip(request: Request) -> str:
    # Trusted-proxy aware: browsers arrive through Traefik and nginx, so the
    # socket peer is a proxy; see api/netinfo.py (#35/#38).
    return netinfo.client_ip(request)


def _login_blocked(client_ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    allowed, _ = repo.rate_peek(
        f"{_LOGIN_RATE_PREFIX}{client_ip}", now=now,
        window=settings.login_rate_window, limit=settings.login_rate_limit,
    )
    return not allowed


def _login_record_failure(client_ip: str) -> None:
    repo.rate_hit(
        f"{_LOGIN_RATE_PREFIX}{client_ip}", now=time.time(),
        window=settings.login_rate_window, limit=settings.login_rate_limit,
    )


def _login_clear(client_ip: str) -> None:
    repo.rate_clear(f"{_LOGIN_RATE_PREFIX}{client_ip}")


def _public_login_blocked(client_ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    allowed, _ = repo.rate_peek(
        f"{_PUBLIC_LOGIN_RATE_PREFIX}{client_ip}", now=now,
        window=settings.login_rate_window, limit=settings.login_rate_limit,
    )
    return not allowed


def _public_login_record_failure(client_ip: str) -> None:
    repo.rate_hit(
        f"{_PUBLIC_LOGIN_RATE_PREFIX}{client_ip}", now=time.time(),
        window=settings.login_rate_window, limit=settings.login_rate_limit,
    )


def _public_login_clear(client_ip: str) -> None:
    repo.rate_clear(f"{_PUBLIC_LOGIN_RATE_PREFIX}{client_ip}")


# Public read endpoints (media redirect, covers, listening position) count EVERY
# request, not only failures: a scraper or a runaway client must not be able to
# mint unlimited presigned URLs or write unlimited rows. Limits are per client
# address and per minute, generous for a person (a 100-cover grid is one burst).
# Counters live in the catalogue (``public_rate_counters``), not in a process:
# several API workers must enforce the same limit.
_PUBLIC_RATE_WINDOW = 60.0
# HLS segments are many small requests (a few per minute per viewer), subtitles
# are fetched once per media: both are public capabilities and were previously
# exempt from any per-client throttling.
_PUBLIC_RATE_LIMITS = {
    "media": 120, "cover": 600, "progress": 120, "preview": 30,
    "hls": 240, "subtitle": 120, "search": 60,
}


def _rate_exceeded(retry: int) -> None:
    raise HTTPException(status_code=429, detail="too many requests",
                        headers={"Retry-After": str(retry)})


def _public_rate_hit(key: str, limit: int, window: float, raise_429: bool = True) -> bool:
    """Count one hit on ``key``; False (or HTTP 429) once ``limit`` hits fit in ``window``."""
    allowed, retry = repo.rate_hit(key, now=time.time(), window=window, limit=limit)
    if not allowed and raise_429:
        _rate_exceeded(retry)
    return allowed


def _public_rate_check(kind: str, request: Request) -> None:
    key = f"{kind}:{_client_ip(request)}"
    allowed, retry = repo.rate_hit(
        key, now=time.time(), window=_PUBLIC_RATE_WINDOW,
        limit=_PUBLIC_RATE_LIMITS[kind],
    )
    if not allowed:
        _rate_exceeded(retry)


def reset_login_attempts() -> None:
    try:
        repo.clear_rate_counters()
    except Exception:
        # Test-only reset: never let a catalogue hiccup break a request path.
        pass

s3, s3ops = make_clients(
    settings.s3_endpoint, settings.s3_internal_endpoint,
    settings.s3_access_key, settings.s3_secret_key, settings.s3_region,
)
# Supervision only: answers within seconds when the storage is down.
s3probe = make_probe_client(
    settings.s3_internal_endpoint, settings.s3_access_key,
    settings.s3_secret_key, settings.s3_region,
)


def _ensure_bootstrap_admin() -> None:
    """Create, or promote, the single bootstrap administrator (hashed password).

    A weak bootstrap password is accepted for existing deployments (changing it
    silently would lock the operator out) but logged loudly, and any implicit
    promotion of an existing account is audited in the process log.
    """
    logger = logging.getLogger("uvicorn.error")
    row = repo.get_user_by_name(settings.admin_user)
    if row is None:
        if len(settings.admin_password) < 12:
            logger.warning(
                "bootstrap admin password is shorter than 12 characters; "
                "rotate AURA_API_ADMIN_PASSWORD"
            )
        repo.create_user(
            settings.admin_user, hash_password(settings.admin_password), role="admin"
        )
        return
    if row["role"] != "admin":
        logger.warning(
            "bootstrap user %r already existed: promoting it to admin (no password "
            "rotation; AURA_API_ADMIN_PASSWORD is only used at creation)",
            settings.admin_user,
        )
    repo.ensure_admin(row["id"])


_ensure_bootstrap_admin()

# Verified against when the username is unknown (timing equalisation in login).
_DUMMY_PASS_HASH = hash_password(new_token(32))


from .normalizers import as_dict as _as_dict


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

# Object list query vocabulary (M02). Literals make FastAPI return 422 for any
# unsupported value and let the OpenAPI document describe the accepted set.
ObjectStatus = Literal[
    "pending", "verifying", "available", "suspect", "deleted", "expired", "failed",
    "aborted", "purging",
]
ObjectSort = Literal["created_at", "display_name", "size_bytes"]
SortOrder = Literal["asc", "desc"]
TransferStatus = Literal["available", "failed", "aborted", "expired"]


def _object_scope(principal: dict) -> dict:
    """Catalogue filter for the caller: space always, owner for plain users.

    Operators and administrators are space-wide on purpose: objects created by
    a machine identity have ``owner_id = NULL`` and would otherwise be invisible
    (and unpurgeable) to every human once the machine token is revoked, which is
    a retention/governance dead end. A plain user still only sees their own.
    """
    owner_id = principal["id"] if principal["kind"] == "user" else None
    if principal["kind"] == "user" and effective_scopes(principal) & {ADMIN_READ, ADMIN_WRITE}:
        owner_id = None
    return {"space_id": principal["space_id"], "owner_id": owner_id}


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


def _folder_public(row, size_bytes: int | None = None) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "created_at": row["created_at"],
        "size_bytes": size_bytes,
    }


# Lifecycle values accepted by the admin registry (#M04). Applications and spaces
# are soft-disabled, never deleted: a disable stops new provisioning/upload while
# keeping every catalogue row readable.
APPLICATION_STATUSES = frozenset({"active", "disabled"})
SPACE_STATUSES = frozenset({"active", "disabled"})


def _trim_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("name must not be blank")
    return name


def _application_public(row) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"], "name": row["name"], "status": row["status"],
        "created_at": row["created_at"],
    }


def _space_public(row) -> dict:
    row = _as_dict(row)
    return {
        "id": row["id"], "application_id": row["application_id"],
        "name": row["name"], "environment": row["environment"],
        "status": row["status"], "created_at": row["created_at"],
    }


def _bucket_public(row) -> dict:
    row = _as_dict(row)
    # A bucket row carries no S3 credential: the access key/secret live only in
    # the deployment environment and are never part of the catalogue (#M04).
    return {
        "id": row["id"], "space_id": row["space_id"], "name": row["name"],
        "is_default": bool(row["is_default"]), "created_at": row["created_at"],
    }


def _object_public(row, tags: list | None = None) -> dict:
    row = _as_dict(row)
    # Only catalogue metadata that is safe to surface. ``bucket`` and
    # ``object_key`` are internal storage coordinates and are never returned.
    return {
        "id": row["id"], "display_name": row["display_name"],
        "content_type": row["content_type"], "size_bytes": row["size_bytes"],
        "expected_size_bytes": row.get("expected_size_bytes"),
        "checksum_sha256": row["checksum_sha256"],
        "checksum_algorithm": "sha256",
        "status": row["status"],
        "folder_id": row["folder_id"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        # Publication and generated preview metadata. The storage key of the
        # thumbnail is never exposed, only whether one exists.
        "public_slug": row.get("public_slug"),
        "published_at": row.get("published_at"),
        "thumbnail": bool(row.get("thumbnail_key")),
        "duration_seconds": row.get("duration_seconds"),
        "hls_status": row.get("hls_status"),
        "subtitle": bool(row.get("subtitle_object_id")),
        "tags": list(tags or []),
    }


def _transfer_public(row) -> dict:
    """Safe projection of a terminal transfer journal row (#246).

    Deliberately no bucket, object key, storage path, presigned URL or token:
    the journal never stores them, and this projection cannot invent them.
    """
    row = _as_dict(row)
    return {
        "id": row["id"],
        "transfer_session_id": row.get("transfer_session_id"),
        "object_id": row.get("object_id"),
        "space_id": row.get("space_id"),
        "owner_id": row.get("owner_id"),
        "actor_id": row.get("actor_id"),
        "actor_kind": row.get("actor_kind"),
        "display_name": row.get("display_name") or "",
        "content_type": row.get("content_type") or "",
        "expected_size_bytes": row.get("expected_size_bytes"),
        "final_size_bytes": row.get("final_size_bytes"),
        "status": row.get("status"),
        "failure_kind": row.get("failure_kind"),
        "error_message": row.get("error_message"),
        "checksum_sha256": row.get("checksum_sha256") or "",
        "created_at": row.get("created_at"),
        "terminal_at": row.get("terminal_at"),
    }


_PUBLIC_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _PUBLIC_SLUG_RE.fullmatch(slug):
        raise ValueError(
            "slug must be 2-63 characters: lowercase letters, digits and dashes"
        )
    return slug


class PublicationIn(BaseModel):
    """Publish or unpublish an object under a stable public slug.

    The slug is the permanent capability: it survives a content replacement, so
    course sites never have to be edited when a file is updated.
    """
    model_config = ConfigDict(extra="forbid")
    slug: str | None = Field(default=None, max_length=63)
    published: bool = True

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_slug(value)


class ReplaceObjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_object_id: Uuid4


_TAG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def _normalize_tags(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        tag = raw.strip().lower()
        if not tag:
            continue
        if not _TAG_RE.fullmatch(tag):
            raise ValueError(
                "tags must be 1-32 characters: lowercase letters, digits and dashes"
            )
        if tag not in out:
            out.append(tag)
    if len(out) > 20:
        raise ValueError("at most 20 tags per object")
    return out


class TagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)


class AudioClassificationEnqueueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = Field(default_factory=list, max_length=100)


class AudioClassificationEnqueueUnclassifiedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=100, ge=1, le=500)


class AudioClassificationReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "reject"]
    corrected_category: str | None = Field(default=None, max_length=64)
    corrected_themes: list[str] | None = None
    corrected_folder: str | None = Field(default=None, max_length=256)


class SubtitleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subtitle_object_id: Uuid4 | None = None


class CollectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=2, max_length=63)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str) -> str:
        return _normalize_slug(value)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class CollectionPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    published: bool | None = None


class CollectionItemsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[Uuid4] = Field(default_factory=list, max_length=500)


class ProgressIn(BaseModel):
    """Playback position posted by the public player (CSRF-protected).

    ``kind`` is advisory: the server decides ``start`` for a first sample or a
    backward seek, and only accepts ``end`` from the player. ``client_event_id``
    is an optional deduplication key for retried samples (#320).
    """
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)
    kind: Literal["start", "position", "end"] = "position"
    client_event_id: str = Field(default="", max_length=120)


class BookmarkIn(BaseModel):
    """A named position in a book, posted by the public player (CSRF-protected)."""
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)
    note: str = Field(default="", max_length=200)


class PlaylistIn(BaseModel):
    """A private playlist name (CSRF-protected)."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


from .routes_auth import LoginIn  # noqa: E402

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
    content_encoding: str | None = Field(default=None, max_length=16)
    # Optional client-generated UUID identifying one upload batch/session
    # (#246). It is carried to the terminal transfer journal only; no storage
    # key, URL or credential is derived from it. Omitted keeps the old shape.
    transfer_session_id: Uuid4 | None = None


class ShareIn(BaseModel):
    """Create a public read-only share link for one object.

    ``expires_in`` is optional but never unbounded: the server refuses anything
    above ``AURA_SHARE_TTL_MAX``. ``max_uses`` turns the link into a
    burn-after-N-read link.
    """
    model_config = ConfigDict(extra="forbid")
    expires_in: int | None = Field(default=None, ge=60)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    # `attachment` is the default so a share link downloads rather than renders.
    content_disposition: Literal["attachment", "inline"] = "attachment"


class FolderShareIn(BaseModel):
    """Create a public read-only link for a whole folder subtree.

    Bounded like an object share: ``expires_in`` is optional but never above
    ``AURA_SHARE_TTL_MAX``, and ``max_uses`` (when set) counts file downloads,
    not page views. Subfolders are always included.
    """
    model_config = ConfigDict(extra="forbid")
    expires_in: int | None = Field(default=None, ge=60)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)


from .routes_objects_mutations import ObjectPatchIn  # noqa: E402

class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _trim_name(value)


class SpaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: Uuid4
    name: str = Field(min_length=1, max_length=63)
    environment: str = Field(min_length=1, max_length=32)
    default_bucket: str | None = Field(default=None, max_length=63)

    @field_validator("name", "environment")
    @classmethod
    def _label(cls, value: str) -> str:
        return _trim_name(value)


class ApplicationPatchIn(BaseModel):
    # Partial update of an application (#M04). `name` is the only mutable label;
    # `status` carries activation/deactivation. `model_fields_set` tells "not
    # sent" apart from an explicit null (which is refused for both fields).
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=63)
    status: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _trim_name(value)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is not None and value not in APPLICATION_STATUSES:
            raise ValueError("invalid status")
        return value


class SpacePatchIn(BaseModel):
    # Controlled modification of a space (#M04). `application_id` is deliberately
    # absent: reassigning a space to another application would move every object,
    # bucket and identity to a different tenant, so it is not an editable field.
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=63)
    environment: str | None = Field(default=None, min_length=1, max_length=32)
    status: str | None = None

    @field_validator("name", "environment")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return None if value is None else _trim_name(value)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is not None and value not in SPACE_STATUSES:
            raise ValueError("invalid status")
        return value


class SpaceQuotasIn(BaseModel):
    """Monthly ceilings for one space. Explicit null clears a quota.

    Storage is enforced at upload intent. Egress is an estimate (issued intents
    and share redemptions), because AURA never proxies object bytes.
    """
    model_config = ConfigDict(extra="forbid")
    storage_bytes: int | None = Field(default=None, ge=0, le=10**15)
    egress_bytes_monthly: int | None = Field(default=None, ge=0, le=10**15)


class BucketIn(BaseModel):
    # Register an additional bucket for an existing space (#M04). The name is
    # validated against the S3 naming rules before it can be used by a client.
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _trim_name(value)


class BucketPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_default: bool


class IdentityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: Uuid4
    name: str = Field(min_length=1, max_length=63)
    scopes: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=1)


def _normalize_partner_url(value: str) -> str:
    """An https origin (optionally with a base path) and nothing else.

    The URL is documentation/metadata for operators, not an enforcement point,
    but it must be a copy-pasteable origin: no credentials, query or fragment,
    and no cleartext http.
    """
    parts = urlsplit(value.strip())
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("site_url must be an https origin without credentials, query or fragment")
    return f"https://{parts.netloc}{parts.path.rstrip('/')}"


class PartnerSiteIn(BaseModel):
    """Create a partner integration: metadata + its dedicated service identity.

    The identity is the credential (rotated/revoked through the identity routes);
    this row only records which external site consumes which space, and the TTL
    its media route should target. Scopes stay data-plane only.
    """
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)
    site_url: str = Field(min_length=8, max_length=255)
    space_id: Uuid4
    scopes: list[str] = Field(default_factory=lambda: [OBJECTS_READ])
    ttl_seconds: int | None = Field(default=None, ge=60)
    default_ttl_seconds: int | None = Field(default=None, ge=60, le=604_800)
    notes: str = Field(default="", max_length=2000)

    @field_validator("site_url")
    @classmethod
    def valid_site_url(cls, value: str) -> str:
        return _normalize_partner_url(value)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()


class PartnerSitePatchIn(BaseModel):
    """Edit the trust metadata. The identity and the space are not editable:
    moving a site to another space means a new identity and a new key."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=63)
    site_url: str | None = Field(default=None, min_length=8, max_length=255)
    default_ttl_seconds: int | None = Field(default=None, ge=60, le=604_800)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("site_url")
    @classmethod
    def valid_site_url(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_partner_url(value)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()


# --- Import jobs ----------------------------------------------------------

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


# Readiness probes are unauthenticated and may be polled aggressively: a
# list_buckets() per request is a free amplification vector against S3 and an
# existence oracle. Cache the verdict for a few seconds.
_READY_CACHE = {"at": 0.0, "ready": False}
_READY_TTL_S = 5
_READY_LOCK = threading.Lock()


@app.get("/health/ready")
def ready():
    now = time.time()
    with _READY_LOCK:
        if now - _READY_CACHE["at"] >= _READY_TTL_S:
            try:
                s3ops.list_buckets()
                _READY_CACHE.update(at=now, ready=True)
            except Exception:
                _READY_CACHE.update(at=now, ready=False)
        ok = _READY_CACHE["ready"]
    if not ok:  # never leak backend details
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# Diagnostic réseau (support)
# ---------------------------------------------------------------------------
# Mesure le chemin *réel* du navigateur vers Aura (TLS, Traefik, API), pas le
# lien de l'opérateur vers un serveur tiers. Rien n'est stocké, aucun corps
# n'est journalisé : ces routes ne servent qu'à compter des octets et du temps.
# Le plafond borne l'usage (un test = au plus 25 Mo dans chaque sens).

DIAG_MAX_BYTES = 25_000_000
DIAG_DEFAULT_DOWNLOAD = 10_000_000
DIAG_CHUNK = 64 * 1024


@app.get("/api/v1/diag/ping")
def diag_ping(principal: dict = Depends(authorize(None))):
    """Aller-retour minimal : le client en déduit RTT et gigue."""
    return JSONResponse(
        {"ts": int(time.time() * 1000)},
        headers={"Cache-Control": "no-store"},
    )


def _diag_random_stream(total: int):
    """Octets incompressibles : un proxy qui compresse ne fausse pas la mesure."""
    remaining = total
    while remaining > 0:
        size = min(DIAG_CHUNK, remaining)
        remaining -= size
        yield os.urandom(size)


@app.get("/api/v1/diag/download")
def diag_download(
    count: int = Query(DIAG_DEFAULT_DOWNLOAD, alias="bytes", ge=0),
    principal: dict = Depends(authorize(None)),
):
    """Flux de `bytes` octets aléatoires (plafonné), pour mesurer la descente."""
    total = max(1, min(int(count), DIAG_MAX_BYTES))
    return StreamingResponse(
        _diag_random_stream(total),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Encoding": "identity",
            "Content-Length": str(total),
        },
    )


@app.post("/api/v1/diag/upload")
async def diag_upload(request: Request, principal: dict = Depends(authorize(None))):
    """Consomme le corps en flux et renvoie le débit mesuré côté serveur.

    L'écart avec le débit vu par le navigateur dit s'il y a des octets perdus
    en route (transit, proxy) ou un simple bridage de l'uplink.
    """
    started = time.perf_counter()
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > DIAG_MAX_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
    elapsed = time.perf_counter() - started
    duration_ms = max(0, int(elapsed * 1000))
    return JSONResponse(
        {
            "bytes": total,
            "duration_ms": duration_ms,
            "bytes_per_second": int(total / elapsed) if elapsed > 0 else 0,
        },
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Public share links
# ---------------------------------------------------------------------------
# Outside /api/v1 on purpose: this is the only unauthenticated route that serves
# object data, and it must not be confused with the session/Bearer API surface.
# It never returns bytes: it redirects to a short-lived presigned GET.
def _share_not_found() -> HTTPException:
    """One indistinguishable 404 for every share failure mode.

    A factory rather than a shared instance: the same object raised from several
    concurrent requests would carry competing tracebacks.
    """
    return HTTPException(status_code=404, detail="not found")




# ---------------------------------------------------------------------------
# Public folder share links
# ---------------------------------------------------------------------------
# Same capability model as /s/<token>, but a folder is a tree: the link serves a
# no-JavaScript listing and each file redirects to a short-lived presigned GET.
# No object bytes ever pass through the API; every link stays relative to the
# token path, so the page never needs the request Host header.
def _public_page_headers() -> dict:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
        # The page has no scripts, no forms and no external assets. Everything it
        # needs is inline CSS, so a share can never run code in the app's origin.
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        ),
    }


def _resolve_folder_share(token: str):
    """Return ``(share_row, folder_row, reason)``; reason None means usable.

    The same shape check and fingerprint lookup as an object share, then the
    owning folder. The folder lookup is owner-scoped through ``created_by``: the
    creator is always the folder owner (folder routes are owner-scoped), and a
    row that disagrees is treated as missing rather than trusted.
    """
    if not shares.is_well_formed(token):
        return None, None, "unknown"
    found = repo.get_folder_share_by_token_hash(shares.fingerprint(token))
    if found is None:
        return None, None, "unknown"
    row = _as_dict(found)
    if row.get("revoked_at"):
        return row, None, "revoked"
    if int(row["expires_at"]) <= int(time.time()):
        return row, None, "expired"
    max_uses = row["max_uses"]
    if max_uses is not None and int(row["use_count"]) >= int(max_uses):
        return row, None, "exhausted"
    folder = repo.get_folder(row["folder_id"], owner_id=row["created_by"])
    if folder is None:
        return row, None, "folder_missing"
    # Tenant attribution for the audit trail: redemption has no principal, but
    # the event still belongs to the shared folder's space.
    set_request_principal(row["space_id"], None)
    return row, _as_dict(folder), None


def _folder_share_denied(reason: str, row: dict | None = None) -> HTMLResponse:
    """One indistinguishable 404 page for every folder-link failure mode."""
    extra: dict = {"reason": reason}
    if row is not None:
        extra["folder_share_id"] = row["id"]
        extra["folder_id"] = row["folder_id"]
    audit_event("folder-share-access", None, "denied", extra)
    return HTMLResponse(
        folder_shares.render_not_found(),
        status_code=404,
        headers=_public_page_headers(),
    )


@app.get("/f/{token}")
def view_folder_share(
    token: str,
    d: str | None = None,
    page: int = Query(default=0, ge=0, le=1000),
):
    """Render the public listing for a folder link, or the uniform 404 page.

    ``d`` navigates inside the subtree; any id that is not the shared folder or
    one of its descendants answers 404, so the link cannot be used to crawl the
    rest of the owner's tree.
    """
    row, folder, reason = _resolve_folder_share(token)
    if row is None or folder is None:
        return _folder_share_denied(reason or "unknown", row)

    owner_id = folder["owner_id"]
    root_id = folder["id"]
    current_id = root_id
    if d is not None:
        canonical = ids.canonical(d)
        if canonical is None or not folder_shares.folder_in_subtree(
            repo, canonical, root_id, owner_id
        ):
            return _folder_share_denied("outside_share", row)
        current_id = canonical

    chain = folder_shares.folder_path(repo, current_id, root_id, owner_id)
    if chain is None:
        return _folder_share_denied("outside_share", row)

    folders = [
        _as_dict(f)
        for f in repo.list_folders(owner_id=owner_id, parent_id=current_id)
    ]
    # One extra row tells us whether a next page exists without a COUNT.
    rows = repo.list_objects(
        space_id=row["space_id"], owner_id=owner_id, folder_id=current_id,
        status=AVAILABLE, sort="display_name", order="asc",
        limit=folder_shares.PAGE_SIZE + 1, offset=page * folder_shares.PAGE_SIZE,
    )
    objects = [_as_dict(o) for o in rows[: folder_shares.PAGE_SIZE]]
    has_next = len(rows) > folder_shares.PAGE_SIZE

    audit_event("folder-share-open", None, "success", {
        "folder_share_id": row["id"], "folder_id": current_id,
        "page": page, "folders": len(folders), "files": len(objects),
    })
    return HTMLResponse(
        folder_shares.render_page(
            token=token, folder=folder, chain=chain, folders=folders,
            objects=objects, page=page, has_next=has_next,
            expires_at=int(row["expires_at"]), now=int(time.time()),
            inline_allowed=shares.inline_allowed,
        ),
        headers=_public_page_headers(),
    )


@app.get("/f/{token}/o/{oid}")
def redeem_folder_share_object(
    token: str, oid: str, request: Request, download: bool = False,
):
    """Redirect one file of a folder share to a presigned GET, or 404.

    The object must be ``available`` and filed inside the shared subtree. Every
    download consumes one use of ``max_uses``; page views do not. ``download=1``
    forces an attachment, otherwise safe types open inline (never HTML/SVG).
    """
    row, folder, reason = _resolve_folder_share(token)
    if row is None or folder is None:
        return _folder_share_denied(reason or "unknown", row)

    canonical = ids.canonical(oid)
    if canonical is None:
        return _folder_share_denied("object_unavailable", row)
    target = repo.get_object(
        canonical, space_id=row["space_id"], owner_id=folder["owner_id"]
    )
    if target is None or target["status"] != AVAILABLE:
        return _folder_share_denied("object_unavailable", row)
    obj = _as_dict(target)
    if not folder_shares.folder_in_subtree(
        repo, obj["folder_id"], folder["id"], folder["owner_id"]
    ):
        # An object outside the shared tree must look exactly like a missing one.
        return _folder_share_denied("outside_share", row)

    # A folder link must not distribute published books outside the paid gate:
    # the same rule as /s/{token} and /d/{slug}. Keep the uniform 404 page.
    if settings.public_download_require_premium and obj.get("published_at"):
        try:
            _require_premium(request)
        except HTTPException:
            return _folder_share_denied("premium_required", row)

    try:
        _check_egress_quota(row["space_id"], int(obj["size_bytes"]))
    except HTTPException:
        return _folder_share_denied("egress_quota", row)

    now = int(time.time())
    if not repo.consume_folder_share(row["id"], now):
        return _folder_share_denied("exhausted", row)

    inline = shares.inline_allowed(obj["content_type"])
    disposition = "attachment" if download or not inline else "inline"
    url = presigned_get(
        s3, obj["bucket"], obj["object_key"], settings.share_presign_ttl,
        content_disposition=shares.content_disposition_header(
            disposition, obj["display_name"]
        ),
        content_type=obj["content_type"],
    )
    _record_egress(row["space_id"], int(obj["size_bytes"]), "share")
    _record_object_event(obj["id"], int(obj["size_bytes"]), "share")
    audit_event("folder-share-access", None, "success", {
        "folder_share_id": row["id"], "folder_id": obj["folder_id"],
        "object_id": obj["id"], "use_count": int(row["use_count"]) + 1,
        "content_disposition": disposition,
    })
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
    })


from .routes_auth import router as auth_router  # noqa: E402
app.include_router(auth_router)


# ---------------------------------------------------------------------------
# Public portal: Google sign-in on a dedicated subdomain.
#
# The portal never uses the admin cookie and never gets an object capability.
# Its role is absent from ROLE_SCOPES (default-deny), and the only routes on the
# public host are the HTML root and /api/public/* (see docker-compose.yml).
# ---------------------------------------------------------------------------
_PUBLIC_OAUTH_COOKIE = "aura_public_oauth"


def _public_host_ok(request: Request) -> bool:
    configured = (settings.public_domain or "").lower()
    if not configured:
        return True  # dev/tests: no public domain configured
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    return host == configured


def _public_auth_failed(request: Request, reason: str) -> JSONResponse:
    # The reason goes to the audit log only; the client gets one generic error.
    _public_login_record_failure(_client_ip(request))
    audit_event("google-login", None, "failure", {"reason": reason})
    out = JSONResponse(
        {"detail": "google sign-in failed"}, status_code=401,
        headers={"Cache-Control": "no-store"},
    )
    out.delete_cookie(_PUBLIC_OAUTH_COOKIE, path="/api/public/auth")
    return out


@app.get("/api/public/auth/google")
def public_auth_google(request: Request):
    """Start Google sign-in with a one-time state and PKCE verifier."""
    if not google_oauth.is_configured():
        raise HTTPException(status_code=503, detail="public portal not configured")
    if _public_login_blocked(_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="too many login attempts",
            headers={"Retry-After": str(settings.login_rate_window)},
        )
    state = new_token(32)
    verifier, challenge = google_oauth.new_pkce()
    out = RedirectResponse(
        google_oauth.authorization_url(state, challenge), status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                 "X-Content-Type-Options": "nosniff"},
    )
    out.set_cookie(
        _PUBLIC_OAUTH_COOKIE, f"{state}.{verifier}", httponly=True,
        secure=settings.cookie_secure, samesite="lax", max_age=600,
        path="/api/public/auth",
    )
    return out


@app.get("/api/public/auth/callback")
def public_auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Verify Google's answer, create the portal user and set its own cookie."""
    if not google_oauth.is_configured():
        raise HTTPException(status_code=503, detail="public portal not configured")
    if _public_login_blocked(_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="too many login attempts",
            headers={"Retry-After": str(settings.login_rate_window)},
        )
    raw = request.cookies.get(_PUBLIC_OAUTH_COOKIE, "")
    expected_state, sep, verifier = raw.partition(".")
    if not sep or not state or not secrets.compare_digest(str(state), str(expected_state)):
        return _public_auth_failed(request, "bad_state")
    if error or not code or len(code) > 512:
        return _public_auth_failed(request, "provider_error")
    try:
        tokens = google_oauth.exchange_code(code, verifier)
        claims = google_oauth.verify_id_token(tokens["id_token"])
    except google_oauth.OAuthError as exc:
        return _public_auth_failed(request, str(exc))
    email = str(claims["email"]).strip().lower()
    allowed = settings.google_allowed_email_domains
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        return _public_auth_failed(request, "domain_not_allowed")

    subject = str(claims["sub"])
    user = repo.get_user_by_oauth("google", subject)
    if user is None:
        # A visitor who first signed in with an e-mailed link keeps that account
        # (favourites, progress) when they later use Google with the same verified
        # address. Only accounts created by e-mail link are reused: two different
        # Google identities are never merged on a shared address.
        candidate = repo.get_public_user_by_email(email)
        if candidate is not None and candidate["oauth_provider"] == "email":
            user = candidate
    plan = _public_plan_for_email(email)
    if user is None:
        # The username is derived from the stable subject, never from the email
        # (which can change) or from a Google display name (which is user data).
        suffix = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
        username = f"google-{suffix}"
        # Passwords are never used by these accounts: store an argon2 hash of a
        # random secret so the NOT NULL column cannot become a login path.
        from .auth import hash_password
        user_id = repo.create_oauth_user(
            username, hash_password(new_token(32)), "google", subject, email,
            role=PUBLIC_ROLE, plan=plan,
        )
    else:
        user_id = user["id"]
        if plan == "premium" and str(_row_get(user, "plan") or "free").lower() != "premium":
            repo.set_user_plan(user_id, "premium")

    return _public_login_response(user_id, request, "google-login", clear_oauth_cookie=True)


def _public_login_response(
    user_id: str, request: Request, event: str, clear_oauth_cookie: bool = False,
) -> RedirectResponse:
    """Open a public session for ``user_id`` and redirect to the catalogue."""
    csrf = new_token(16)
    sid = repo.create_session(
        user_id, csrf, int(time.time()) + settings.public_session_ttl
    )
    _public_login_clear(_client_ip(request))
    audit_event(event, user_id, "success", {"user_id": user_id})
    out = RedirectResponse("/", status_code=302, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex, nofollow",
    })
    out.set_cookie(
        settings.public_session_cookie, sid, httponly=True,
        secure=settings.cookie_secure, samesite="lax",
        max_age=settings.public_session_ttl, path="/",
    )
    if clear_oauth_cookie:
        out.delete_cookie(_PUBLIC_OAUTH_COOKIE, path="/api/public/auth")
    return out


# ---------------------------------------------------------------------------
# E-mail sign-in link for visitors without a Google account.
# 1) POST the address -> always the same answer (no account enumeration), the
#    mail is sent in the background. 2) The mailed link only opens a page with a
#    button: mail scanners that pre-fetch links must not burn the single-use token.
# 3) POST the token from that page -> session cookie.
# ---------------------------------------------------------------------------
_EMAIL_LINK_PER_IP = 10        # requests per client and hour
_EMAIL_LINK_PER_ADDRESS = 3    # mails per address and hour


def _same_origin_post(request: Request) -> bool:
    """Browsers always send Origin/Referer on a POST: refuse another site's form."""
    source = request.headers.get("origin") or request.headers.get("referer") or ""
    if not source:
        return True  # not a browser; the single-use token is the protection
    return urlsplit(source).hostname == (settings.public_domain or "")


def _email_login_open(request: Request) -> bool:
    return _public_host_ok(request) and magic_link.enabled(settings)


def _email_domain_allowed(email: str) -> bool:
    allowed = settings.google_allowed_email_domains
    return not allowed or email.rsplit("@", 1)[-1] in allowed


def _send_login_email(email: str, link: str) -> None:
    try:
        magic_link.send(settings, email, link)
    except Exception as exc:  # SMTP down/misconfigured: log, never tell the visitor
        audit_event("email-link", "system", "send_failed", {"error": type(exc).__name__})


@app.post("/api/public/auth/email", response_class=HTMLResponse)
async def public_email_link_request(request: Request, background: BackgroundTasks):
    if not _email_login_open(request):
        raise HTTPException(status_code=404, detail="not found")
    if not _same_origin_post(request):
        raise HTTPException(status_code=403, detail="cross-site request")
    _public_rate_hit(f"email-ip:{_client_ip(request)}", _EMAIL_LINK_PER_IP, 3600)
    form = await request.form()
    email = magic_link.normalize_email(str(form.get("email") or ""))
    who = hashlib.sha256((email or "-").encode("utf-8")).hexdigest()[:12]
    if (
        email and _email_domain_allowed(email)
        and _public_rate_hit(f"email-addr:{email}", _EMAIL_LINK_PER_ADDRESS, 3600, raise_429=False)
    ):
        token = magic_link.new_token()
        now = int(time.time())
        repo.create_login_link(magic_link.hash_token(token), email, now, now + settings.email_link_ttl)
        background.add_task(
            _send_login_email, email, f"{_public_base_url()}/connexion/lien?token={token}",
        )
        audit_event("email-link", who, "requested")
    else:
        audit_event("email-link", who, "ignored")
    return HTMLResponse(
        public_book.message_page(
            "Vérifiez votre boîte mail",
            "Si cette adresse est valide, un lien de connexion vient de lui être envoyé. "
            f"Il est valable {max(1, settings.email_link_ttl // 60)} minutes.",
        ),
        headers=_public_profile_headers(),
    )


@app.get("/connexion/lien", response_class=HTMLResponse)
def public_email_link_open(request: Request, token: str = ""):
    if not _email_login_open(request):
        raise HTTPException(status_code=404, detail="not found")
    headers = _public_profile_headers()
    if len(token) > 200 or not repo.peek_login_link(magic_link.hash_token(token), int(time.time())):
        return HTMLResponse(
            public_book.message_page(
                "Lien expiré", "Ce lien a déjà été utilisé ou a expiré. Demandez-en un nouveau.",
            ),
            status_code=400, headers=headers,
        )
    return HTMLResponse(public_book.confirm_login_page(token), headers=headers)


@app.post("/api/public/auth/email/confirm")
async def public_email_link_confirm(request: Request):
    if not _email_login_open(request):
        raise HTTPException(status_code=404, detail="not found")
    if not _same_origin_post(request):
        raise HTTPException(status_code=403, detail="cross-site request")
    client_ip = _client_ip(request)
    if _public_login_blocked(client_ip):
        raise HTTPException(status_code=429, detail="too many login attempts",
                            headers={"Retry-After": str(settings.login_rate_window)})
    form = await request.form()
    token = str(form.get("token") or "")[:200]
    email = repo.consume_login_link(magic_link.hash_token(token), int(time.time())) if token else None
    if email is None or not _email_domain_allowed(email):
        _public_login_record_failure(client_ip)
        audit_event("email-login", "-", "failure")
        return HTMLResponse(
            public_book.message_page(
                "Lien expiré", "Ce lien a déjà été utilisé ou a expiré. Demandez-en un nouveau.",
            ),
            status_code=400, headers=_public_profile_headers(),
        )
    user = repo.get_user_by_oauth("email", email) or repo.get_public_user_by_email(email)
    plan = _public_plan_for_email(email)
    if user is None:
        from .auth import hash_password
        suffix = hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]
        user_id = repo.create_oauth_user(
            f"email-{suffix}", hash_password(new_token(32)), "email", email, email,
            role=PUBLIC_ROLE, plan=plan,
        )
    else:
        user_id = user["id"]
        if plan == "premium" and str(_row_get(user, "plan") or "free").lower() != "premium":
            repo.set_user_plan(user_id, "premium")
    return _public_login_response(user_id, request, "email-login")


class PublicProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=80)


def _clean_display_name(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "") if ch.isprintable()).strip()
    return cleaned[:80]










def _portal_csp() -> str:
    """Content-Security-Policy of the public portal pages.

    Scripts and styles are same-origin files (api/portal_assets), so no inline
    script or <style> is allowed. Audio and covers are 302-redirected to the S3
    host, which therefore has to be allowed for media and images. Inline style
    *attributes* stay allowed (server-computed cover hue and progress width).
    """
    parts = urlsplit(settings.s3_endpoint or "")
    s3 = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    media = f"'self' {s3}".strip()
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "style-src-attr 'unsafe-inline'; "
        f"img-src {media}; media-src {media}; connect-src {media}; "
        "manifest-src 'self'; worker-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


def _public_profile_headers(indexable: bool = False) -> dict:
    """Headers of every portal HTML page; only browse pages may be indexed."""
    headers = {
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": _portal_csp(),
    }
    if indexable:
        # Same content for every anonymous visitor: cacheable for a minute.
        headers["Cache-Control"] = "public, max-age=60"
        headers["Vary"] = "Cookie"
    else:
        # Personalised HTML (CSRF token, favourites, shelves) must never be
        # reused by another visitor — not even by a shared proxy.
        headers["Cache-Control"] = "private, no-store"
        headers["Vary"] = "Cookie"
        headers["X-Robots-Tag"] = "noindex, nofollow"
    return headers


@app.exception_handler(StarletteHTTPException)
async def _portal_html_not_found(request: Request, exc: StarletteHTTPException):
    """A visitor who mistypes a portal address gets a page, not a JSON error."""
    if (
        exc.status_code == 404 and settings.public_domain and _public_host_ok(request)
        and "text/html" in request.headers.get("accept", "")
        and not request.url.path.startswith("/api/")
    ):
        return HTMLResponse(
            public_book.message_page("Page introuvable", "Cette adresse n'existe pas ou n'est plus disponible."),
            status_code=404, headers=_public_profile_headers(),
        )
    return await http_exception_handler(request, exc)


@app.get("/sw.js")
def portal_service_worker(request: Request):
    """Service worker: must live at the root to control every portal page."""
    if not _public_host_ok(request) or not settings.public_domain:
        raise HTTPException(status_code=404, detail="not found")
    return Response(
        public_ui.ASSETS["sw.js"][0], media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-cache", "Service-Worker-Allowed": "/",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/hors-ligne", response_class=HTMLResponse)
def portal_offline_page(request: Request):
    """Shown by the service worker when a page is needed and there is no network."""
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    return HTMLResponse(
        public_book.message_page(
            "Vous êtes hors connexion",
            "Cette page n'a pas été enregistrée sur cet appareil. Les livres téléchargés "
            "restent lisibles : rouvrez la bibliothèque depuis la page d'accueil.",
        ),
        headers=_public_profile_headers(),
    )


@app.get("/portal-assets/{name}")
def portal_asset(name: str, request: Request):
    """Stylesheet and scripts of the portal, versioned by content hash."""
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    asset = public_ui.ASSETS.get(name)
    if asset is None:
        raise HTTPException(status_code=404, detail="not found")
    data, content_type, version = asset
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff", "ETag": f'"{version}"',
    }
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=content_type, headers=headers)


@app.get("/profil", response_class=HTMLResponse)
def public_profile(request: Request):
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    try:
        principal = authenticate_public(request)
    except HTTPException:
        return RedirectResponse("/", status_code=302)
    headers = _public_profile_headers()
    return HTMLResponse(
        public_ui.profile_page(
            principal,
            playlists=repo.list_listen_playlists(principal["id"]),
            stats=_public_listening_stats(principal),
        ),
        headers=headers,
    )


@app.post("/profil", response_class=HTMLResponse)
async def public_profile_update(request: Request, principal: dict = Depends(require_public)):
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    form = await request.form()
    display_name = _clean_display_name(str(form.get("display_name") or ""))
    repo.update_user_display_name(principal["id"], display_name)
    principal = {**principal, "display_name": display_name}
    audit_event("public-profile", principal["id"], "success", {"action": "update"})
    headers = _public_profile_headers()
    return HTMLResponse(
        public_ui.profile_page(principal, message="Profil mis à jour."),
        headers=headers,
    )


@app.post("/profil/supprimer")
async def public_profile_delete(request: Request, principal: dict = Depends(require_public)):
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    uid = principal["id"]
    repo.delete_public_account(uid)
    audit_event("public-account-delete", uid, "success")
    out = RedirectResponse("/", status_code=303)
    out.delete_cookie(
        settings.public_session_cookie, path="/", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return out


def _split_audio_name(display_name: str) -> tuple[str, str]:
    """Split `Auteur - Titre.ext` into (author, title) when possible."""
    stem = display_name.rsplit(".", 1)[0] if "." in display_name else display_name
    if " - " in stem:
        author, title = stem.split(" - ", 1)
        author, title = author.strip(), title.strip()
        # `06 - Titre` is an episode number, not an author.
        if author.isdigit():
            return "", title
        return author, title
    # `001_Titre` and `06 - Titre` fall back to a clean, unnumbered title.
    stem = re.sub(r"^\d{1,3}\s*[-_]\s*", "", stem)
    return "", stem.replace("_", " ").strip()


def _folder_names(folder_ids: list[str]) -> dict:
    ids = list({fid for fid in folder_ids if fid})
    if not ids:
        return {}
    mark = "?" if settings.db_backend == "sqlite" else "%s"
    placeholders = ",".join(mark for _ in ids)
    rows = repo.conn.execute(
        f"SELECT id, name FROM folders WHERE id IN ({placeholders})", tuple(ids),
    ).fetchall()
    return {r["id"]: r["name"] for r in rows}


def _library_items(col: dict, only_published: bool = False) -> list:
    """Items of a published pack, with their public media URL when available."""
    rows = []
    for pos, row in enumerate(repo.get_collection_items(col["id"])):
        row = _as_dict(row)
        if row["status"] != AVAILABLE:
            continue
        published = bool(row.get("published_at") and row.get("public_slug"))
        if only_published and not published:
            continue
        rows.append((pos, row, published))
    # One query for every chapter and folder name instead of one per book.
    chapters = repo.get_audio_chapters_map([row["id"] for _, row, _ in rows])
    folder_names = _folder_names([row.get("folder_id") for _, row, _ in rows])
    items = []
    for pos, row, published in rows:
        author, title = _split_audio_name(row["display_name"])
        items.append({
            "position": pos,
            "id": row["id"],
            "display_name": row["display_name"],
            "title": title,
            "author": author,
            "series": public_series.series_for_folder(
                folder_names.get(row.get("folder_id"), "")
            ),
            "created_at": row.get("created_at"),
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
            "duration_seconds": row.get("duration_seconds"),
            "chapters": chapters.get(row["id"], []),
            "published_slug": row.get("public_slug"),
            "cover_url": f"/covers/{row['id']}.jpg" if row.get("cover_key") else None,
            "emblematic_cover": bool(row.get("emblematic_cover")),
            "url": f"/m/{row['public_slug']}" if published else None,
            "subtitle_url": (
                f"/m/{row['public_slug']}/subtitles.vtt"
                if published and row.get("subtitle_object_id") else None
            ),
        })
    return items


def _attach_public_facets(collections: list) -> list:
    """Attach only approved public facets, loading tags in bounded batches."""
    object_ids = list({
        item["id"] for col in collections for item in col.get("items", [])
    })
    tags_by_object: dict[str, list[str]] = {}
    for start in range(0, len(object_ids), 500):
        tags_by_object.update(repo.list_tags_for_objects(object_ids[start:start + 500]))
    for col in collections:
        col["items"] = [
            public_facets.enrich_public_item(item, tags_by_object.get(item["id"], []))
            for item in col.get("items", [])
        ]
    return collections


def _public_catalog() -> list:
    """Published catalogue, identical for every visitor (no listening position)."""
    collections = []
    for col in repo.list_published_collections():
        col = _as_dict(col)
        collections.append({
            "slug": col["slug"], "title": col["title"],
            "description": col.get("description") or "",
            "updated_at": col["updated_at"],
            "items": _library_items(col, only_published=True),
        })
    return _attach_public_facets(collections)


def _public_collections(principal: dict) -> list:
    """Published catalogue with each visitor's own listening position."""
    collections = _public_catalog()
    object_ids = [item["id"] for col in collections for item in col["items"]]
    progress = repo.get_progress_map(principal["id"], object_ids)
    favorites = repo.get_favorite_ids(principal["id"], object_ids)
    for col in collections:
        for item in col["items"]:
            item["progress_seconds"] = progress.get(item["id"], 0)
            item["favorite"] = item["id"] in favorites
    return collections


def _filter_collections(
    collections: list, query: str, author: str, sort: str = "",
    *, min_seconds: int | None = None, max_seconds: int | None = None,
    collection: str = "", category: str = "", theme: str = "",
    language: str = "", media_format: str = "",
) -> list:
    """Search and combine public facets with AND semantics."""
    # Query and indexed text share the same canonicalisation, so « polar »
    # finds a book tagged « thriller » while unknown words keep plain matching.
    from . import portal_search
    words = portal_search.search_tokens(query)
    raw_format = (media_format or "").strip().lower()
    wanted_format = public_facets.normalize_format(raw_format, unknown=raw_format) if raw_format else ""
    wanted_author = public_ui.fold(author) if author else ""
    out = []
    for col in collections:
        if collection and col.get("slug") != collection:
            continue
        prepared = []
        for item in col["items"]:
            facets = public_facets.item_facets(item)
            searchable = portal_search.canonicalize(
                f'{item.get("display_name", "")} {item.get("author", "")} '
                f'{item.get("title", "")} {" ".join(facets["categories"])} '
                f'{" ".join(facets["themes"])}'
            )
            prepared.append((item, facets, searchable, float(item.get("duration_seconds") or 0)))
        items = [
            item for item, facets, searchable, duration in prepared
            if (not words or all(word in searchable for word in words))
            and (not wanted_author or public_ui.fold(item.get("author", "")) == wanted_author)
            and (not category or category in facets["categories"])
            and (not theme or theme in facets["themes"])
            and (not language or language in facets["languages"])
            and (not wanted_format or facets["format"] == wanted_format)
            and (
                (min_seconds is None and max_seconds is None)
                or (
                    duration > 0
                    and (min_seconds is None or duration >= min_seconds)
                    and (max_seconds is None or duration <= max_seconds)
                )
            )
        ]
        if items:
            out.append({**col, "items": public_ui.sort_items(items, sort)})
    return out


def _sort_param(request: Request) -> str:
    value = (request.query_params.get("tri") or "").strip().lower()
    return value if value in {v for _, v in public_ui.SORTS} else ""


def _catalog_filter_state(request: Request, intent) -> tuple[dict, dict, str]:
    """Parse explicit URL facets; explicit duration bounds override NLP ones."""
    params = request.query_params
    raw_format = (params.get("format") or "").strip().lower()
    active = {
        "collection": (params.get("collection") or "").strip()[:120],
        "category": (params.get("categorie") or "").strip().lower()[:64],
        "theme": (params.get("theme") or "").strip().lower()[:64],
        "language": (params.get("langue") or "").strip().lower()[:16],
        "format": public_facets.normalize_format(raw_format, unknown=raw_format)[:32],
        "duration_min": (params.get("duree_min") or "").strip()[:6],
        "duration_max": (params.get("duree_max") or "").strip()[:6],
    }
    error = ""
    try:
        explicit_min = public_facets.minutes_to_seconds(active["duration_min"])
        explicit_max = public_facets.minutes_to_seconds(active["duration_max"])
        min_seconds = explicit_min if active["duration_min"] else intent.min_seconds
        max_seconds = explicit_max if active["duration_max"] else intent.max_seconds
        # The form works in whole minutes. Round NLP-derived bounds down before
        # filtering so submitting the form later cannot silently change results.
        if not active["duration_min"] and min_seconds is not None:
            min_seconds = (min_seconds // 60) * 60
        if not active["duration_max"] and max_seconds is not None:
            max_seconds = (max_seconds // 60) * 60
        if min_seconds is not None and max_seconds is not None and min_seconds > max_seconds:
            raise ValueError("duration")
    except ValueError:
        min_seconds = max_seconds = None
        error = "Durée invalide : indiquez des minutes entières et une borne minimale inférieure à la maximale."
    if not active["duration_min"] and min_seconds is not None:
        active["duration_min"] = str(min_seconds // 60)
    if not active["duration_max"] and max_seconds is not None:
        active["duration_max"] = str(max_seconds // 60)
    return active, {"min_seconds": min_seconds, "max_seconds": max_seconds}, error


def _catalog_authors(collections: list) -> list:
    return sorted({i["author"] for col in collections for i in col["items"] if i["author"]})


def _catalog_author_counts(collections: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in public_facets.unique_items(collections):
        author = str(item.get("author") or "").strip()
        if author:
            counts[author] = counts.get(author, 0) + 1
    return counts






_BOOKMARKS_PER_BOOK = 50


def _published_book_or_404(oid: str) -> str:
    oid = _canonical_id(oid, "object id")
    row = repo.get_object_unscoped(oid)
    row = _as_dict(row) if row is not None else None
    if row is None or not row.get("published_at") or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="object not found")
    return oid










def _set_public_favorite(oid: str, request: Request, principal: dict, favorite: bool) -> dict:
    _public_rate_check("progress", request)
    oid = _canonical_id(oid, "object id")
    row = repo.get_object_unscoped(oid)
    row = _as_dict(row) if row is not None else None
    if row is None or not row.get("published_at") or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="object not found")
    repo.set_favorite(principal["id"], oid, favorite, int(time.time()))
    return {"object_id": oid, "favorite": favorite}






# --- Private playlists (#302) -------------------------------------------
def _own_playlist_or_404(pid: str, principal: dict) -> dict:
    playlist = repo.get_listen_playlist(principal["id"], _canonical_id(pid, "playlist id"))
    if playlist is None:
        raise HTTPException(status_code=404, detail="playlist not found")
    return playlist


@app.post("/api/public/playlists/create")
async def public_playlist_create_form(
    request: Request, principal: dict = Depends(require_public),
):
    """No-JavaScript form variant used by the profile page."""
    form = await request.form()
    name = " ".join(str(form.get("name") or "").split())[:80]
    if name:
        repo.create_listen_playlist(principal["id"], name, int(time.time()))
    return RedirectResponse("/profil", status_code=303)


@app.post("/api/public/playlists/{pid}/delete")
async def public_playlist_delete_form(
    pid: str, request: Request, principal: dict = Depends(require_public),
):
    playlist = repo.get_listen_playlist(principal["id"], _canonical_id(pid, "playlist id"))
    if playlist is not None:
        repo.delete_listen_playlist(principal["id"], playlist["id"])
    return RedirectResponse("/profil", status_code=303)


def _public_listening_stats(principal: dict) -> dict:
    """Listener stats: a measured projection plus the legacy estimate.

    ``estimated_listened_seconds`` still sums the latest saved positions for
    compatibility, but it is only an estimate. ``measured_listened_seconds``
    sums the capped deltas of the append-only events (#320) within the retention
    window; the profile labels whichever figure it displays accordingly.
    """
    collections = _public_collections(principal)
    items = [item for col in collections for item in col["items"]]
    progress = repo.get_progress_map(principal["id"], [item["id"] for item in items])
    positions = {item["id"]: float(progress.get(item["id"], 0)) for item in items}
    listened = sum(positions.values())
    completed = sum(
        1 for item in items
        if item.get("duration_seconds")
        and positions[item["id"]] >= 0.9 * float(item["duration_seconds"])
    )
    favourites = [item for item in items if item.get("favorite")]
    bookmarks = sum(len(repo.list_bookmarks(principal["id"], item["id"])) for item in items)
    authors: dict[str, int] = {}
    for item in favourites:
        author = str(item.get("author") or "").strip()
        if author:
            authors[author] = authors.get(author, 0) + 1
    series = []
    for col in collections:
        col_items = col.get("items", [])
        started = [i for i in col_items if positions.get(i["id"], 0) > 0]
        if len(col_items) > 1 and started:
            series.append({
                "title": col.get("title") or "Bibliothèque",
                "started": len(started),
                "total": len(col_items),
            })
    totals = repo.listening_totals(
        principal["id"], int(time.time()),
        settings.listen_event_retention_days * 86400,
    )
    return {
        "items_in_library": len(items),
        "estimated_listened_seconds": int(listened),
        "measured_listened_seconds": totals["listened_seconds"],
        "listen_events": totals["samples"],
        "completed": completed,
        "favorites": len(favourites),
        "bookmarks": bookmarks,
        "top_authors": [
            {"name": name, "count": count}
            for name, count in sorted(authors.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        ],
        "series_in_progress": series[:5],
    }


















@app.get("/", response_class=HTMLResponse)
def public_portal(request: Request):
    """Catalogue page with a single audio player, served on the public host.

    Anonymous visitors get a sign-in page instead of a JSON 401: the portal is
    the browser entry point, while /api/public/* stays strictly authenticated.
    """
    if not _public_host_ok(request):
        raise HTTPException(status_code=404, detail="not found")
    try:
        principal = authenticate_public(request)
    except HTTPException:
        principal = None
    query = (request.query_params.get("q") or "").strip()[:120]
    author = (request.query_params.get("auteur") or "").strip()[:120]
    sort = _sort_param(request)
    # Natural-language queries are translated into the portal's existing
    # filters; the "search" limiter bounds how often one client can ask.
    from . import portal_search
    intent = portal_search.parse_search(query) if query else portal_search.SearchIntent()
    search_note = ""
    if intent.recognised:
        _public_rate_check("search", request)
        search_note = intent.explanation
        query = intent.q
        author = author or intent.author
        sort = sort or intent.sort
    active_facets, duration_filters, filter_error = _catalog_filter_state(request, intent)
    if principal is None:
        if not settings.public_browse:
            return HTMLResponse(
                public_ui.login_page(with_email=magic_link.enabled(settings)),
                headers=_public_profile_headers(),
            )
        catalog = _public_catalog()
        facet_options = public_facets.catalog_facets(catalog)
        filtered = _filter_collections(
            catalog, query, author, sort, **duration_filters,
            collection=active_facets["collection"],
            category=active_facets["category"],
            theme=active_facets["theme"],
            language=active_facets["language"],
            media_format=active_facets["format"],
        )
        filters_active = bool(
            query or author or sort or filter_error or
            duration_filters["min_seconds"] is not None or
            duration_filters["max_seconds"] is not None or
            any(active_facets[key] for key in (
                "collection", "category", "theme", "language", "format",
                "duration_min", "duration_max",
            ))
        )
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        return HTMLResponse(
            public_book.landing_page(
                filtered, query=query, search_note=search_note,
                authors=_catalog_authors(catalog), active_author=author, sort=sort,
                author_counts=_catalog_author_counts(catalog),
                facet_options=facet_options, active_facets=active_facets,
                filter_error=filter_error,
                base_url=_public_base_url(), with_email=magic_link.enabled(settings),
                page=page,
            ),
            headers=_public_profile_headers(indexable=not filters_active),
        )
    view = request.query_params.get("vue", "grille").strip().lower()
    if view not in ("liste", "grille", "immersif"):
        view = "liste"
    collections = _public_collections(principal)
    authors = _catalog_authors(collections)
    author_counts = _catalog_author_counts(collections)
    facet_options = public_facets.catalog_facets(collections)
    collections = _filter_collections(
        collections, query, author, sort, **duration_filters,
        collection=active_facets["collection"],
        category=active_facets["category"],
        theme=active_facets["theme"],
        language=active_facets["language"],
        media_format=active_facets["format"],
    )
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    recommend_fn = None
    if settings.public_recommendations_engine == "audiobook":
        from . import portal_recommendations
        recommend_fn = portal_recommendations.rank
    return HTMLResponse(
        public_ui.catalog_page(
            principal, collections, query=query, view=view, search_note=search_note,
            authors=authors, active_author=author, sort=sort,
            author_counts=author_counts,
            facet_options=facet_options, active_facets=active_facets,
            filter_error=filter_error,
            premium=str(principal.get("plan") or "free").lower() == "premium",
            page=page, recommend_fn=recommend_fn,
        ),
        headers=_public_profile_headers(),
    )


def _public_base_url() -> str:
    return f"https://{settings.public_domain}" if settings.public_domain else ""


def _optional_public_principal(request: Request):
    try:
        return authenticate_public(request)
    except HTTPException:
        return None


def _public_plan_for_email(email: str) -> str:
    """Bootstrap plan from the operator allow-list; never downgrades a row."""
    allow = {str(item).strip().lower() for item in settings.premium_emails}
    return "premium" if str(email or "").strip().lower() in allow else "free"


def _require_premium(request: Request) -> dict:
    """Authenticate the public session and require the premium product plan.

    This is a product gate, not an authorization scope: a public principal
    still has zero object capabilities. Download routes call it before they
    mint any presigned URL; streaming only needs a public session.
    """
    principal = authenticate_public(request)
    if str(principal.get("plan") or "free").lower() != "premium":
        raise HTTPException(status_code=403, detail="premium account required")
    return principal


def _find_public_book(oid: str):
    """``(item, collection)`` of a published book, or ``(None, None)``.

    A book page used to rebuild the entire published catalogue (every pack and
    every chapter) just to find one object. Look up the packs containing this
    id directly and build only that pack's items (issue #299).
    """
    row = _as_dict(repo.get_object_unscoped(oid) or {})
    if (
        not row or row["status"] != AVAILABLE
        or not row.get("published_at") or not row.get("public_slug")
    ):
        return None, None
    for col_row in repo.get_published_collections_for_object(oid):
        col = _as_dict(col_row)
        items = _library_items(col, only_published=True)
        items = _attach_public_facets([{"items": items}])[0]["items"]
        item = next((i for i in items if i["id"] == oid), None)
        if item is not None:
            return item, {
                "title": col["title"],
                "description": col.get("description") or "",
                "items": items,
            }
    return None, None


def _preview_bytes(row: dict) -> int:
    """Size of the free preview in bytes, 0 when the format cannot be cut safely."""
    seconds = settings.public_preview_seconds
    duration = float(row.get("duration_seconds") or 0)
    size = int(row.get("size_bytes") or 0)
    if seconds <= 0 or duration <= 0 or size <= 0:
        return 0
    if (row.get("content_type") or "").split(";")[0].strip().lower() != "audio/mpeg":
        return 0  # only MPEG frames survive a cut at an arbitrary byte
    return min(size, int(size * min(seconds, duration) / duration) + 4096)


@app.get("/livre/{oid}", response_class=HTMLResponse)
def public_book_page(oid: str, request: Request):
    """One book of the published catalogue, readable without signing in."""
    if not _public_host_ok(request) or not settings.public_browse:
        raise HTTPException(status_code=404, detail="not found")
    try:
        oid = _canonical_id(oid, "object id")
    except HTTPException:
        item = None
    else:
        item, col = _find_public_book(oid)
    if item is None:
        return HTMLResponse(
            public_book.message_page("Livre introuvable", "Ce livre n'existe pas ou n'est plus publié."),
            status_code=404, headers=_public_profile_headers(),
        )
    principal = _optional_public_principal(request)
    related = [
        i for i in col["items"] if i["author"] and i["author"] == item["author"] and i["id"] != oid
    ][:6]
    position = next(n for n, i in enumerate(col["items"]) if i["id"] == oid)
    shown = {i["id"] for i in related} | {oid}
    up_next = [i for i in col["items"][position + 1:] if i["id"] not in shown][:6]
    # A pack with several ordered titles is presented as a series. Its editorial
    # description is the spoiler-free recap; operators must keep it that way.
    is_series = len(col["items"]) > 1
    recap = col.get("description") if is_series and up_next else ""
    row = _as_dict(repo.get_object_unscoped(oid) or {})
    if principal is not None:
        item["favorite"] = oid in repo.get_favorite_ids(principal["id"], [oid])
    return HTMLResponse(
        public_book.book_page(
            item, col["title"], related, principal, base_url=_public_base_url(),
            preview_seconds=settings.public_preview_seconds if _preview_bytes(row) else 0,
            up_next=up_next,
            recap=recap,
            series_position=position + 1 if is_series else 0,
            series_total=len(col["items"]) if is_series else 0,
        ),
        # The HTML contains the CSRF token and the visitor's favourite state:
        # only the anonymous version may be cached and indexed.
        headers=_public_profile_headers(indexable=principal is None),
    )


@app.get("/extrait/{oid}")
def public_preview(oid: str, request: Request):
    """Free preview: only the first minutes of a published MP3, cut server-side."""
    _public_rate_check("preview", request)
    if not _public_host_ok(request) or not settings.public_browse:
        raise HTTPException(status_code=404, detail="not found")
    oid = _canonical_id(oid, "object id")
    row = _as_dict(repo.get_object_unscoped(oid) or {})
    if (
        not row or row.get("status") != AVAILABLE or not row.get("published_at")
        or not _preview_bytes(row)
    ):
        raise HTTPException(status_code=404, detail="not found")
    length = _preview_bytes(row)
    set_request_principal(row.get("space_id"), None)
    try:
        body = s3ops.get_object(
            Bucket=row["bucket"], Key=row["object_key"], Range=f"bytes=0-{length - 1}",
        )["Body"]
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    _record_object_event(oid, length, "view")
    return StreamingResponse(
        body.iter_chunks(64 * 1024), media_type="audio/mpeg",
        headers={
            "Content-Length": str(length), "Accept-Ranges": "none",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline",
        },
    )


@app.get("/robots.txt")
def public_robots(request: Request):
    if not _public_host_ok(request) or not settings.public_domain:
        raise HTTPException(status_code=404, detail="not found")
    lines = ["User-agent: *"]
    if settings.public_browse:
        lines += ["Allow: /$", "Allow: /livre/", "Disallow: /",
                  f"Sitemap: {_public_base_url()}/sitemap.xml"]
    else:
        lines.append("Disallow: /")
    return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/sitemap.xml")
def public_sitemap(request: Request):
    if not _public_host_ok(request) or not settings.public_domain or not settings.public_browse:
        raise HTTPException(status_code=404, detail="not found")
    base = _public_base_url()
    urls = [f"{base}/"] + [
        f"{base}/livre/{i['id']}" for col in _public_catalog() for i in col["items"]
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{html_escape(u)}</loc></url>" for u in urls)
        + "</urlset>"
    )
    return Response(xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# Master mode: a short, password-confirmed elevation for bulk destructive
# actions (bulk purge, emptying the trash) without a confirmation per item.
# Bound to one browser session, needs objects:purge, expires on its own,
# and every activation and bulk action is audited.
# ---------------------------------------------------------------------------
class MasterModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


@app.post("/api/v1/me/master-mode")
def master_mode_on(
    body: MasterModeIn, request: Request,
    principal: dict = Depends(authorize(OBJECTS_PURGE, human=True)),
):
    client_ip = _client_ip(request)
    if _login_blocked(client_ip):
        raise HTTPException(status_code=429, detail="too many attempts",
                            headers={"Retry-After": str(settings.login_rate_window)})
    user = repo.get_user(principal["id"])
    if user is None or not verify_password(user["pass_hash"], body.password):
        _login_record_failure(client_ip)
        audit_event("master-mode", principal["id"], "failure")
        raise HTTPException(status_code=403, detail="password does not match")
    # A successful step-up clears the shared failure budget, like /login;
    # otherwise ten later successes cannot happen until the window expires.
    _login_clear(client_ip)
    until = int(time.time()) + settings.master_mode_ttl
    repo.set_session_master(principal["session_id"], until)
    audit_event("master-mode", principal["id"], "on", {"until": until})
    return {"master_until": until}


@app.delete("/api/v1/me/master-mode")
def master_mode_off(principal: dict = Depends(authorize(human=True))):
    repo.set_session_master(principal["session_id"], None)
    audit_event("master-mode", principal["id"], "off")
    return {"master_until": None}


def _require_master(principal: dict) -> None:
    if not master_mode_active(principal):
        raise HTTPException(status_code=403, detail="master mode required")


class BulkIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1)


def _bulk_purge(ids: list[str], principal: dict) -> dict:
    from .lifecycle import PurgeBlockedError, StorageDeleteError
    purged: list[str] = []
    not_found: list[str] = []
    failed: list[str] = []
    for oid in ids:
        try:
            oid = _canonical_id(oid, "object id")
        except HTTPException:
            not_found.append(oid)
            continue
        try:
            done = purge_object(repo, s3ops, oid, **_object_scope(principal))
        except (StorageDeleteError, PurgeBlockedError):
            failed.append(oid)
            continue
        (purged if done else not_found).append(oid)
    audit_event("bulk-purge", principal["id"], "success", {
        "purged": len(purged), "not_found": len(not_found), "failed": len(failed),
    })
    return {"purged": purged, "not_found": not_found, "failed": failed}






def _upload_headers(content_type: str) -> dict:
    """Headers the client must send with the presigned PUT (both are signed)."""
    return {"Content-Type": content_type, SSE_HEADER: SSE_ALGORITHM,
            "If-None-Match": "*"}


@app.post("/api/v1/objects/upload-intents")
def upload_intent(
    body: UploadIntentIn, request: Request,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    space_id = principal["space_id"]
    if not space_id:
        raise HTTPException(status_code=403, detail="forbidden")
    # A disabled space refuses new uploads (#M04): existing objects stay readable
    # and downloadable, but the space is closed to new writes.
    if principal.get("space_status") not in (None, "active"):
        raise HTTPException(status_code=403, detail="forbidden")

    # Authoritative server-side transfer policy: media type, size ceiling and
    # empty-file rule. A malformed/blocked type or an out-of-range size is a 422
    # before any intent row or presigned URL exists. The browser checks are UX.
    try:
        content_type = validate_upload_policy(
            body.content_type, body.size_bytes,
            max_bytes=_upload_ceiling(),
            allow_empty=settings.allow_empty_objects,
            allowed_types=settings.allowed_content_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Optional zstd compression (C3): never transparent, never on already-compressed types.
    content_encoding = body.content_encoding
    if content_encoding is not None:
        if content_encoding not in ("zstd",):
            raise HTTPException(status_code=422, detail="unsupported content encoding")
        from .transfer import NON_COMPRESSIBLE_TYPES
        bare = content_type.split(";", 1)[0].strip().lower()
        if bare in NON_COMPRESSIBLE_TYPES:
            raise HTTPException(status_code=422, detail="content type must not be compressed")

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
            # A replay may be the first request to carry the batch id (older
            # client/row): attach it now so the terminal journal can still
            # correlate the attempt. Never overwrite an existing session id.
            if body.transfer_session_id and not existing.get("transfer_session_id"):
                repo.set_transfer_session(existing["id"], body.transfer_session_id)
                existing["transfer_session_id"] = body.transfer_session_id
            expires_at = existing.get("intent_expires_at")
            now_ts = int(time.time())
            grace_deadline = int(expires_at) + settings.intent_grace_s if expires_at else now_ts
            # G6: a replay accepted too close to the grace deadline would hand
            # out a URL whose commits are refused for most of its life. Retire
            # the old intent and fall through to mint a fresh one.
            if expires_at and (now_ts + settings.replay_refresh_margin_s) > grace_deadline:
                # Retire the old intent: abort its multipart session first,
                # otherwise its parts linger until the session TTL with no
                # catalogue row left for the sweep to act on.
                _abort_multipart_session(existing)
                try:
                    s3ops.delete_object(Bucket=existing["bucket"], Key=existing["object_key"])
                except Exception:
                    pass
                repo.set_status(
                    existing["id"], EXPIRED,
                    failure_kind="expired",
                    error_message="upload intent expired before replay",
                )
                # fall through: create a new intent below
            elif not expires_at or now_ts <= grace_deadline:
                if existing.get("multipart_upload_id"):
                    # A resumed multipart upload: same session, the client then
                    # asks which parts are still missing (#72).
                    audit_event("upload-intent", principal["id"], "replay", {
                        "object_id": existing["id"], "bucket": existing["bucket"],
                    })
                    return _multipart_intent_response(existing, replay=True)
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
                    "headers": _upload_headers(existing["content_type"]),
                    "content_type": existing["content_type"],
                    "size_bytes": expected, "expires_in": settings.intent_ttl,
                    "expires_at": expires_at, "idempotent_replay": True,
                    "transfer_session_id": existing.get("transfer_session_id"),
                }
            # Retired above (or past grace): fall through to mint a fresh intent.

    if idem_key:
        # The same file was already sent (page reloaded while its check ran):
        # report it instead of sending the bytes a second time.
        done = repo.get_by_idempotency(
            actor_id=principal["id"], idempotency_key=idem_key, space_id=space_id
        )
        if done is not None and _as_dict(done)["status"] in (VERIFYING, AVAILABLE):
            done = _as_dict(done)
            return {
                "id": done["id"], "status": done["status"], "method": "PUT",
                "upload_url": None, "headers": {},
                "content_type": done["content_type"],
                "size_bytes": done.get("expected_size_bytes"),
                "expires_in": 0, "expires_at": None, "idempotent_replay": True,
                "transfer_session_id": done.get("transfer_session_id"),
            }

    # Only live intents count: an expired row (whose bytes the sweep has not
    # deleted yet) must not block a resume after a session loss.
    live_since = int(time.time()) - settings.intent_grace_s
    owner_id = principal["id"] if principal["kind"] == "user" else None
    # Admission is a check-then-insert sequence; hold the repository lock so
    # concurrent intents cannot all pass the same capacity check. (The lock is
    # process-local, which matches the single-worker deployment; a pool would
    # need a DB-side reservation.)
    with repo._lock:
        if repo.count_pending(
            **_object_scope(principal), min_expires_at=live_since
        ) >= settings.max_pending_intents:
            raise HTTPException(status_code=429, detail="too many pending uploads")
        if settings.max_pending_bytes_per_owner > 0:
            reserved = repo.reserved_bytes_for(
                space_id=space_id, owner_id=owner_id, min_expires_at=live_since,
            )
            if reserved + body.size_bytes > settings.max_pending_bytes_per_owner:
                audit_event("upload-intent", principal["id"], "reservation_cap", {
                    "size_bytes": body.size_bytes, "reserved_bytes": reserved,
                })
                raise HTTPException(status_code=429, detail="too many pending bytes")
        _check_capacity(body.size_bytes)
        _check_storage_quota(space_id, body.size_bytes)

    if body.folder_id is not None:
        # A client-supplied folder must exist and be owned by the caller (#61).
        # Service identities own no folders, so any folder_id they send is refused.
        if principal["kind"] != "user" or repo.get_folder(
            body.folder_id, owner_id=principal["id"]
        ) is None:
            raise HTTPException(status_code=403, detail="forbidden")

    _charge_quota(space_id, body.size_bytes)

    key = f"aura/{space_id}/{principal['id']}/{ids.new_id()}"
    multipart = (
        settings.multipart_enabled
        and body.size_bytes >= settings.multipart_threshold_bytes
    )
    intent_expires_at = int(time.time()) + (
        settings.multipart_session_ttl if multipart else settings.intent_ttl
    )
    oid = repo.create_pending_object(
        space_id=space_id, application_id=principal["application_id"],
        environment=principal["environment"], bucket=bucket, object_key=key,
        display_name=body.display_name, content_type=content_type,
        owner_id=owner_id, actor_id=principal["id"], actor_kind=principal["kind"],
        intent_expires_at=intent_expires_at, folder_id=body.folder_id,
        expected_size_bytes=body.size_bytes, idempotency_key=idem_key,
        content_encoding=content_encoding,
        transfer_session_id=body.transfer_session_id,
    )
    if multipart:
        part_bytes, _ = plan_parts(body.size_bytes, settings.multipart_part_bytes)
        try:
            upload_id = create_multipart(s3ops, bucket, key, content_type)
        except Exception:
            repo.set_status(
                oid, "failed",
                failure_kind="storage_unavailable",
                error_message="storage unavailable while starting multipart upload",
            )
            audit_event("upload-intent", principal["id"], "storage_failure", {
                "object_id": oid, "bucket": bucket,
            })
            raise HTTPException(status_code=502, detail="storage unavailable")
        repo.set_multipart(oid, upload_id, part_bytes)
        audit_event("upload-intent", principal["id"], "success", {
            "object_id": oid, "bucket": bucket, "size_bytes": body.size_bytes,
            "multipart": True,
        })
        return _multipart_intent_response(
            _as_dict(repo.get_object(oid, **_object_scope(principal))), replay=False,
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
        "headers": _upload_headers(content_type),
        "content_type": content_type, "size_bytes": body.size_bytes,
        "expires_in": settings.intent_ttl, "expires_at": intent_expires_at,
        "idempotent_replay": False,
        "transfer_session_id": body.transfer_session_id,
    }


@app.post("/api/v1/objects/{oid}/replace-intents")
def create_replace_intent(
    oid: str,
    body: UploadIntentIn, request: Request,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Create an upload intent whose committed bytes replace an existing object.

    Lot 3.3.2: the new bytes are uploaded to a fresh key; on commit the target's
    current head is archived as a content revision and the target adopts the new
    bytes. This is the archive-on-replace path (no in-place overwrite).
    """
    target_id = _canonical_id(oid, "object id")
    target = repo.get_object(target_id, **_object_scope(principal))
    if target is None:
        raise HTTPException(status_code=404, detail="object not found")
    target = _as_dict(target)
    if target.get("status") != AVAILABLE:
        raise HTTPException(status_code=409, detail="object not available")

    space_id = principal["space_id"]
    if not space_id:
        raise HTTPException(status_code=403, detail="forbidden")
    if principal.get("space_status") not in (None, "active"):
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        content_type = validate_upload_policy(
            body.content_type, body.size_bytes,
            max_bytes=_upload_ceiling(),
            allow_empty=settings.allow_empty_objects,
            allowed_types=settings.allowed_content_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    content_encoding = body.content_encoding
    if content_encoding is not None:
        if content_encoding not in ("zstd",):
            raise HTTPException(status_code=422, detail="unsupported content encoding")
        from .transfer import NON_COMPRESSIBLE_TYPES
        bare = content_type.split(";", 1)[0].strip().lower()
        if bare in NON_COMPRESSIBLE_TYPES:
            raise HTTPException(status_code=422, detail="content type must not be compressed")

    idem_key = request.headers.get("idempotency-key")
    if idem_key is not None and not valid_idempotency_key(
        idem_key, max_length=settings.idempotency_key_max
    ):
        raise HTTPException(status_code=422, detail="invalid idempotency key")

    # Replacement stays in the target's bucket/space.
    bucket = target["bucket"]
    owner_id = principal["id"] if principal["kind"] == "user" else None
    live_since = int(time.time()) - settings.intent_grace_s
    with repo._lock:
        if repo.count_pending(
            **_object_scope(principal), min_expires_at=live_since
        ) >= settings.max_pending_intents:
            raise HTTPException(status_code=429, detail="too many pending uploads")
        if settings.max_pending_bytes_per_owner > 0:
            reserved = repo.reserved_bytes_for(
                space_id=space_id, owner_id=owner_id, min_expires_at=live_since,
            )
            if reserved + body.size_bytes > settings.max_pending_bytes_per_owner:
                raise HTTPException(status_code=429, detail="too many pending bytes")
        _check_capacity(body.size_bytes)
        _check_storage_quota(space_id, body.size_bytes)
    _charge_quota(space_id, body.size_bytes)

    key = f"aura/{space_id}/{principal['id']}/{ids.new_id()}"
    multipart = (
        settings.multipart_enabled
        and body.size_bytes >= settings.multipart_threshold_bytes
    )
    intent_expires_at = int(time.time()) + (
        settings.multipart_session_ttl if multipart else settings.intent_ttl
    )
    intent_oid = repo.create_pending_object(
        space_id=space_id, application_id=principal["application_id"],
        environment=principal["environment"], bucket=bucket, object_key=key,
        display_name=body.display_name or target.get("display_name") or "file",
        content_type=content_type,
        owner_id=owner_id, actor_id=principal["id"], actor_kind=principal["kind"],
        intent_expires_at=intent_expires_at, folder_id=target.get("folder_id"),
        expected_size_bytes=body.size_bytes, idempotency_key=idem_key,
        content_encoding=content_encoding,
        transfer_session_id=body.transfer_session_id,
        replace_target_id=target_id,
    )
    if multipart:
        part_bytes, _ = plan_parts(body.size_bytes, settings.multipart_part_bytes)
        try:
            upload_id = create_multipart(s3ops, bucket, key, content_type)
        except Exception:
            repo.set_status(intent_oid, "failed", failure_kind="storage_unavailable",
                            error_message="storage unavailable while starting multipart upload")
            raise HTTPException(status_code=502, detail="storage unavailable")
        repo.set_multipart(intent_oid, upload_id, part_bytes)
        audit_event("replace-intent", principal["id"], "success", {
            "object_id": target_id, "intent_id": intent_oid, "bucket": bucket,
            "size_bytes": body.size_bytes, "multipart": True,
        })
        return _multipart_intent_response(
            _as_dict(repo.get_object(intent_oid, **_object_scope(principal))), replay=False,
        )
    url = presigned_put(s3, bucket, key, content_type, settings.intent_ttl, body.size_bytes)
    audit_event("replace-intent", principal["id"], "success", {
        "object_id": target_id, "intent_id": intent_oid, "bucket": bucket,
        "size_bytes": body.size_bytes,
    })
    return {
        "id": intent_oid, "status": PENDING, "method": "PUT", "upload_url": url,
        "headers": _upload_headers(content_type),
        "content_type": content_type, "size_bytes": body.size_bytes,
        "expires_in": settings.intent_ttl, "expires_at": intent_expires_at,
        "idempotent_replay": False,
        "transfer_session_id": body.transfer_session_id,
        "replace_target_id": target_id,
    }


def _capacity() -> dict | None:
    """Fill level of the object store against the configured capacity."""
    if settings.storage_capacity_bytes <= 0:
        return None
    committed = repo.storage_commitment()
    limit = settings.storage_capacity_bytes * settings.storage_high_watermark_pct // 100
    used = committed["stored"] + committed["reserved"]
    return {
        "capacity_bytes": settings.storage_capacity_bytes,
        "high_watermark_pct": settings.storage_high_watermark_pct,
        "accept_until_bytes": limit,
        "stored_bytes": committed["stored"],
        "reserved_bytes": committed["reserved"],
        "free_for_uploads_bytes": max(0, limit - used),
    }


def _check_capacity(size_bytes: int) -> None:
    """Refuse (507) an upload that would push the disk past the watermark.

    The declared size is reserved as soon as the intent exists, so a burst of
    parallel imports is accounted for before any byte lands.
    """
    cap = _capacity()
    if cap is not None and size_bytes > cap["free_for_uploads_bytes"]:
        audit_event("upload-intent", None, "capacity", {
            "size_bytes": size_bytes, "free_bytes": cap["free_for_uploads_bytes"],
        })
        raise HTTPException(status_code=507, detail="storage capacity reached")


def _upload_ceiling() -> int:
    """Largest declarable size: multipart lifts the single-PUT ceiling."""
    if settings.multipart_enabled:
        return max(settings.max_object_bytes, settings.multipart_max_object_bytes)
    return settings.max_object_bytes


def _multipart_intent_response(row: dict, *, replay: bool) -> dict:
    size = int(row["expected_size_bytes"])
    part_bytes = int(row["multipart_part_bytes"])
    return {
        "id": row["id"], "status": PENDING, "method": "PUT",
        "upload_mode": "multipart", "upload_url": None, "headers": {},
        "content_type": row["content_type"], "size_bytes": size,
        "multipart": {
            "part_size_bytes": part_bytes,
            "part_count": -(-size // part_bytes),
        },
        "expires_in": max(0, int(row["intent_expires_at"]) - int(time.time())),
        "expires_at": row["intent_expires_at"], "idempotent_replay": replay,
        "transfer_session_id": row.get("transfer_session_id"),
    }


def _pending_multipart(oid: str, principal: dict) -> dict:
    """The caller's own pending object with an open multipart session (or 404/409)."""
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != PENDING or not row.get("multipart_upload_id"):
        raise HTTPException(status_code=409, detail="no multipart upload in progress")
    expires_at = row.get("intent_expires_at")
    if expires_at and int(time.time()) > int(expires_at) + settings.intent_grace_s:
        raise HTTPException(status_code=410, detail="upload intent expired")
    return row


def _uploaded_parts(row: dict) -> dict[int, tuple[int, str]]:
    """Parts the backend holds whose size matches the plan exactly."""
    size = int(row["expected_size_bytes"])
    part_bytes = int(row["multipart_part_bytes"])
    count = -(-size // part_bytes)
    try:
        held = list_uploaded_parts(
            s3ops, row["bucket"], row["object_key"], row["multipart_upload_id"]
        )
    except Exception as exc:
        if is_no_such_upload(exc):
            raise HTTPException(status_code=410, detail="multipart upload no longer exists")
        raise HTTPException(status_code=502, detail="storage unavailable")
    return {
        number: part for number, part in held.items()
        if 1 <= number <= count and part[0] == part_length(number, part_bytes, size)
    }


def _complete_multipart_session(row: dict, principal: dict) -> None:
    """Check every planned part is held, then assemble the object (#72).

    The part list is read from the backend, never taken from the client. A
    missing part is a 409 the client resolves by sending it; after a successful
    completion the session is cleared, so a retried commit goes straight to the
    full-object SHA-256 verification.
    """
    size = int(row["expected_size_bytes"])
    part_bytes = int(row["multipart_part_bytes"])
    count = -(-size // part_bytes)
    try:
        parts = _uploaded_parts(row)
    except HTTPException as exc:
        if exc.status_code != 410:
            raise
        # The session is gone: a previous commit completed it and crashed
        # before recording that. The object itself decides (head below).
        repo.set_multipart(row["id"], None, part_bytes)
        row["multipart_upload_id"] = None
        return
    missing = count - len(parts)
    if missing:
        raise HTTPException(
            status_code=409, detail=f"{missing} part(s) missing; upload them, then commit",
        )
    try:
        complete_multipart(
            s3ops, row["bucket"], row["object_key"], row["multipart_upload_id"], parts,
        )
    except Exception as exc:
        if is_no_such_upload(exc):
            repo.set_multipart(row["id"], None, part_bytes)
            row["multipart_upload_id"] = None
            return
        audit_event("commit", principal["id"], "storage_failure", {"object_id": row["id"]})
        raise HTTPException(status_code=502, detail="storage could not assemble the parts")
    repo.set_multipart(row["id"], None, part_bytes)
    row["multipart_upload_id"] = None


def _abort_multipart_session(row: dict) -> None:
    if not row.get("multipart_upload_id"):
        return
    try:
        abort_multipart(s3ops, row["bucket"], row["object_key"], row["multipart_upload_id"])
    except Exception as exc:
        if not is_no_such_upload(exc):
            # Best effort: the session stays recorded and the sweep retries.
            return
    repo.set_multipart(row["id"], None, row.get("multipart_part_bytes"))


class PartUrlsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_numbers: list[int] = Field(min_length=1, max_length=100)


@app.get("/api/v1/objects/{oid}/multipart")
def multipart_status(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE))):
    """Plan and parts already held: a resumed upload sends only the rest."""
    row = _pending_multipart(oid, principal)
    size = int(row["expected_size_bytes"])
    part_bytes = int(row["multipart_part_bytes"])
    return {
        "id": row["id"], "size_bytes": size, "part_size_bytes": part_bytes,
        "part_count": -(-size // part_bytes),
        "uploaded_parts": sorted(_uploaded_parts(row)),
    }


@app.post("/api/v1/objects/{oid}/multipart/parts")
def multipart_part_urls(
    oid: str, body: PartUrlsIn, principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    """Short-lived presigned PUTs for the requested part numbers (max 100)."""
    row = _pending_multipart(oid, principal)
    size = int(row["expected_size_bytes"])
    part_bytes = int(row["multipart_part_bytes"])
    count = -(-size // part_bytes)
    numbers = sorted(set(body.part_numbers))
    if any(n < 1 or n > count for n in numbers):
        raise HTTPException(status_code=422, detail="part number out of range")
    parts = []
    for number in numbers:
        length = part_length(number, part_bytes, size)
        parts.append({
            "part_number": number, "size_bytes": length,
            "url": presigned_upload_part(
                s3, row["bucket"], row["object_key"], row["multipart_upload_id"],
                number, length, settings.intent_ttl,
            ),
        })
    return {"id": row["id"], "expires_in": settings.intent_ttl, "parts": parts}


def _cache_key(route: str, oid: str, idem: str | None, principal_id: str = "") -> str | None:
    if not idem:
        return None
    # The caller is part of the key: one principal's cached answer is never
    # served to another that happens to reuse the same key and object id.
    return f"{route}:{principal_id}:{oid}:{idem}"


def _cache_get(key: str | None):
    if key is None:
        return None
    with _RESP_CACHE_LOCK:
        entry = _RESP_CACHE.get(key)
        if entry is None:
            return None
        if time.time() - entry[0] > _RESP_CACHE_TTL:
            _RESP_CACHE.pop(key, None)
            return None
        return entry[1], entry[2]


def _cache_set(key: str | None, status: int, body):
    if key is None:
        return
    now = time.time()
    with _RESP_CACHE_LOCK:
        if len(_RESP_CACHE) >= _RESP_CACHE_MAX:
            # Bounded: drop expired entries, then the oldest ones.
            for k in [k for k, v in _RESP_CACHE.items() if now - v[0] > _RESP_CACHE_TTL]:
                _RESP_CACHE.pop(k, None)
            while len(_RESP_CACHE) >= _RESP_CACHE_MAX:
                _RESP_CACHE.pop(next(iter(_RESP_CACHE)), None)
        _RESP_CACHE[key] = (now, status, body)


def _defer_slow_commit(oid, size, head, principal):
    """The synchronous check ran past its deadline: the bytes may well be fine
    (a slow disk under load is not corruption), so hand the object to the
    verification worker instead of deleting it. The client follows the 202."""
    repo.mark_verifying(oid, head.get("ETag"))
    audit_event("commit", principal["id"], "deadline_deferred", {"object_id": oid})
    return JSONResponse(status_code=202, content={
        "id": oid, "status": VERIFYING, "size_bytes": size,
    })


def _finalize_replacement_commit(intent: dict, size: int, digest: str, principal: dict) -> dict:
    """Archive target head as revision and adopt committed intent bytes (Lot 3.3.2).

    Hardened for idempotent replay: if the target already reflects this intent's
    bytes, return success (and clean up a stray intent row). Archive/swap is
    ordered for recoverability and uses a CAS on target status/version.
    """
    target_id = intent.get("replace_target_id")
    intent_oid = intent.get("id")
    if not target_id:
        raise HTTPException(status_code=500, detail="replacement target missing")

    target = repo.get_object(target_id, space_id=intent.get("space_id"))
    if target is None:
        raise HTTPException(status_code=404, detail="replacement target not found")
    target = _as_dict(target)

    # Idempotent replay: target already adopted this intent's committed bytes.
    if (
        target.get("status") == AVAILABLE
        and target.get("object_key") == intent.get("object_key")
        and target.get("checksum_sha256") == digest
        and int(target.get("size_bytes") or 0) == int(size)
    ):
        # Best-effort cleanup of a leftover intent row from a partial previous run.
        try:
            if intent_oid:
                if hasattr(repo, "_run"):
                    repo._run("DELETE FROM objects WHERE id = %s", (intent_oid,))
                else:
                    repo.conn.execute("DELETE FROM objects WHERE id = ?", (intent_oid,))
                    repo.conn.commit()
        except Exception:
            pass
        return {
            "id": target_id, "status": "available", "size_bytes": int(target.get("size_bytes") or size),
            "checksum_sha256": target.get("checksum_sha256") or digest,
            "checksum_algorithm": "sha256",
        }

    if target.get("status") != AVAILABLE:
        raise HTTPException(status_code=409, detail="replacement target not available")

    target_version = target.get("version")
    existing = repo.list_revisions(target_id)
    next_no = (max((int(r.get("revision_number") or 0) for r in existing), default=0) + 1)
    # Reuse an archive revision for this exact head if a prior attempt partially completed.
    old_key = target.get("object_key")
    archive = None
    for r in existing:
        if (
            r.get("storage_key") == old_key
            and r.get("checksum_sha256") == (target.get("checksum_sha256") or "")
            and int(r.get("size_bytes") or 0) == int(target.get("size_bytes") or 0)
        ):
            archive = r
            break
    if archive is not None:
        archive_rid = archive["id"]
        archive_no = int(archive.get("revision_number") or next_no)
    else:
        archive_key = f"aura/{intent['space_id']}/revisions/{target_id}/{ids.new_id()}"
        copy_object(s3ops, target["bucket"], target["object_key"], archive_key, target.get("content_type"))
        archive_rid = repo.create_revision(
            object_id=target_id, revision_number=next_no, bucket=target["bucket"],
            storage_key=archive_key, size_bytes=int(target.get("size_bytes") or 0),
            checksum_sha256=target.get("checksum_sha256") or "",
            content_type=target.get("content_type") or "application/octet-stream",
            created_by_id=principal["id"], created_by_kind=principal.get("kind"),
            keep_forever=False,
        )
        archive_no = next_no

    # 2) Swap with CAS: only if target still at the same head/version.
    # Free intent's (bucket,object_key) uniqueness before adopting it on target.
    now = int(time.time())
    if hasattr(repo, "_run"):
        if intent_oid:
            repo._run("DELETE FROM objects WHERE id = %s", (intent_oid,))
        res = repo._run(
            "UPDATE objects SET bucket = %s, object_key = %s, size_bytes = %s, "
            "checksum_sha256 = %s, content_type = %s, expected_size_bytes = %s, "
            "content_encoding = %s, version = COALESCE(version,0)+1, "
            "revision_count = %s, current_revision_id = %s, replaced_at = %s, "
            "status = 'available', updated_at = %s, scrubbed_at = %s, scrub_result = 'ok' "
            "WHERE id = %s AND status = 'available' AND COALESCE(version,0) = COALESCE(%s,0) AND object_key = %s",
            (intent["bucket"], intent["object_key"], size, digest,
             intent.get("content_type") or target.get("content_type"),
             intent.get("expected_size_bytes"),
             intent.get("content_encoding"),
             max(int(target.get("revision_count") or 0), archive_no), archive_rid, now, now, now,
             target_id, target_version, old_key),
        )
        updated = int(getattr(res, "rowcount", 0) or 0)
        if updated == 0:
            fresh = repo.get_object(target_id, space_id=intent.get("space_id"))
            fresh = _as_dict(fresh) if fresh else None
            if fresh and fresh.get("status") == AVAILABLE and fresh.get("object_key") == intent.get("object_key") and fresh.get("checksum_sha256") == digest:
                return {"id": target_id, "status": "available", "size_bytes": int(fresh.get("size_bytes") or size),
                        "checksum_sha256": digest, "checksum_algorithm": "sha256"}
            raise HTTPException(status_code=409, detail="replacement target changed concurrently")
    else:
        if intent_oid:
            repo.conn.execute("DELETE FROM objects WHERE id = ?", (intent_oid,))
        cur = repo.conn.execute(
            "UPDATE objects SET bucket = ?, object_key = ?, size_bytes = ?, "
            "checksum_sha256 = ?, content_type = ?, expected_size_bytes = ?, "
            "content_encoding = ?, version = COALESCE(version,0)+1, "
            "revision_count = ?, current_revision_id = ?, replaced_at = ?, "
            "status = 'available', updated_at = ?, scrubbed_at = ?, scrub_result = 'ok' "
            "WHERE id = ? AND status = 'available' AND COALESCE(version,0) = COALESCE(?,0) AND object_key = ?",
            (intent["bucket"], intent["object_key"], size, digest,
             intent.get("content_type") or target.get("content_type"),
             intent.get("expected_size_bytes"),
             intent.get("content_encoding"),
             max(int(target.get("revision_count") or 0), archive_no), archive_rid, now, now, now,
             target_id, target_version, old_key),
        )
        updated = int(getattr(cur, "rowcount", 0) or 0)
        if updated == 0:
            fresh = repo.get_object(target_id, space_id=intent.get("space_id"))
            fresh = _as_dict(fresh) if fresh else None
            if fresh and fresh.get("status") == AVAILABLE and fresh.get("object_key") == intent.get("object_key") and fresh.get("checksum_sha256") == digest:
                repo.conn.commit()
                return {"id": target_id, "status": "available", "size_bytes": int(fresh.get("size_bytes") or size),
                        "checksum_sha256": digest, "checksum_algorithm": "sha256"}
            repo.conn.rollback() if hasattr(repo.conn, "rollback") else None
            raise HTTPException(status_code=409, detail="replacement target changed concurrently")
        repo.conn.commit()

    audit_event("object.replace", principal["id"], "success", {
        "object_id": target_id, "intent_id": intent_oid,
        "archived_revision_id": archive_rid, "revision_number": archive_no,
        "size_bytes": size,
    })
    return {"id": target_id, "status": "available", "size_bytes": size,
            "checksum_sha256": digest, "checksum_algorithm": "sha256"}



@app.post("/api/v1/objects/{oid}/commit")
def commit_object(
    oid: str, response: Response, request: Request,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    started = time.perf_counter()
    # Global deadline for this commit (#120): measured from request start so
    # HEAD time and hashing share one budget, enforced per chunk by
    # stream_sha256 (the other phases are bounded by the S3 client timeouts).
    deadline = time.monotonic() + settings.commit_deadline_s
    oid = _canonical_id(oid, "object id")
    idem = request.headers.get("idempotency-key")
    ck = _cache_key("commit", oid, idem, principal["id"])
    cached = _cache_get(ck)
    if cached is not None:
        status, body = cached
        response.status_code = status
        return body
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
    if row["status"] == VERIFYING:
        # Idempotent: the integrity check is still running (N5).
        return JSONResponse(status_code=202, content={
            "id": oid, "status": VERIFYING, "size_bytes": row.get("expected_size_bytes"),
        })
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="object not committable")

    expires_at = row.get("intent_expires_at")
    if expires_at and int(time.time()) > int(expires_at) + settings.intent_grace_s:
        # Clean up before closing the intent: an expired row is no longer
        # selected by reconcile_pending, so any multipart session or partial
        # bytes left here would be orphaned until the terminal sweep finds it.
        _abort_multipart_session(row)
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            pass
        repo.set_status(
            oid, "expired",
            failure_kind="expired",
            error_message="upload intent expired before commit",
        )
        audit_event("commit", principal["id"], "expired", {"object_id": oid})
        raise HTTPException(status_code=410, detail="upload intent expired")

    max_bytes = settings.max_object_bytes
    if row.get("multipart_part_bytes"):
        max_bytes = settings.multipart_max_object_bytes
    if row.get("multipart_upload_id"):
        _complete_multipart_session(row, principal)

    head_started = time.perf_counter()
    try:
        head = s3ops.head_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception:
        raise HTTPException(status_code=422, detail="upload not found at storage")
    head_s = time.perf_counter() - head_started

    size = int(head.get("ContentLength", -1))
    if size < 0:
        raise HTTPException(status_code=422, detail="upload size unknown")
    if size > max_bytes:
        repo.set_status(
            oid, "failed",
            failure_kind="size_limit",
            error_message="object exceeds maximum allowed size",
        )
        raise HTTPException(status_code=413, detail="object exceeds maximum allowed size")
    if settings.require_sse and head.get("ServerSideEncryption") != SSE_ALGORITHM:
        # Never mark plaintext-at-rest bytes available; drop them best-effort
        # (the reconciliation sweep retries a failed delete).
        repo.set_status(
            oid, "failed",
            failure_kind="not_encrypted",
            error_message="object not encrypted at rest",
        )
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            pass
        audit_event("commit", principal["id"], "unencrypted", {"object_id": oid})
        raise HTTPException(status_code=422, detail="object not encrypted at rest")

    # Defence in depth: the declared size must match the size actually stored.
    expected_declared = row.get("expected_size_bytes")
    try:
        expected_declared = int(expected_declared) if expected_declared is not None else None
    except (TypeError, ValueError):
        expected_declared = None
    if expected_declared is not None and expected_declared >= 0 and size != expected_declared:
        repo.set_status(
            oid, "failed",
            failure_kind="size_mismatch",
            error_message="uploaded size does not match declared size",
        )
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            pass
        audit_event("commit", principal["id"], "size_mismatch_declared", {"object_id": oid})
        raise HTTPException(status_code=422, detail="uploaded size does not match declared size")

    if size >= settings.verify_async_threshold_bytes:
        # Replacement intents with async verification are not yet supported.
        if row.get("replace_target_id"):
            raise HTTPException(status_code=422, detail="replacement of large objects requires synchronous verification")
        # Large object: hand it to the verification worker instead of hashing
        # gigabytes inside this request (N5). The client follows the status.
        repo.mark_verifying(oid, head.get("ETag"))
        audit_event("commit", principal["id"], "verifying", {"object_id": oid, "size_bytes": size})
        return JSONResponse(status_code=202, content={
            "id": oid, "status": VERIFYING, "size_bytes": size,
        })

    hash_started = time.perf_counter()
    try:
        body = s3ops.get_object(Bucket=row["bucket"], Key=row["object_key"])["Body"]
        # Reuse the single deadline set at request start: resetting it here
        # silently doubled the budget (HEAD + hash) past the proxy's 310 s,
        # so the structured 504 never reached the client.
        total, digest = stream_sha256(body, max_bytes, settings.commit_chunk_bytes, deadline=deadline)
    except ObjectTooLarge:
        repo.set_status(
            oid, "failed",
            failure_kind="size_limit",
            error_message="object exceeds maximum allowed size",
        )
        raise HTTPException(status_code=413, detail="object exceeds maximum allowed size")
    except CommitDeadlineExceeded:
        return _defer_slow_commit(oid, size, head, principal)
    except Exception:
        raise HTTPException(status_code=422, detail="upload not readable at storage")
    hash_s = time.perf_counter() - hash_started

    if total != size or (expected_declared is not None and expected_declared >= 0 and total != expected_declared):
        # Truncated or mismatched upload is never marked available (#37).
        repo.set_status(
            oid, "failed",
            failure_kind="size_mismatch",
            error_message="uploaded size does not match storage",
        )
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            pass
        raise HTTPException(status_code=422, detail="uploaded size does not match storage")

    # Optional AV scan (D4): if configured, scan the bytes before publication.
    if settings.av_scan_cmd:
        try:
            verdict = av_scan_object(s3ops, row["bucket"], row["object_key"], settings)
        except Exception:
            raise HTTPException(status_code=422, detail="upload not readable at storage")
        if verdict == AV_INFECTED:
            repo.set_status(
                oid, "failed",
                failure_kind="av_infected",
                error_message="object failed av scan",
            )
            try:
                s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
            except Exception:
                pass
            audit_event("commit", principal["id"], "av_infected", {"object_id": oid})
            raise HTTPException(status_code=422, detail="object failed av scan")
        if verdict == AV_TIMEOUT:
            # Not a verdict: the object stays pending and the client may retry.
            raise HTTPException(status_code=504, detail="av scan timed out")

    # Hard deadline guard for the synchronous commit path.
    if settings.commit_deadline_s and (time.perf_counter() - started) > settings.commit_deadline_s:
        if row.get("replace_target_id"):
            # Replacement finalization is a synchronous archive+swap; do not defer
            # to async verification in this cut (would risk partial/inconsistent state).
            raise HTTPException(status_code=504, detail="commit deadline exceeded for replacement")
        return _defer_slow_commit(oid, size, head, principal)

    # Replacement intent: archive target head and swap target to the verified bytes.
    if row.get("replace_target_id"):
        result = _finalize_replacement_commit(row, size, digest, principal)
        audit_event("commit", principal["id"], "success", {"object_id": result.get("id", oid), "size_bytes": size})
        try:
            _THUMBNAIL_POOL.submit(_safe_generate_thumbnail, dict(row, id=result.get("id", oid)))
        except Exception:
            pass
        total_s = time.perf_counter() - started
        head_ms = head_s * 1000.0
        hash_ms = hash_s * 1000.0
        total_ms = total_s * 1000.0
        response.headers["Server-Timing"] = (
            f"head;dur={head_ms:.1f}, hash;dur={hash_ms:.1f}, total;dur={total_ms:.1f}"
        )
        log.info("commit timings oid=%s bytes=%d head_ms=%.1f hash_ms=%.1f total_ms=%.1f",
                 result.get("id", oid), size, head_ms, hash_ms, total_ms)
        result["commit_timing"] = {
            "head_ms": round(head_ms, 3),
            "hash_ms": round(hash_ms, 3),
            "total_ms": round(total_ms, 3),
        }
        _cache_set(ck, 200, result)
        return result

    row_version = row.get("version")
    n = repo.mark_available(oid, size, digest, expected_version=row_version)
    if n == 0:
        # Compare-and-set lost the race. Re-read to distinguish idempotent
        # success (already available with the same digest) from a real conflict.
        fresh = _as_dict(repo.get_object(oid, **_object_scope(principal)))
        if fresh and fresh.get("status") == "available" and fresh.get("checksum_sha256") == digest:
            audit_event("commit", principal["id"], "success", {"object_id": oid, "size_bytes": size})
            # Le commit a été fait par une requête concurrente : les phases
            # HEAD/hash ne sont pas mesurées *ici*, donc les inventer (0, ou des
            # durées partielles) serait mensonger. On expose explicitement
            # ``null`` — le front type le champ en ``CommitTiming | null`` et sait
            # distinguer « non mesuré » de « mesuré ».
            return {
                "id": oid, "status": "available", "size_bytes": fresh.get("size_bytes", size),
                "checksum_sha256": digest, "checksum_algorithm": "sha256",
                "commit_timing": None,
            }
        raise HTTPException(status_code=409, detail="concurrent commit conflict")
    audit_event("commit", principal["id"], "success", {"object_id": oid, "size_bytes": size})
    # Poster/thumbnail in the background: a commit never waits for ffmpeg.
    try:
        _THUMBNAIL_POOL.submit(_safe_generate_thumbnail, dict(row))
    except Exception:
        pass
    total_s = time.perf_counter() - started
    head_ms = head_s * 1000.0
    hash_ms = hash_s * 1000.0
    total_ms = total_s * 1000.0
    response.headers["Server-Timing"] = (
        f"head;dur={head_ms:.1f}, hash;dur={hash_ms:.1f}, total;dur={total_ms:.1f}"
    )
    log.info("commit timings oid=%s bytes=%d head_ms=%.1f hash_ms=%.1f total_ms=%.1f",
             oid, size, head_ms, hash_ms, total_ms)
    result = {
        "id": oid, "status": "available", "size_bytes": size,
        "checksum_sha256": digest, "checksum_algorithm": "sha256",
        # Mêmes mesures que l'en-tête ``Server-Timing`` ci-dessus, mais dans le
        # corps pour le front (l'en-tête reste la source lue par le bench et les
        # logs). Ce sont des mesures de la requête courante, jamais persistées :
        # elles décrivent un commit, pas l'objet.
        "commit_timing": {
            "head_ms": round(head_ms, 3),
            "hash_ms": round(hash_ms, 3),
            "total_ms": round(total_ms, 3),
        },
    }
    # Le cache d'idempotence conserve le corps tel que produit par la requête qui
    # a réellement commité : un rejeu avec la même clé renvoie donc *ses* timings,
    # ce qui est cohérent (c'est bien ce commit-là qui a publié l'objet).
    _cache_set(ck, 200, result)
    return result


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

    _abort_multipart_session(row)
    try:
        s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception:
        # A transient storage error must not block the catalogue transition, but
        # this cleanup is best-effort only: once the row is marked ``aborted`` the
        # reconciliation sweep no longer selects it (api/lifecycle.py::
        # reconcile_pending only scans status='pending'), so the partial bytes are
        # orphaned and are NOT retried automatically. They are detected read-only
        # by GET /admin/orphans and must be cleaned operationally.
        pass
    repo.set_status(oid, ABORTED)
    audit_event("abort", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": ABORTED, "aborted": True}


def _require_public_access_scopes(principal: dict) -> None:
    """Issuing or revoking a public read grant requires read and write.

    A write-only service identity must not gain read access by minting a bearer
    grant for an object it can upload but is not allowed to read.
    """
    if not {OBJECTS_READ, OBJECTS_WRITE}.issubset(effective_scopes(principal)):
        raise HTTPException(status_code=403, detail="forbidden")






def _query_tags(value: str | None) -> list[str]:
    """Normalize a comma-separated tag filter like stored tags (max 10)."""
    if not value:
        return []
    out: list[str] = []
    for part in value.split(","):
        tag = part.strip().lower()
        if tag and tag not in out:
            out.append(tag)
        if len(out) == 10:
            break
    return out




# ---------------------------------------------------------------------------
# Authoritative duplicate scan. The browser sends one fingerprint per file it
# is about to import; the API answers with the *actual* available objects in
# each destination folder. Matching stays in the client: this route supplies
# catalogue truth only, and never guesses a folder from a matching leaf name.
# ---------------------------------------------------------------------------
_DUPLICATE_SCAN_MAX_ITEMS = 5000
_DUPLICATE_SCAN_PAGE = 1000
_DUPLICATE_SCAN_CAP = 20000
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize_parent_path(value: str) -> str:
    """Exact backend twin of web/src/lib/folderTree.ts::normalizeRelativePath."""
    return "/".join(
        part for part in value.replace("\\", "/").split("/")
        if part not in ("", ".", "..")
    )


class DuplicateScanItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parentPath: str
    name: str = Field(min_length=1)
    sizeBytes: int = Field(ge=0)
    sha256: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_HEX.fullmatch(value):
            raise ValueError("sha256 must be 64 hexadecimal characters")
        return value


class DuplicateScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[DuplicateScanItemIn] = Field(max_length=_DUPLICATE_SCAN_MAX_ITEMS)


def _resolve_duplicate_scan_paths(
    *, owner_id: str, paths: list[str],
) -> tuple[dict[str, str | None], list[str]]:
    """Resolve normalized paths to folder ids through one strict parent chain.

    ``repo.list_folders`` is owner-scoped; a child is only looked up under the
    parent id resolved on the previous step. A missing ancestor therefore puts
    the whole path in ``unresolved`` instead of guessing from a same-named
    folder elsewhere in the tree. The empty path (space root) maps to ``None``.
    """
    by_parent: dict[str | None, dict[str, str]] = {}

    def children(parent_id: str | None) -> dict[str, str]:
        if parent_id not in by_parent:
            by_parent[parent_id] = {
                row["name"]: row["id"]
                for row in repo.list_folders(owner_id=owner_id, parent_id=parent_id)
            }
        return by_parent[parent_id]

    resolved: dict[str, str | None] = {}
    unresolved: list[str] = []
    for path in paths:
        if not path:
            resolved[path] = None
            continue
        current: str | None = None
        for part in path.split("/"):
            found = children(current).get(part)
            if found is None:
                break
            current = found
        else:
            resolved[path] = current
            continue
        unresolved.append(path)
    return resolved, unresolved


def _duplicate_scan_objects(scope: dict, folder_filter: str) -> list[dict]:
    """All available objects in one destination, paged with a hard cap."""
    rows: list[dict] = []
    for offset in range(0, _DUPLICATE_SCAN_CAP, _DUPLICATE_SCAN_PAGE):
        page = repo.list_objects(
            **scope, folder_id=folder_filter, status="available",
            limit=_DUPLICATE_SCAN_PAGE, offset=offset,
            sort="created_at", order="asc",
        )
        rows.extend(
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "size_bytes": row["size_bytes"],
                "checksum_sha256": row["checksum_sha256"],
            }
            for row in page
        )
        if len(page) < _DUPLICATE_SCAN_PAGE:
            break
    return rows


@app.post("/api/v1/objects/duplicate-scan")
def duplicate_scan(
    body: DuplicateScanIn,
    principal: dict = Depends(authorize(OBJECTS_READ)),
):
    # Normalize exactly like the browser planner, then collapse duplicates: one
    # authoritative listing per destination path, whatever the item count.
    paths = list(dict.fromkeys(
        _normalize_parent_path(item.parentPath) for item in body.items
    ))
    resolved, unresolved = _resolve_duplicate_scan_paths(
        owner_id=principal["id"], paths=paths,
    )
    unresolved_set = set(unresolved)
    scope = _object_scope(principal)
    by_parent: dict[str, list[dict]] = {}
    for path in paths:
        if path in unresolved_set:
            continue
        # repo.list_objects reads "" as "folder_id IS NULL"; None would mean
        # "no folder filter" and leak objects filed elsewhere in the space.
        by_parent[path] = _duplicate_scan_objects(scope, resolved[path] or "")
    audit_event("duplicate-scan", principal["id"], "success", {
        "item_count": len(body.items),
        "unresolved_count": len(unresolved),
    })
    return {"byParent": by_parent, "unresolved": sorted(unresolved)}




def _audio_job_public(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "object_id": row.get("object_id"),
        "space_id": row.get("space_id"),
        "status": row.get("status"),
        "attempts": row.get("attempts", 0),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "confidence": row.get("confidence"),
        "suggested_category": row.get("suggested_category"),
        "suggested_themes": json.loads(row["suggested_themes"]) if row.get("suggested_themes") else [],
        "suggested_language": row.get("suggested_language"),
        "suggested_folder": row.get("suggested_folder"),
        "quality": json.loads(row["quality_json"]) if row.get("quality_json") else None,
        "transcript_excerpt": row.get("transcript_excerpt"),
        "reason": row.get("reason"),
        "error": row.get("error"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "object": {
            "display_name": row.get("display_name"),
            "content_type": row.get("content_type"),
            "size_bytes": row.get("size_bytes"),
        } if row.get("display_name") is not None else None,
    }


@app.get("/api/v1/audio-classifications")
def list_audio_classifications(
    principal: dict = Depends(authorize(OBJECTS_READ)),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    rows = repo.list_audio_classification_jobs(
        principal["space_id"], status=status, limit=limit, offset=offset
    )
    return {"items": [_audio_job_public(r) for r in rows]}


@app.get("/api/v1/audio-classifications/feedback")
def audio_classification_feedback(
    principal: dict = Depends(authorize(OBJECTS_READ)),
    limit: int = Query(default=500, ge=1, le=1000),
):
    rows = repo.list_audio_classification_jobs(principal["space_id"], limit=limit, offset=0)
    total = len(rows)
    by_status = {}
    by_category = {}
    low_conf = []
    rejected = []
    for r in rows:
        r = _as_dict(r)
        st = r.get("status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1
        cat = r.get("suggested_category") or "autre"
        by_category[cat] = by_category.get(cat, 0) + 1
        conf = float(r.get("confidence") or 0)
        item = {
            "id": r.get("id"), "object_id": r.get("object_id"),
            "display_name": (r.get("display_name") or ""),
            "status": st, "suggested_category": cat, "confidence": conf,
            "reason": r.get("reason"), "provider": r.get("provider"),
        }
        if st == "rejected":
            rejected.append(item)
        if conf < 0.6 and st in ("needs_review", "failed", "rejected"):
            low_conf.append(item)
    return {
        "total": total,
        "by_status": by_status,
        "by_category": by_category,
        "rejected": rejected[:100],
        "low_confidence": low_conf[:100],
        "hint": "Utilise les rejected/low_confidence pour ajouter des mots-clés dans api/audio_rules.json puis rebuild l'API.",
    }


@app.get("/api/v1/audio-classifications/{jid}")
def get_audio_classification(jid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    jid = _canonical_id(jid, "job id")
    row = repo.get_audio_classification_job(jid)
    if row is None or row.get("space_id") != principal["space_id"]:
        raise HTTPException(status_code=404, detail="job not found")
    return _audio_job_public(row)


@app.post("/api/v1/audio-classifications/enqueue")
def enqueue_audio_classifications(
    body: AudioClassificationEnqueueIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    if not settings.ai_classification_enabled:
        raise HTTPException(status_code=409, detail="audio classification is disabled")
    enqueued = []
    skipped = []
    for raw in body.object_ids:
        try:
            oid = _canonical_id(raw, "object id")
        except Exception:
            skipped.append({"id": raw, "reason": "invalid_id"})
            continue
        row = repo.get_object(oid, **_object_scope(principal))
        if row is None:
            skipped.append({"id": oid, "reason": "not_found"})
            continue
        row = _as_dict(row)
        if row.get("status") != "available":
            skipped.append({"id": oid, "reason": "not_available"})
            continue
        if not str(row.get("content_type") or "").startswith("audio/"):
            skipped.append({"id": oid, "reason": "not_audio"})
            continue
        jid = repo.enqueue_audio_classification(ids.new_id(), oid, principal["space_id"])
        enqueued.append({"object_id": oid, "job_id": jid})
    if enqueued:
        audit_event("audio_classification.enqueue", principal.get("sub") or principal.get("id"), "ok",
                    {"count": len(enqueued), "space_id": principal.get("space_id")})
    return {"enqueued": enqueued, "skipped": skipped}


@app.post("/api/v1/audio-classifications/enqueue-unclassified")
def enqueue_unclassified_audio_classifications(
    body: AudioClassificationEnqueueUnclassifiedIn = AudioClassificationEnqueueUnclassifiedIn(),
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    if not settings.ai_classification_enabled:
        raise HTTPException(status_code=409, detail="audio classification is disabled")
    ids_to_enqueue = repo.list_unclassified_audio_object_ids(principal["space_id"], limit=body.limit)
    enqueued = []
    for oid in ids_to_enqueue:
        jid = repo.enqueue_audio_classification(ids.new_id(), oid, principal["space_id"])
        enqueued.append({"object_id": oid, "job_id": jid})
    if enqueued:
        audit_event("audio_classification.enqueue_unclassified", principal.get("sub") or principal.get("id"), "ok",
                    {"count": len(enqueued), "space_id": principal.get("space_id")})
    return {"enqueued": enqueued, "count": len(enqueued)}


@app.post("/api/v1/audio-classifications/{jid}/review")
def review_audio_classification(
    jid: str,
    body: AudioClassificationReviewIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE)),
):
    jid = _canonical_id(jid, "job id")
    row = repo.get_audio_classification_job(jid)
    if row is None or row.get("space_id") != principal["space_id"]:
        raise HTTPException(status_code=404, detail="job not found")
    status = "accepted" if body.action == "accept" else "rejected"
    ok = repo.review_audio_classification_job(jid, status=status, reviewed_by=principal.get("sub") or principal.get("id"))
    if not ok:
        raise HTTPException(status_code=409, detail="job cannot be reviewed")

    # Save human correction for learning loop.
    correction = {}
    if body.corrected_category:
        correction["corrected_category"] = body.corrected_category.strip().lower()[:64]
    if body.corrected_themes is not None:
        correction["corrected_themes"] = [str(t).strip().lower()[:32] for t in body.corrected_themes if str(t).strip()][:8]
    if body.corrected_folder:
        correction["corrected_folder"] = body.corrected_folder.strip()[:256]
    if correction:
        try:
            existing_result = json.loads(row.get("result_json") or "{}")
        except Exception:
            existing_result = {}
        existing_result["correction"] = correction
        existing_result["corrected_at"] = repo.now()
        repo.save_audio_classification_correction(jid, json.dumps(existing_result, ensure_ascii=False))

    # On accept, apply suggested/corrected tags only when confidence is high enough.
    applied_tags = False
    if status == "accepted":
        conf = float(row.get("confidence") or 0)
        effective_cat = correction.get("corrected_category") or row.get("suggested_category")
        effective_themes = correction.get("corrected_themes")
        if effective_themes is None:
            try:
                effective_themes = json.loads(row.get("suggested_themes") or "[]")
            except Exception:
                effective_themes = []
        if conf >= 0.80 or correction.get("corrected_category"):
            oid = row.get("object_id")
            obj = repo.get_object_global(oid) if oid else None
            if obj is not None:
                tags = []
                if effective_cat:
                    tags.append(f"categorie-{effective_cat}")
                for t in effective_themes[:3]:
                    t = str(t).strip().lower().replace(" ", "-")
                    if t:
                        tags.append(f"theme-{t}")
                lang = row.get("suggested_language")
                if lang:
                    tags.append(f"langue-{lang}")
                existing = repo.get_object_tags(oid)
                merged = list(existing)
                for t in tags:
                    if t not in merged:
                        merged.append(t)
                repo.set_object_tags(oid, merged[:20])
                applied_tags = True
    fresh = repo.get_audio_classification_job(jid)
    audit_event("audio_classification.review", principal.get("sub") or principal.get("id"), "ok",
                {"job_id": jid, "action": body.action, "applied_tags": applied_tags, "space_id": principal.get("space_id")})
    out = _audio_job_public(fresh or row)
    out["applied_tags"] = applied_tags
    return out














@app.post("/api/v1/objects/{oid}/purge")
def purge(oid: str, principal: dict = Depends(authorize(OBJECTS_PURGE))):
    # Destructive: requires objects:purge (operator/admin), not merely a session.
    # A storage failure keeps the catalogue row and surfaces 502 (M06): the
    # reference is never dropped on a failed backend delete.
    from .lifecycle import PurgeBlockedError, StorageDeleteError
    oid = _canonical_id(oid, "object id")
    try:
        purged = purge_object(repo, s3ops, oid, **_object_scope(principal))
    except PurgeBlockedError:
        audit_event("purge", principal["id"], "blocked", {"object_id": oid})
        raise HTTPException(status_code=409, detail="purge blocked by keep-forever revisions")
    except StorageDeleteError:
        audit_event("purge", principal["id"], "storage_failure", {"object_id": oid})
        raise HTTPException(status_code=502, detail="storage delete failed")
    if not purged:
        raise HTTPException(status_code=404, detail="object not found")
    audit_event("purge", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "status": "purged"}




# Media types that may be rendered in place. Anything that can carry script or
# markup (text/html, image/svg+xml, xml, ...) is deliberately absent: a
# user-uploaded file must never execute from the storage origin. Everything not
# listed here is offered as a download instead (415 from preview-intent).
PREVIEWABLE_CONTENT_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
    "application/pdf",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg",
    "audio/webm", "audio/mp4", "audio/aac", "audio/flac",
    # Video is served untouched, inline, from the S3 origin: the browser streams
    # it with HTTP Range requests and there is no transcoding nor thumbnail.
    "video/mp4", "video/webm", "video/ogg",
})


def is_previewable(content_type: str) -> bool:
    """True when `content_type` (parameters ignored) may be previewed inline."""
    return (content_type or "").split(";", 1)[0].strip().lower() in PREVIEWABLE_CONTENT_TYPES


def _assert_bytes_intact(oid: str, row: dict) -> None:
    """Invariant S10: published bytes must still match the catalogue.

    A divergence marks the object ``suspect`` and blocks reading until an
    operator re-verifies it (``POST /api/v1/admin/objects/{oid}/reverify``).
    An unreachable backend is *not* treated as corruption: availability wins
    over a transient HEAD failure, as before.
    """
    try:
        head = s3ops.head_object(Bucket=row["bucket"], Key=row["object_key"])
        if int(head.get("ContentLength", -1)) != int(row["size_bytes"]) or (
            settings.require_sse and head.get("ServerSideEncryption") != SSE_ALGORITHM
        ):
            repo.set_status(oid, "suspect")
            raise HTTPException(status_code=409, detail="object integrity suspect")
    except HTTPException:
        raise
    except Exception:
        pass




# ---------------------------------------------------------------------------
# Generated previews: video poster / image thumbnail + duration.
# ---------------------------------------------------------------------------
_THUMBNAIL_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aura-thumb")
_THUMBNAIL_LOCKS: dict[str, threading.Lock] = {}
_THUMBNAIL_LOCKS_LOCK = threading.Lock()


def _thumbnail_supported(content_type: str) -> bool:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    if value == "image/svg+xml":
        return False
    return value.startswith("image/") or value.startswith("video/")


def _run_ffmpeg(args: list[str], timeout: int = 45) -> bytes:
    result = subprocess.run(
        args, capture_output=True, timeout=timeout, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(
            (result.stderr or b"").decode("utf-8", "replace")[:300]
        )
    return result.stdout


def _probe_duration(url: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", url],
            capture_output=True, timeout=20, check=False,
        )
        return round(float(out.stdout.strip()), 2) if out.returncode == 0 else None
    except Exception:
        return None


def _generate_thumbnail(row: dict) -> str | None:
    """Best-effort poster/thumbnail stored next to the object.

    Runs ffmpeg against a short-lived presigned GET (Range-capable), so the API
    never streams the whole file through Python. Returns the new S3 key, or
    None when ffmpeg is unavailable or the media cannot be decoded.
    """
    if not _thumbnail_supported(row.get("content_type") or ""):
        return None
    if not shutil.which("ffmpeg"):
        return None
    is_video = (row.get("content_type") or "").startswith("video/")
    # Sign against the internal endpoint: ffmpeg runs inside the API container,
    # which cannot resolve the public S3 hostname (and should not depend on it).
    url = presigned_get(
        s3ops, row["bucket"], row["object_key"], 300,
        content_disposition="inline", content_type=row.get("content_type"),
    )
    args = ["ffmpeg", "-v", "error"]
    if is_video:
        # A frame around 10 % of the video, bounded so short clips still work.
        duration = _probe_duration(url) or 0
        seek = min(max(duration * 0.1, 0), 10) if duration else 1
        args += ["-ss", f"{seek:.2f}"]
    args += ["-i", url, "-frames:v", "1", "-vf", "scale=480:-2",
             "-f", "mjpeg", "-q:v", "4", "pipe:1"]
    jpg = _run_ffmpeg(args)
    duration = _probe_duration(url) if is_video else None
    key = f"{row['object_key']}.thumb.jpg"
    s3ops.put_object(
        Bucket=row["bucket"], Key=key, Body=jpg, ContentType="image/jpeg",
        **({"ServerSideEncryption": SSE_ALGORITHM} if settings.require_sse else {}),
    )
    repo.set_object_thumbnail(row["id"], key, duration)
    return key


def _safe_generate_thumbnail(row: dict) -> None:
    lock = None
    with _THUMBNAIL_LOCKS_LOCK:
        lock = _THUMBNAIL_LOCKS.setdefault(row["id"], threading.Lock())
    try:
        with lock:
            fresh = repo.get_object(row["id"], space_id=row["space_id"])
            fresh = _as_dict(fresh) if fresh is not None else None
            if fresh and not fresh.get("thumbnail_key") and fresh["status"] == AVAILABLE:
                _generate_thumbnail(fresh)
    except Exception as exc:  # never fail a commit because a poster failed
        log.info("thumbnail generation failed oid=%s: %s", row["id"], exc)
    finally:
        with _THUMBNAIL_LOCKS_LOCK:
            _THUMBNAIL_LOCKS.pop(row["id"], None)


@app.get("/api/v1/objects/{oid}/thumbnail")
def object_thumbnail(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    """Redirect to a generated thumbnail/poster, or 404 when none exists.

    The browser loads this directly in an `<img>` (same-origin cookies), so a
    302 is enough and the API still never proxies object bytes.
    """
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="thumbnail not found")
    if not row.get("thumbnail_key") and _thumbnail_supported(row["content_type"]):
        # Lazy first generation (large asynchronous commits have no poster yet).
        _safe_generate_thumbnail(row)
        fresh = repo.get_object(oid, **_object_scope(principal))
        row = _as_dict(fresh) if fresh is not None else row
    key = row.get("thumbnail_key")
    if not key:
        raise HTTPException(status_code=404, detail="thumbnail not found")
    url = presigned_get(
        s3, row["bucket"], key, 300,
        content_disposition="inline", content_type="image/jpeg",
    )
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
    })


def _classify_published_audio(row: dict) -> bool:
    """Add missing public facets to a newly published audio object."""
    if not str(row.get("content_type") or "").lower().startswith("audio/"):
        return False
    folder_name = ""
    if row.get("folder_id"):
        mark = "?" if settings.db_backend == "sqlite" else "%s"
        folder = repo.conn.execute(
            f"SELECT name FROM folders WHERE id = {mark}", (row["folder_id"],),
        ).fetchone()
        folder_name = str(folder["name"]) if folder else ""
    classification = public_classification.classify_public_item(
        row["display_name"], folder_name,
    )
    existing = repo.get_object_tags(row["id"])
    merged = public_classification.merge_public_tags(existing, classification)
    if set(merged) == set(existing):
        return False
    repo.set_object_tags(row["id"], merged)
    return True




@app.post("/api/v1/objects/{oid}/replace")
def replace_object_content(
    oid: str, body: ReplaceObjectIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    """Point an object at another object's bytes, keeping id, slug and URL.

    This is how a published course file is updated without touching the sites:
    upload the new version normally, then replace. The source row is removed and
    the target's previous bytes are deleted (no automatic rollback yet).
    """
    oid = _canonical_id(oid, "object id")
    source_id = _canonical_id(body.source_object_id, "source object id")
    if source_id == oid:
        raise HTTPException(status_code=422, detail="source must be another object")
    target = repo.get_object(oid, **_object_scope(principal))
    source = repo.get_object(source_id, **_object_scope(principal))
    if target is None or source is None:
        raise HTTPException(status_code=404, detail="object not found")
    target = _as_dict(target)
    source = _as_dict(source)
    if target["status"] != AVAILABLE or source["status"] != AVAILABLE:
        raise HTTPException(status_code=409, detail="both objects must be available")
    if source.get("public_slug"):
        # Deleting a published source would silently kill another public URL.
        raise HTTPException(status_code=409, detail="source object is published")
    old_bucket, old_key = target["bucket"], target["object_key"]
    old_thumb = target.get("thumbnail_key")
    repo.replace_object_content(oid, source_id, source)
    try:
        s3ops.delete_object(Bucket=old_bucket, Key=old_key)
    except Exception:
        pass
    if old_thumb and old_thumb != source.get("thumbnail_key"):
        try:
            s3ops.delete_object(Bucket=old_bucket, Key=old_thumb)
        except Exception:
            pass
    audit_event("object.replace", principal["id"], "success", {
        "object_id": oid, "source_object_id": source_id,
        "size_bytes": source["size_bytes"],
    })
    updated = _as_dict(repo.get_object(oid, **_object_scope(principal)))
    if not updated.get("thumbnail_key"):
        try:
            _THUMBNAIL_POOL.submit(_safe_generate_thumbnail, updated)
        except Exception:
            pass
    return _object_public(updated)


def _guard_public_media_slug(
    slug: str, request: Request, require_premium: bool = False,
) -> None:
    """Apply the published-media policy before any catalogue lookup.

    Streaming (``/m/{slug}``, HLS, subtitles) only needs a public session:
    signed-in free accounts may listen to the whole book. An explicit download
    (``/d/{slug}``) is the paid capability and always checks the plan, even for
    a slug allowlisted for public embeds.
    """
    if not _PUBLIC_SLUG_RE.fullmatch(slug or ""):
        raise HTTPException(status_code=404, detail="not found")
    # D-08: a restricted slug is not an access-control bypass. Answer 404 before
    # any session check, lookup, presign, view event or successful-access audit.
    if slug in settings.public_media_restricted_slugs:
        raise HTTPException(status_code=404, detail="not found")
    paid = require_premium and settings.public_download_require_premium
    open_slug = slug in settings.public_media_open_slugs
    # Check before the lookup so an anonymous caller cannot probe which slugs
    # exist. Trusted course embeds can be allowlisted explicitly with
    # AURA_PUBLIC_MEDIA_OPEN_SLUGS: they stay public for *listening* only.
    if paid:
        _require_premium(request)
    elif settings.public_media_require_auth and not open_slug:
        try:
            authenticate_public(request)
        except HTTPException:
            raise HTTPException(status_code=401, detail="authentication required")


@app.get("/m/{slug}")
def public_media(slug: str, request: Request):
    """Permanent published URL: 302 to a short-lived presigned GET, or 404.

    Only an object with `published_at` resolves. The slug survives content
    replacement, so course sites embed one stable URL. Bytes still come from
    the storage host; the API never proxies them.
    """
    _public_rate_check("media", request)
    _guard_public_media_slug(slug, request)
    row = repo.get_object_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE or not row.get("published_at"):
        raise HTTPException(status_code=404, detail="not found")
    set_request_principal(row["space_id"], None)
    inline = is_previewable(row["content_type"])
    # Published media is streamed with Range requests for hours: the short
    # upload-intent TTL would expire mid-book. Only this route gets the longer
    # TTL; upload/download intents keep their own limits.
    url = presigned_get(
        s3, row["bucket"], row["object_key"], settings.public_media_ttl,
        content_disposition=shares.content_disposition_header(
            "inline" if inline else "attachment", row["display_name"]
        ),
        content_type=row["content_type"],
    )
    _record_object_event(row["id"], int(row["size_bytes"]), "view")
    audit_event("public-access", None, "success",
                {"object_id": row["id"], "slug": slug})
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/d/{slug}")
def public_download(slug: str, request: Request):
    """Explicit, premium-only download of a published book.

    ``/m/{slug}`` stays a streaming URL for every signed-in listener. This
    route is the one the offline button uses: it always forces an attachment
    response and checks the product plan, including for allowlisted embeds.
    """
    _public_rate_check("media", request)
    if not _PUBLIC_SLUG_RE.fullmatch(slug or ""):
        raise HTTPException(status_code=404, detail="not found")
    if slug in settings.public_media_restricted_slugs:
        raise HTTPException(status_code=404, detail="not found")
    if settings.public_download_require_premium:
        _require_premium(request)  # anonymous -> 401, free -> 403
    else:
        try:
            authenticate_public(request)  # never an anonymous download URL
        except HTTPException:
            raise HTTPException(status_code=401, detail="authentication required")
    row = repo.get_object_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE or not row.get("published_at"):
        raise HTTPException(status_code=404, detail="not found")
    set_request_principal(row["space_id"], None)
    url = presigned_get(
        s3, row["bucket"], row["object_key"], settings.public_media_ttl,
        content_disposition=shares.content_disposition_header(
            "attachment", row["display_name"]
        ),
        content_type=row["content_type"],
    )
    _record_object_event(row["id"], int(row["size_bytes"]), "download")
    audit_event("public-download", None, "success",
                {"object_id": row["id"], "slug": slug})
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/a/{token}")
def public_granted_media(token: str, request: Request):
    """Short, revocable media URL issued by a service after an entitlement check.

    Gate D-08: paid or rights-restricted content must never rely on the permanent
    ``/m/{slug}`` capability. The token is a bearer capability, stored only as a
    SHA-256 fingerprint and never logged.
    """
    _public_rate_check("media", request)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    grant = repo.get_public_access_grant(token_hash)
    now = int(time.time())
    if (
        grant is None or grant["revoked_at"] is not None
        or int(grant["expires_at"]) <= now
    ):
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(repo.get_object_unscoped(grant["object_id"]) or {})
    if not row or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="not found")
    set_request_principal(row["space_id"], None)
    inline = is_previewable(row["content_type"])
    # A storage URL must never outlive the grant that authorised its creation.
    # Recompute after the catalogue read: a slow database must not turn an
    # initially valid grant into a storage URL issued after its expiration. Keep
    # a one-second margin because presigning starts its own TTL clock.
    remaining = int(grant["expires_at"] - time.time())
    if remaining <= 1:
        raise HTTPException(status_code=404, detail="not found")
    redirect_ttl = min(settings.public_media_ttl, remaining - 1)
    url = presigned_get(
        s3, row["bucket"], row["object_key"], redirect_ttl,
        content_disposition=shares.content_disposition_header(
            "inline" if inline else "attachment", row["display_name"]
        ),
        content_type=row["content_type"],
    )
    _record_object_event(row["id"], int(row["size_bytes"]), "view")
    audit_event("public-access-grant", grant["actor_id"], "redeemed",
                {"object_id": row["id"]})
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff",
    })


@app.get("/covers/{oid}.jpg")
def public_cover(oid: str, request: Request):
    """Cover art extracted locally from a published audio file, or 404.

    No external cover API is contacted: the JPEG is stored next to the object
    in the same bucket by scripts/generate_audiobook_covers.py.
    """
    _public_rate_check("cover", request)
    oid = _canonical_id(oid, "object id")
    row = _as_dict(repo.get_object_unscoped(oid) or {})
    if (
        not row or row.get("status") != AVAILABLE
        or not row.get("published_at") or not row.get("cover_key")
    ):
        raise HTTPException(status_code=404, detail="not found")
    set_request_principal(row.get("space_id"), None)
    url = presigned_get(
        s3, row["bucket"], row["cover_key"], settings.intent_ttl,
        content_disposition="inline", content_type="image/jpeg",
    )
    # The redirect target is valid for `intent_ttl`; letting the browser reuse
    # the redirect for 5 minutes spares a signed URL per cover on every visit
    # (a unpublished cover may stay visible that long in a warm cache).
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "private, max-age=300", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex, nofollow",
    })


_HLS_SEGMENT_RE = re.compile(r"seg_[0-9]{5}\.ts")


def _hls_playlist(row: dict, base: str) -> str:
    """Fetch the stored playlist and rewrite segment URIs to ``base``."""
    if not row.get("hls_prefix"):
        raise HTTPException(status_code=404, detail="hls not ready")
    try:
        body = s3ops.get_object(
            Bucket=row["bucket"], Key=f"{row['hls_prefix']}/index.m3u8"
        )["Body"].read().decode("utf-8")
    except Exception:
        raise HTTPException(status_code=404, detail="hls not ready")
    lines = []
    for line in body.splitlines():
        if line and not line.startswith("#"):
            lines.append(f"{base}/{line}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


@app.post("/api/v1/objects/{oid}/hls")
def prepare_hls(oid: str, principal: dict = Depends(authorize(OBJECTS_WRITE, human=True))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE:
        raise HTTPException(status_code=409, detail="object not available")
    if not (row["content_type"] or "").startswith("video/"):
        raise HTTPException(status_code=422, detail="hls is only available for video")
    repo.set_object_hls(oid, "queued", row.get("hls_prefix"))
    repo.enqueue_media_job(ids.new_id(), oid, "hls")
    audit_event("object.hls", principal["id"], "success", {"object_id": oid})
    return {"id": oid, "hls_status": "queued"}


@app.get("/api/v1/objects/{oid}/hls/status")
def hls_status(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    row = _as_dict(row)
    job = repo.get_media_job(oid, "hls") or {}
    return {
        "object_id": oid, "status": row.get("hls_status") or "none",
        "error": job.get("error"), "attempts": job.get("attempts") or 0,
    }


@app.get("/api/v1/objects/{oid}/hls/index.m3u8")
def hls_playlist(oid: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None or row["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="hls not ready")
    text = _hls_playlist(_as_dict(row), f"/api/v1/objects/{oid}/hls")
    return Response(content=text, media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/v1/objects/{oid}/hls/{segment}")
def hls_segment(oid: str, segment: str, principal: dict = Depends(authorize(OBJECTS_READ))):
    oid = _canonical_id(oid, "object id")
    if not _HLS_SEGMENT_RE.fullmatch(segment):
        raise HTTPException(status_code=404, detail="not found")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None or not row.get("hls_prefix"):
        raise HTTPException(status_code=404, detail="not found")
    url = presigned_get(
        s3, row["bucket"], f"{row['hls_prefix']}/{segment}", 300,
        content_type="video/mp2t",
    )
    return RedirectResponse(url, status_code=302)


@app.put("/api/v1/objects/{oid}/subtitle")
def set_subtitle(
    oid: str, body: SubtitleIn,
    principal: dict = Depends(authorize(OBJECTS_WRITE, human=True)),
):
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    if body.subtitle_object_id is not None:
        sub = repo.get_object(body.subtitle_object_id, **_object_scope(principal))
        if sub is None or sub["status"] != AVAILABLE:
            raise HTTPException(status_code=404, detail="subtitle object not found")
        sub = _as_dict(sub)
        name = (sub["display_name"] or "").lower()
        if not (name.endswith(".vtt") or sub["content_type"] == "text/vtt"):
            raise HTTPException(status_code=422, detail="subtitle must be a .vtt file")
    repo.set_object_subtitle(oid, body.subtitle_object_id)
    audit_event("object.subtitle", principal["id"], "success",
                {"object_id": oid, "subtitle_object_id": body.subtitle_object_id})
    return _object_public(repo.get_object(oid, **_object_scope(principal)))


@app.get("/hls/{slug}.m3u8")
def public_hls_playlist(slug: str, request: Request):
    _public_rate_check("hls", request)
    _guard_public_media_slug(slug, request)
    row = repo.get_object_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE or not row.get("published_at") or not row.get("hls_prefix"):
        raise HTTPException(status_code=404, detail="not found")
    text = _hls_playlist(row, f"/hls/{slug}")
    return Response(content=text, media_type="application/vnd.apple.mpegurl",
                    headers={
                        "Cache-Control": "no-store",
                        "Referrer-Policy": "no-referrer",
                        "X-Content-Type-Options": "nosniff",
                        "X-Robots-Tag": "noindex, nofollow",
                    })


@app.get("/hls/{slug}/{segment}")
def public_hls_segment(slug: str, segment: str, request: Request):
    _public_rate_check("hls", request)
    _guard_public_media_slug(slug, request)
    if not _HLS_SEGMENT_RE.fullmatch(segment):
        raise HTTPException(status_code=404, detail="not found")
    row = repo.get_object_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(row)
    if row["status"] != AVAILABLE or not row.get("published_at") or not row.get("hls_prefix"):
        raise HTTPException(status_code=404, detail="not found")
    url = presigned_get(
        s3, row["bucket"], f"{row['hls_prefix']}/{segment}", 300,
        content_type="video/mp2t",
    )
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow",
    })


@app.get("/m/{slug}/subtitles.vtt")
def public_subtitle(slug: str, request: Request):
    _public_rate_check("subtitle", request)
    _guard_public_media_slug(slug, request)
    row = repo.get_object_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row = _as_dict(row)
    if (
        row["status"] != AVAILABLE or not row.get("published_at")
        or not row.get("subtitle_object_id")
    ):
        raise HTTPException(status_code=404, detail="not found")
    sub = repo.get_object_global(row["subtitle_object_id"])
    if sub is None or sub["status"] != AVAILABLE:
        raise HTTPException(status_code=404, detail="not found")
    sub = _as_dict(sub)
    url = presigned_get(
        s3, sub["bucket"], sub["object_key"], 300,
        content_disposition="inline", content_type="text/vtt",
    )
    return RedirectResponse(url, status_code=302, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow",
    })


# ---------------------------------------------------------------------------
# Tags and ordered packs (Sprint 2).
# ---------------------------------------------------------------------------
def _collection_public(col: dict) -> dict:
    return {
        "id": col["id"], "slug": col["slug"], "title": col["title"],
        "description": col.get("description") or "",
        "published_at": col.get("published_at"),
        "published": bool(col.get("published_at")),
        "item_count": int(col.get("item_count") or 0),
        "created_at": col["created_at"], "updated_at": col["updated_at"],
    }


def _owned_collection(cid: str, principal: dict) -> dict:
    cid = _canonical_id(cid, "collection id")
    col = repo.get_collection(cid)
    if col is None or col["owner_id"] != principal["id"]:
        raise HTTPException(status_code=404, detail="collection not found")
    return _as_dict(col)


















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












# ---------------------------------------------------------------------------
# Folder share links. Same human-only, expiring, revocable capability as an
# object share, but scoped to a folder subtree (subfolders are always included).
# The public routes live outside /api/v1 under /f/.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Administration (#35, #36, #38): require the admin:* capabilities.
# ---------------------------------------------------------------------------
class CoverSelectionIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=64)
    candidate_url: str | None = Field(default=None, max_length=2048)
    model_config = ConfigDict(extra="forbid")


class CoverSearchIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=64)
    isbn: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=12, ge=1, le=20)
    model_config = ConfigDict(extra="forbid")


class CoverApplyIn(BaseModel):
    dry_run: bool = True
    confirm: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    model_config = ConfigDict(extra="forbid")


class EmblematicCoverIn(BaseModel):
    emblematic: bool
    model_config = ConfigDict(extra="forbid")


@app.get("/api/v1/admin/cover-candidates")
def admin_cover_candidates(principal: dict = Depends(authorize(ADMIN_READ))):
    """Operator review of external cover candidates. Never publishes anything."""
    from . import cover_review as cr

    review = cr.public_review(cr.read_review())
    # Display policy, not review state: read the curation flag from the
    # catalogue so the admin can toggle real artwork per book.
    for book in review["books"]:
        obj = repo.get_object_unscoped(str(book.get("object_id") or ""))
        book["emblematic_cover"] = bool(obj and obj.get("emblematic_cover"))
    return review


@app.put("/api/v1/admin/objects/{oid}/emblematic-cover")
def admin_set_emblematic_cover(
    oid: str, body: EmblematicCoverIn,
    principal: dict = Depends(authorize(ADMIN_WRITE)),
):
    """Curate whether one book may show its real cover art on the portal."""
    oid = _canonical_id(oid, "object id")
    row = repo.get_object(oid, **_object_scope(principal))
    if row is None:
        raise HTTPException(status_code=404, detail="object not found")
    repo.set_object_emblematic(oid, body.emblematic)
    audit_event("admin.cover.emblematic", principal["id"], "success", {
        "object_id": oid,
        "emblematic": bool(body.emblematic),
    })
    return {"id": oid, "emblematic_cover": bool(body.emblematic)}


@app.post("/api/v1/admin/covers/select")
def admin_select_cover(body: CoverSelectionIn,
                       principal: dict = Depends(authorize(ADMIN_WRITE))):
    """Record or clear one operator decision. The cover is not published yet."""
    from . import cover_review as cr

    path = cr.review_path()
    with cr.review_lock(path):
        review = cr.read_review(path, strict=True)
        try:
            book = cr.select_cover(review, body.object_id, body.candidate_url)
        except LookupError:
            raise HTTPException(status_code=404, detail="book not in review")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        cr.write_review(review, path)
    audit_event("admin.cover.select", principal["id"], "success", {
        "object_id": body.object_id,
        "chosen": bool(body.candidate_url),
    })
    return {"book": cr.public_review({"books": [book]})["books"][0]}


@app.post("/api/v1/admin/covers/search")
def admin_search_cover(body: CoverSearchIn,
                       principal: dict = Depends(authorize(ADMIN_WRITE))):
    """Search new candidates for one book; ISBN first, then title + author."""
    from . import cover_enrichment as ce
    from . import cover_review as cr

    isbn = (body.isbn or "").strip()
    if isbn and not re.fullmatch(r"[0-9Xx\- ]{8,20}", isbn):
        raise HTTPException(status_code=400, detail="invalid ISBN")
    path = cr.review_path()
    with cr.review_lock(path):
        review = cr.read_review(path, strict=True)
        book = cr.find_book(review, body.object_id)
        if book is None:
            raise HTTPException(status_code=404, detail="book not in review")
        title, author = _split_audio_name(
            str(book.get("display_name") or book.get("title") or "")
        )
        found = ce.search_candidates(title, author, isbn, body.limit)
        chosen_url = book.get("chosen_url")
        if chosen_url and not any(candidate.get("url") == chosen_url for candidate in found):
            previous = next(
                (candidate for candidate in (book.get("candidates") or [])
                 if candidate.get("url") == chosen_url),
                None,
            )
            if previous:
                found.append(previous)
        merged = []
        seen_urls = set()
        for candidate in found + list(book.get("candidates") or []):
            url = candidate.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(candidate)
        book["candidates"] = merged
        book["last_search_at"] = int(time.time())
        book["search_isbn"] = isbn or None
        book["search_title"] = title
        book["search_author"] = author
        cr.write_review(review, path)
        updated = cr.public_review({"books": [book]})["books"][0]
    audit_event("admin.cover.search", principal["id"], "success", {
        "object_id": body.object_id, "isbn": bool(isbn),
        "candidates": len(updated["candidates"]),
    })
    return {"book": updated}


@app.post("/api/v1/admin/covers/apply")
def admin_apply_covers(body: CoverApplyIn,
                       principal: dict = Depends(authorize(ADMIN_WRITE))):
    """Publish the explicitly selected candidates, bounded and resumable."""
    from . import cover_review as cr

    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    path = cr.review_path()
    with cr.review_lock(path):
        review = cr.read_review(path, strict=True)
        out = cr.apply_selected(
            review, dry_run=body.dry_run, limit=body.limit,
        )
        if not body.dry_run:
            cr.write_review(review, path)
    audit_event("admin.cover.apply", principal["id"], "success", out)
    return out


















class OrphanUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=1024)
    upload_id: str = Field(min_length=1, max_length=1024)


class OrphanCleanupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: str = Field(min_length=1, max_length=63)
    keys: list[str] = Field(default_factory=list, max_length=100)
    uploads: list[OrphanUploadIn] = Field(default_factory=list, max_length=100)






# ---------------------------------------------------------------------------
# Observability (M07): audit search, usage, supervision. Reads require
# admin:read; retention pruning requires admin:write. Every value returned is
# measured live from the catalogue, the audit file or the OS — see
# docs/OBSERVABILITY.md for what is (and is not) available.
# ---------------------------------------------------------------------------


















def _space_detail(sid: str) -> dict:
    """Space detail with its application, buckets and attachment counts."""
    row = repo.get_space(sid)
    out = _space_public(row)
    application = repo.get_application(row["application_id"])
    out["application_name"] = application["name"] if application else None
    out["buckets"] = [_bucket_public(b) for b in repo.list_buckets(sid)]
    out["counts"] = repo.space_counts(sid)
    return out


















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














# --- Import jobs ----------------------------------------------------------







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















from .routes_objects_mutations import router as objects_mutations_router  # noqa: E402
app.include_router(objects_mutations_router)
from .routes_shares import router as shares_router  # noqa: E402
app.include_router(shares_router)
from .routes_import_jobs import router as import_jobs_router  # noqa: E402
app.include_router(import_jobs_router)
from .routes_revisions import router as revisions_router  # noqa: E402
app.include_router(revisions_router)
from .routes_public_profile import router as public_profile_router  # noqa: E402
app.include_router(public_profile_router)
from .routes_public_library import router as public_library_router  # noqa: E402
app.include_router(public_library_router)
from .routes_bookmarks_playlists import router as bookmarks_playlists_router  # noqa: E402
app.include_router(bookmarks_playlists_router)
from .routes_admin import router as admin_router  # noqa: E402
app.include_router(admin_router)
from .routes_objects import router as objects_router  # noqa: E402
app.include_router(objects_router)
from .routes_objects_ops import router as objects_ops_router  # noqa: E402
app.include_router(objects_ops_router)
from .routes_folders import router as folders_router  # noqa: E402
app.include_router(folders_router)
