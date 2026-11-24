from __future__ import annotations

import pytest

from audiobook.metadata.aggregator import MetadataAggregator
from audiobook.metadata.matching import match_score
from audiobook.metadata.models import (
    ExternalIdentifier,
    MetadataCandidate,
    MetadataQuery,
)
from audiobook.metadata.providers import ITunesMetadataProvider, OpenLibraryMetadataProvider
from audiobook.metadata.transport import MetadataProviderError, UrllibJsonTransport


class FakeTransport:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url, *, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if not self.payloads:
            raise MetadataProviderError("no fake payload left")
        return self.payloads.pop(0)


class FakeProvider:
    def __init__(self, name, candidates, *, fail=False):
        self.name = name
        self.candidates = candidates
        self.fail = fail
        self.calls = 0

    def search(self, query):
        self.calls += 1
        if self.fail:
            raise MetadataProviderError("provider down")
        return list(self.candidates)


def _candidate(provider, provider_id, title, *, confidence=0):
    return MetadataCandidate(
        provider=provider,
        provider_id=provider_id,
        title=title,
        kind="audiobook",
        identifiers=(ExternalIdentifier(kind=provider, value=provider_id),),
        confidence=confidence,
    )


def test_openlibrary_normalizes_authors_isbn_and_cover():
    transport = FakeTransport(
        [
            {
                "docs": [
                    {
                        "key": "/works/OL42W",
                        "title": "Les Voix de la Nuit",
                        "author_name": ["Awa Diallo"],
                        "first_publish_year": 2021,
                        "isbn": ["978-2-07-000001-1", "invalid"],
                        "publisher": ["Éditions Test"],
                        "language": ["fre"],
                        "cover_i": 12345,
                    }
                ]
            }
        ]
    )
    provider = OpenLibraryMetadataProvider(transport)
    query = MetadataQuery(text="Voix Nuit", kind="audiobook", language="fr")
    candidates = provider.search(query)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provider == "openlibrary"
    assert candidate.provider_id == "OL42W"
    assert candidate.language == "fr"
    assert candidate.publisher == "Éditions Test"
    assert candidate.contributors[0].name == "Awa Diallo"
    assert [item.value for item in candidate.identifiers] == [
        "/works/OL42W",
        "9782070000011",
    ]
    assert candidate.cover_candidates[0].url.endswith("/12345-L.jpg")
    assert transport.calls[0][1]["q"] == "Voix Nuit"


def test_itunes_queries_both_media_for_unknown_kind_and_maps_audiobook():
    transport = FakeTransport(
        [
            {
                "results": [
                    {
                        "trackId": 101,
                        "collectionName": "Livre numérique",
                        "artistName": "Auteur",
                        "genres": ["Littérature"],
                        "artworkUrl100": "https://example.test/100x100bb.jpg",
                        "description": "<p>Description</p>",
                    }
                ]
            },
            {
                "results": [
                    {
                        "trackId": 202,
                        "collectionName": "Livre audio",
                        "artistName": "Auteur",
                        "trackTimeMillis": 600000,
                        "releaseDate": "2024-05-01T00:00:00Z",
                    }
                ]
            },
        ]
    )
    provider = ITunesMetadataProvider(transport, country="FR")
    candidates = provider.search(MetadataQuery(text="Livre", kind="unknown"))
    assert [item.kind for item in candidates] == ["ebook", "audiobook"]
    assert [call[1]["media"] for call in transport.calls] == ["ebook", "audiobook"]
    assert candidates[1].duration_ms == 600000
    assert candidates[1].publication_date is not None
    assert candidates[1].publication_date.isoformat() == "2024-05-01"
    assert candidates[0].description == "Description"
    assert "600x600bb" in candidates[0].cover_candidates[0].url


def test_aggregator_uses_cache_and_survives_one_provider_failure():
    good = FakeProvider("good", [_candidate("good", "1", "Titre")])
    bad = FakeProvider("bad", [], fail=True)
    aggregator = MetadataAggregator((good, bad), cache_ttl_seconds=60)
    first = aggregator.search(MetadataQuery(text="Titre"))
    second = aggregator.search(MetadataQuery(text="Titre"))
    assert len(first.items) == 1
    assert first.provider_failures == {"bad": "unavailable"}
    assert second.cache_hit is True
    assert good.calls == 1


def test_aggregator_raises_when_every_provider_fails():
    aggregator = MetadataAggregator((FakeProvider("bad", [], fail=True),))
    with pytest.raises(MetadataProviderError, match="all metadata providers"):
        aggregator.search(MetadataQuery(text="Titre"))


def test_identifier_match_ranks_above_title_similarity():
    query = MetadataQuery(identifier="9782070000011")
    exact = MetadataCandidate(
        provider="openlibrary",
        provider_id="OL42W",
        title="Autre titre",
        identifiers=(ExternalIdentifier(kind="isbn13", value="9782070000011"),),
    )
    similar = MetadataCandidate(
        provider="itunes",
        provider_id="202",
        title="9782070000011",
    )
    assert match_score(query, exact) == 100
    assert match_score(query, similar) < 100


def test_transport_refuses_plain_http():
    transport = UrllibJsonTransport()
    with pytest.raises(MetadataProviderError, match="HTTPS"):
        transport.get_json("http://openlibrary.org/search.json")
