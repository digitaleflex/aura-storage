"""Open Library and iTunes Search metadata adapters."""
from __future__ import annotations

import re
from typing import Any, Protocol

from .models import (
    CoverCandidate,
    ExternalIdentifier,
    MetadataCandidate,
    MetadataContributor,
    MetadataKind,
    MetadataQuery,
    clean_text,
    normalize_date,
    normalize_language,
    normalize_isbn,
    strip_html,
    valid_isbn,
)
from .transport import JsonTransport, MetadataProviderError


class MetadataProvider(Protocol):
    name: str

    def search(self, query: MetadataQuery) -> list[MetadataCandidate]: ...

    def lookup(self, identifier: ExternalIdentifier) -> list[MetadataCandidate]:
        return self.search(
            MetadataQuery(
                identifier=identifier.value,
                identifier_kind=identifier.kind,
                limit=10,
            )
        )


class OpenLibraryMetadataProvider:
    name = "openlibrary"
    _BASE = "https://openlibrary.org"

    def __init__(self, transport: JsonTransport) -> None:
        self.transport = transport

    def search(self, query: MetadataQuery) -> list[MetadataCandidate]:
        term = query.text or query.identifier
        params: dict[str, Any] = {
            "q": term,
            "limit": query.limit,
            "fields": (
                "key,title,author_name,first_publish_year,isbn,publisher,language,"
                "cover_i,edition_key,number_of_pages_median"
            ),
        }
        if query.language:
            params["language"] = query.language
        payload = self.transport.get_json(f"{self._BASE}/search.json", params=params)
        docs = payload.get("docs")
        if not isinstance(docs, list):
            raise MetadataProviderError("Open Library response has no docs list")
        candidates: list[MetadataCandidate] = []
        for doc in docs[: query.limit]:
            if not isinstance(doc, dict):
                continue
            candidate = self._normalize(doc)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _normalize(self, doc: dict[str, Any]) -> MetadataCandidate | None:
        key = clean_text(doc.get("key"), limit=200)
        title = clean_text(doc.get("title"), limit=500)
        if not key or not title:
            return None
        provider_id = key.rsplit("/", 1)[-1]
        authors = doc.get("author_name")
        if not isinstance(authors, list):
            authors = []
        contributors = tuple(
            MetadataContributor(name=name, role="author", position=index)
            for index, name in enumerate(authors[:20])
            if clean_text(name)
        )
        identifiers: list[ExternalIdentifier] = [
            ExternalIdentifier(kind="openlibrary", value=key)
        ]
        isbns = doc.get("isbn")
        if isinstance(isbns, list):
            for raw in isbns:
                isbn = valid_isbn(raw)
                if isbn:
                    identifiers.append(
                        ExternalIdentifier(
                            kind="isbn13" if len(isbn) == 13 else "isbn10",
                            value=isbn,
                        )
                    )
        publishers = doc.get("publisher")
        publisher = clean_text(publishers[0], limit=300) if isinstance(publishers, list) and publishers else ""
        languages = doc.get("language")
        language = ""
        if isinstance(languages, list) and languages:
            language = normalize_language(languages[0])
        cover_id = doc.get("cover_i")
        covers: tuple[CoverCandidate, ...] = ()
        if isinstance(cover_id, int) and cover_id > 0:
            covers = (
                CoverCandidate(
                    url=f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg",
                    provider=self.name,
                ),
            )
        return MetadataCandidate(
            provider=self.name,
            provider_id=provider_id,
            title=title,
            kind="unknown",
            language=language,
            publisher=publisher,
            publication_date=normalize_date(doc.get("first_publish_year")),
            contributors=contributors,
            identifiers=tuple(dict.fromkeys(identifiers)),
            cover_candidates=covers,
        )


class ITunesMetadataProvider:
    name = "itunes"
    _BASE = "https://itunes.apple.com/search"

    def __init__(self, transport: JsonTransport, *, country: str = "FR") -> None:
        self.transport = transport
        self.country = clean_text(country, limit=2).upper() or "FR"

    def search(self, query: MetadataQuery) -> list[MetadataCandidate]:
        media_values = {
            "ebook": ("ebook",),
            "audiobook": ("audiobook",),
            "unknown": ("ebook", "audiobook"),
        }[query.kind]
        candidates: list[MetadataCandidate] = []
        seen: set[tuple[str, str]] = set()
        errors: list[MetadataProviderError] = []
        for media in media_values:
            params = {
                "term": query.text or query.identifier,
                "media": media,
                "entity": media,
                "country": self.country,
                "limit": query.limit,
            }
            try:
                payload = self.transport.get_json(self._BASE, params=params)
            except MetadataProviderError as exc:
                errors.append(exc)
                continue
            results = payload.get("results")
            if not isinstance(results, list):
                errors.append(MetadataProviderError("iTunes response has no results list"))
                continue
            for item in results[:query.limit]:
                if not isinstance(item, dict):
                    continue
                candidate = self._normalize(item, media)
                if candidate is None:
                    continue
                key = (candidate.provider, candidate.provider_id)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
        if not candidates and errors:
            raise errors[0]
        return candidates[:query.limit]

    def _normalize(self, item: dict[str, Any], requested_media: str) -> MetadataCandidate | None:
        provider_id = clean_text(item.get("trackId") or item.get("collectionId"), limit=200)
        title = clean_text(item.get("collectionName") or item.get("trackName"), limit=500)
        if not provider_id or not title:
            return None
        kind: MetadataKind = "audiobook" if requested_media == "audiobook" else "ebook"
        artist = clean_text(item.get("artistName"), limit=500)
        contributors = (
            (MetadataContributor(name=artist, role="author", position=0),) if artist else ()
        )
        categories = item.get("genres")
        if not isinstance(categories, list):
            primary = clean_text(item.get("primaryGenreName"), limit=200)
            categories = [primary] if primary else []
        artwork = clean_text(item.get("artworkUrl100"), limit=2048)
        artwork = re.sub(r"100x100bb", "600x600bb", artwork)
        covers = (
            (CoverCandidate(url=artwork, provider=self.name, width=600, height=600),)
            if artwork
            else ()
        )
        duration = item.get("trackTimeMillis")
        duration_ms = int(duration) if isinstance(duration, (int, float)) and duration >= 0 else None
        return MetadataCandidate(
            provider=self.name,
            provider_id=provider_id,
            title=title,
            kind=kind,
            description=strip_html(item.get("description") or item.get("shortDescription")),
            publisher=clean_text(item.get("copyright"), limit=300),
            publication_date=normalize_date(item.get("releaseDate")),
            contributors=contributors,
            categories=tuple(clean_text(value, limit=200) for value in categories if clean_text(value)),
            identifiers=(ExternalIdentifier(kind="itunes", value=provider_id),),
            cover_candidates=covers,
            duration_ms=duration_ms,
        )
