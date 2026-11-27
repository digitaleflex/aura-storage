"""External metadata providers and normalization for the publication catalogue."""

from .aggregator import MetadataAggregator, MetadataSearchResult
from .models import (
    CoverCandidate,
    ExternalIdentifier,
    MetadataCandidate,
    MetadataContributor,
    MetadataQuery,
)
from .providers import (
    GoogleBooksMetadataProvider,
    ITunesMetadataProvider,
    OpenLibraryMetadataProvider,
)
from .transport import MetadataProviderError, UrllibJsonTransport

__all__ = [
    "CoverCandidate",
    "ExternalIdentifier",
    "GoogleBooksMetadataProvider",
    "ITunesMetadataProvider",
    "MetadataAggregator",
    "MetadataCandidate",
    "MetadataContributor",
    "MetadataProviderError",
    "MetadataQuery",
    "MetadataSearchResult",
    "OpenLibraryMetadataProvider",
    "UrllibJsonTransport",
]
