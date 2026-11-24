"""Provider-independent metadata models and normalization helpers."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

MetadataKind = Literal["ebook", "audiobook", "unknown"]


def clean_text(value: Any, *, limit: int = 20_000) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def strip_html(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"<[^>]*>", " ", text)
    return clean_text(text)


def normalize_language(value: Any) -> str:
    raw = clean_text(value, limit=16).lower().replace("_", "-")
    if not raw:
        return ""
    primary = raw.split("-")[0]
    marc = {
        "ara": "ar",
        "chi": "zh",
        "cze": "cs",
        "dan": "da",
        "dut": "nl",
        "eng": "en",
        "fre": "fr",
        "fra": "fr",
        "ger": "de",
        "deu": "de",
        "gre": "el",
        "ita": "it",
        "jpn": "ja",
        "kor": "ko",
        "por": "pt",
        "rus": "ru",
        "spa": "es",
        "swe": "sv",
        "tur": "tr",
    }
    return marc.get(primary, primary)


def normalize_isbn(value: Any) -> str:
    raw = clean_text(value, limit=32).upper()
    return re.sub(r"[^0-9X]", "", raw)


def isbn10_to_isbn13(value: str) -> str:
    isbn = normalize_isbn(value)
    if len(isbn) != 10 or not isbn[:9].isdigit():
        return ""
    stem = "978" + isbn[:9]
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(stem))
    check = (10 - total % 10) % 10
    return f"{stem}{check}"


def valid_isbn(value: Any) -> str:
    isbn = normalize_isbn(value)
    if len(isbn) == 13 and isbn.isdigit():
        return isbn
    if len(isbn) == 10 and isbn[:9].isdigit() and (isbn[-1].isdigit() or isbn[-1] == "X"):
        return isbn
    return ""


def normalize_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = clean_text(value, limit=32)
    if len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class ExternalIdentifier:
    kind: str
    value: str

    def __post_init__(self) -> None:
        kind = clean_text(self.kind, limit=40).lower()
        value = clean_text(self.value, limit=200)
        if not kind or not value:
            raise ValueError("external identifier kind and value are required")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class MetadataContributor:
    name: str
    role: str = "author"
    position: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", clean_text(self.name, limit=500))
        object.__setattr__(self, "role", clean_text(self.role, limit=40).lower() or "author")
        object.__setattr__(self, "position", max(0, int(self.position)))


@dataclass(frozen=True)
class CoverCandidate:
    url: str
    provider: str
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", clean_text(self.url, limit=2048))
        object.__setattr__(self, "provider", clean_text(self.provider, limit=80))


@dataclass(frozen=True)
class MetadataCandidate:
    provider: str
    provider_id: str
    title: str
    kind: MetadataKind = "unknown"
    original_title: str = ""
    language: str = ""
    description: str = ""
    publisher: str = ""
    publication_date: date | None = None
    contributors: tuple[MetadataContributor, ...] = field(default_factory=tuple)
    categories: tuple[str, ...] = field(default_factory=tuple)
    series: str = ""
    identifiers: tuple[ExternalIdentifier, ...] = field(default_factory=tuple)
    cover_candidates: tuple[CoverCandidate, ...] = field(default_factory=tuple)
    duration_ms: int | None = None
    narrator: str = ""
    confidence: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", clean_text(self.provider, limit=80).lower())
        object.__setattr__(self, "provider_id", clean_text(self.provider_id, limit=200))
        object.__setattr__(self, "title", clean_text(self.title, limit=500))
        object.__setattr__(self, "kind", self.kind)
        object.__setattr__(self, "original_title", clean_text(self.original_title, limit=500))
        object.__setattr__(self, "language", normalize_language(self.language))
        object.__setattr__(self, "description", clean_text(self.description))
        object.__setattr__(self, "publisher", clean_text(self.publisher, limit=300))
        object.__setattr__(self, "series", clean_text(self.series, limit=500))
        object.__setattr__(self, "narrator", clean_text(self.narrator, limit=500))
        object.__setattr__(self, "confidence", max(0, min(100, int(self.confidence))))
        if not self.provider or not self.provider_id or not self.title:
            raise ValueError("provider, provider_id and title are required")
        if self.kind not in {"ebook", "audiobook", "unknown"}:
            raise ValueError("unsupported metadata kind")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contributors"] = [asdict(item) for item in self.contributors]
        payload["categories"] = list(self.categories)
        payload["identifiers"] = [asdict(item) for item in self.identifiers]
        payload["cover_candidates"] = [asdict(item) for item in self.cover_candidates]
        payload["publication_date"] = (
            self.publication_date.isoformat() if self.publication_date else None
        )
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload

    @property
    def payload_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MetadataQuery:
    text: str = ""
    kind: MetadataKind = "unknown"
    language: str = ""
    limit: int = 10
    identifier: str = ""
    identifier_kind: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", clean_text(self.text, limit=500))
        object.__setattr__(self, "language", normalize_language(self.language))
        object.__setattr__(self, "identifier", clean_text(self.identifier, limit=200))
        object.__setattr__(self, "identifier_kind", clean_text(self.identifier_kind, limit=40).lower())
        object.__setattr__(self, "limit", max(1, min(50, int(self.limit))))
        if not self.text and not self.identifier:
            raise ValueError("metadata query requires text or identifier")
        if self.kind not in {"ebook", "audiobook", "unknown"}:
            raise ValueError("unsupported metadata kind")
        if self.identifier and not self.identifier_kind:
            inferred = "isbn" if len(normalize_isbn(self.identifier)) in {10, 13} else "asin"
            object.__setattr__(self, "identifier_kind", inferred)

    def cache_key(self) -> str:
        return "|".join(
            [
                self.text.casefold(),
                self.kind,
                self.language,
                self.identifier_kind,
                self.identifier.casefold(),
                str(self.limit),
            ]
        )


@dataclass(frozen=True)
class MetadataSearchResult:
    items: tuple[MetadataCandidate, ...]
    provider_failures: dict[str, str] = field(default_factory=dict)
    cache_hit: bool = False
