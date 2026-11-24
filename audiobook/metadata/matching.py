"""Deterministic candidate ranking; never performs an automatic merge."""
from __future__ import annotations

import re
import unicodedata

from .models import (
    MetadataCandidate,
    MetadataQuery,
    isbn10_to_isbn13,
    normalize_isbn,
)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in _fold(value).split() if len(token) > 1}


def _identifiers_match(query: MetadataQuery, candidate: MetadataCandidate) -> bool:
    if not query.identifier:
        return False
    expected_kind = query.identifier_kind
    expected = query.identifier
    if expected_kind == "isbn":
        expected = normalize_isbn(expected)
        expected_isbn13 = expected if len(expected) == 13 else isbn10_to_isbn13(expected)
        for identifier in candidate.identifiers:
            if identifier.kind not in {"isbn10", "isbn13"}:
                continue
            actual = normalize_isbn(identifier.value)
            actual_isbn13 = actual if len(actual) == 13 else isbn10_to_isbn13(actual)
            if actual == expected or (
                expected_isbn13 and actual_isbn13 and expected_isbn13 == actual_isbn13
            ):
                return True
        return False
    return any(
        identifier.kind == expected_kind and identifier.value.casefold() == expected.casefold()
        for identifier in candidate.identifiers
    )


def match_score(query: MetadataQuery, candidate: MetadataCandidate) -> int:
    """Return a 0-100 confidence score for review, not an auto-merge decision."""
    if _identifiers_match(query, candidate):
        return 100
    if not query.text:
        return 0
    wanted_title = _fold(query.text)
    actual_title = _fold(candidate.title)
    if wanted_title and wanted_title == actual_title:
        score = 75
    else:
        wanted_tokens = _tokens(query.text)
        actual_tokens = _tokens(candidate.title)
        if not wanted_tokens or not actual_tokens:
            return 0
        overlap = len(wanted_tokens & actual_tokens) / len(wanted_tokens | actual_tokens)
        score = int(overlap * 60)
    if query.language and candidate.language:
        score += 10 if query.language == candidate.language else -20
    return max(0, min(99, score))


def with_confidence(query: MetadataQuery, candidate: MetadataCandidate) -> MetadataCandidate:
    score = match_score(query, candidate)
    if score == candidate.confidence:
        return candidate
    return MetadataCandidate(
        provider=candidate.provider,
        provider_id=candidate.provider_id,
        title=candidate.title,
        kind=candidate.kind,
        original_title=candidate.original_title,
        language=candidate.language,
        description=candidate.description,
        publisher=candidate.publisher,
        publication_date=candidate.publication_date,
        contributors=candidate.contributors,
        categories=candidate.categories,
        series=candidate.series,
        identifiers=candidate.identifiers,
        cover_candidates=candidate.cover_candidates,
        duration_ms=candidate.duration_ms,
        narrator=candidate.narrator,
        confidence=score,
        fetched_at=candidate.fetched_at,
    )
