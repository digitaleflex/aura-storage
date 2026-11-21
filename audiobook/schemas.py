"""Pydantic request schemas for the audiobook API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

class DevLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=200)


class WorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=2, max_length=16)
    description: str = Field(default="", max_length=20_000)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)


class ContributorIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    role: Literal["author", "narrator", "translator", "adapter", "illustrator", "other"]
    position: int = Field(default=0, ge=0, le=10_000)
    sort_name: str = Field(default="", max_length=500)


class EditionIn(BaseModel):
    work_id: UUID
    title: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=2, max_length=16)
    description: str = Field(min_length=1, max_length=50_000)
    duration_ms: int = Field(gt=0)
    slug: str | None = Field(default=None, max_length=140)
    publisher: str = Field(default="", max_length=300)
    publication_date: date | None = None
    cover_asset_id: UUID | None = None
    access_model: Literal["free", "paid", "subscription"] = "free"


class AssetIn(BaseModel):
    storage_object_id: str = Field(min_length=1, max_length=200)
    kind: Literal["source", "hls", "cover", "subtitle", "derivative"] = "source"
    content_type: str = Field(default="", max_length=200)
    size_bytes: int = Field(default=-1, ge=-1)
    checksum_sha256: str = Field(default="", max_length=128)
    duration_ms: int | None = Field(default=None, ge=0)
    codec: str = Field(default="", max_length=100)
    status: Literal[
        "initiated", "uploaded", "quarantined", "validating", "ready",
        "rejected", "blocked", "superseded", "deleted",
    ] = "ready"


class TrackIn(BaseModel):
    position: int = Field(ge=1, le=100_000)
    title: str = Field(default="", max_length=500)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    asset_id: UUID | None = None
    status: Literal["pending", "ready", "unavailable", "blocked"] = "ready"


class ChapterIn(BaseModel):
    position: int = Field(ge=1, le=100_000)
    title: str = Field(default="", max_length=500)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class RightsIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    territory_code: str = Field(default="WORLD", min_length=2, max_length=32)
    channel: Literal["stream", "download", "preview"] = "stream"
    status: Literal["planned", "active", "suspended", "expired", "terminated"] = "active"
    contract_id: UUID | None = None
    max_downloads: int | None = Field(default=None, ge=0)
    allowed_formats: list[str] | None = None


class EntitlementIn(BaseModel):
    listener_id: UUID
    source_type: Literal[
        "purchase", "subscription", "free", "promotion", "manual", "personal_import"
    ]
    source_id: str = Field(default="", max_length=200)
    scope_type: Literal["edition", "work", "plan_catalog", "personal_asset"]
    scope_id: str = Field(min_length=1, max_length=200)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: Literal["pending", "active", "suspended", "revoked", "expired", "canceled"] = "active"


class LibraryIn(BaseModel):
    work_id: UUID
    preferred_edition_id: UUID | None = None
    source: Literal["manual", "purchase", "subscription", "import", "promotion"] = "manual"


class SessionIn(BaseModel):
    edition_id: UUID
    device_id: UUID | None = None
    takeover: bool = False


class EventIn(BaseModel):
    event_id: UUID | None = None
    client_seq: int = Field(ge=1, le=2_147_483_647)
    kind: Literal["start", "heartbeat", "seek", "pause", "resume", "ended", "takeover"]
    position_ms: int = Field(ge=0)
    track_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    occurred_at_client: datetime | None = None
    playback_rate: float = Field(default=1.0, ge=0.25, le=4.0)


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    territory_code: str | None = Field(default=None, min_length=2, max_length=32)


class PreferencesIn(BaseModel):
    preferred_languages: list[str] = Field(default_factory=list, max_length=20)
    preferred_category_slugs: list[str] = Field(default_factory=list, max_length=50)
    preferred_authors: list[str] = Field(default_factory=list, max_length=50)
    preferred_narrators: list[str] = Field(default_factory=list, max_length=50)
    min_duration_ms: int | None = Field(default=None, ge=0)
    max_duration_ms: int | None = Field(default=None, ge=0)
    prefer_completed: bool = False


class DeviceIn(BaseModel):
    name: str = Field(default="", max_length=200)
    platform: str = Field(default="", max_length=100)


class PersonalCollectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class PersonalCollectionItemIn(BaseModel):
    work_id: UUID
    position: int = Field(default=0, ge=0, le=100_000)


class CategoryIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class EditorialCollectionIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class EditorialCollectionItemIn(BaseModel):
    edition_id: UUID
    position: int = Field(default=0, ge=0, le=100_000)


class ContractIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    licensor: str = Field(default="", max_length=300)
    territory_scope: str = Field(default="WORLD", min_length=2, max_length=32)
    starts_at: datetime
    ends_at: datetime
    status: Literal["draft", "active", "suspended", "expired", "terminated"] = "draft"
    notes: str = Field(default="", max_length=5000)


class EntitlementRevokeIn(BaseModel):
    reason: str = Field(default="revoked", max_length=500)


# ---------------------------------------------------------------------------
