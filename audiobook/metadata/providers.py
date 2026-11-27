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


class GoogleBooksMetadataProvider:
    """Google Books volumes, including their front-cover image links."""

    name = "google_books"
    _BASE = "https://www.googleapis.com/books/v1/volumes"
    _IMAGE_SIZES = (
        "extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail",
    )

    def __init__(self, transport: JsonTransport, *, api_key: str = "") -> None:
        self.transport = transport
        self.api_key = clean_text(api_key, limit=200)

    def search(self, query: MetadataQuery) -> list[MetadataCandidate]:
        params: dict[str, Any] = {"maxResults": max(1, min(query.limit, 20))}
        if query.identifier_kind == "isbn" and query.identifier:
            params["q"] = f"isbn:{clean_text(query.identifier, limit=32)}"
        elif query.text:
            params["q"] = f'intitle:"{clean_text(query.text, limit=200)}"'
        elif query.identifier:
            params["q"] = clean_text(query.identifier, limit=200)
        else:
            return []
        if query.language:
            params["langRestrict"] = clean_text(query.language, limit=10)
        if self.api_key:
            params["key"] = self.api_key
        payload = self.transport.get_json(self._BASE, params=params)
        items = payload.get("items")
        if not isinstance(items, list):
            raise MetadataProviderError("Google Books response has no items list")
        candidates: list[MetadataCandidate] = []
        for item in items[: query.limit]:
            if not isinstance(item, dict):
                continue
            candidate = self._normalize(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _normalize(self, item: dict[str, Any]) -> MetadataCandidate | None:
        provider_id = clean_text(item.get("id"), limit=200)
        info = item.get("volumeInfo")
        if not provider_id or not isinstance(info, dict):
            return None
        title = clean_text(info.get("title"), limit=500)
        if not title:
            return None
        authors = info.get("authors")
        if not isinstance(authors, list):
            authors = []
        contributors = tuple(
            MetadataContributor(name=name, role="author", position=index)
            for index, name in enumerate(authors[:20])
            if clean_text(name)
        )
        identifiers: list[ExternalIdentifier] = [
            ExternalIdentifier(kind="google_books", value=provider_id)
        ]
        for entry in info.get("industryIdentifiers") or []:
            if not isinstance(entry, dict):
                continue
            isbn = valid_isbn(entry.get("identifier"))
            if isbn:
                identifiers.append(
                    ExternalIdentifier(
                        kind="isbn13" if len(isbn) == 13 else "isbn10", value=isbn,
                    )
                )
        links = info.get("imageLinks")
        covers: tuple[CoverCandidate, ...] = ()
        if isinstance(links, dict):
            for size in self._IMAGE_SIZES:
                url = clean_text(links.get(size), limit=2048)
                if url.startswith("http://"):
                    url = "https://" + url[len("http://"):]
                if url.startswith("https://"):
                    covers = (CoverCandidate(url=url, provider=self.name),)
                    break
        categories = info.get("categories")
        return MetadataCandidate(
            provider=self.name,
            provider_id=provider_id,
            title=title,
            kind="ebook",
            language=clean_text(info.get("language"), limit=10),
            description=strip_html(info.get("description")),
            publisher=clean_text(info.get("publisher"), limit=300),
            publication_date=normalize_date(info.get("publishedDate")),
            contributors=contributors,
            categories=tuple(
                clean_text(value, limit=200)
                for value in (categories if isinstance(categories, list) else ())
                if clean_text(value, limit=200)
            ),
            identifiers=tuple(dict.fromkeys(identifiers)),
            cover_candidates=covers,
        )
