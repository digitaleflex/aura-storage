"""Pydantic request/response schemas extracted from api.main (#340)."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from . import ids

# Extracted schema module (not imported by api.main): reuse the original
# validators and constants from main instead of duplicating their rules.
from .main import (  # noqa: E402
    APPLICATION_STATUSES, OBJECTS_READ, SPACE_STATUSES,
    _normalize_partner_url, _trim_name, _validate_folder_name,
)


def _canonical_uuid(value: str) -> str:
    """Pydantic validator helper: canonicalize or fail with 422."""
    canonical = ids.canonical(value)
    if canonical is None:
        raise ValueError("must be a canonical UUID v4")
    return canonical

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

_PUBLIC_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _PUBLIC_SLUG_RE.fullmatch(slug):
        raise ValueError(
            "slug must be 2-63 characters: lowercase letters, digits and dashes"
        )
    return slug
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

class TagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)

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
    """Playback position posted by the public player (CSRF-protected)."""
    model_config = ConfigDict(extra="forbid")
    object_id: Uuid4
    position_seconds: float = Field(ge=0, le=864000)

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

class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Bounded so a failed attempt can never inject megabytes into the audit
    # trail (the username is recorded on every failure).
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)

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

class ObjectPatchIn(BaseModel):
    # Object reassignment into a logical folder (#62). `model_fields_set`
    # distinguishes "not sent" from an explicit null (which unfiles the object
    # back to the root level).
    model_config = ConfigDict(extra="forbid")
    folder_id: Uuid4 | None = None

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

class PublicProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=80)

class MasterModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)

class BulkIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1)

class PartUrlsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_numbers: list[int] = Field(min_length=1, max_length=100)

class OrphanUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=1024)
    upload_id: str = Field(min_length=1, max_length=1024)

class OrphanCleanupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: str = Field(min_length=1, max_length=63)
    keys: list[str] = Field(default_factory=list, max_length=100)
    uploads: list[OrphanUploadIn] = Field(default_factory=list, max_length=100)
