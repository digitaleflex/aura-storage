"""Provider orchestration, deterministic ranking and a bounded TTL cache."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Callable

from .matching import with_confidence
from .models import MetadataCandidate, MetadataQuery, MetadataSearchResult
from .providers import MetadataProvider
from .transport import MetadataProviderError


class MetadataAggregator:
    def __init__(
        self,
        providers: tuple[MetadataProvider, ...],
        *,
        cache_ttl_seconds: int = 300,
        cache_size: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_ttl_seconds < 0 or cache_size <= 0:
            raise ValueError("invalid metadata cache configuration")
        self.providers = tuple(providers)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_size = cache_size
        self._clock = clock
        self._cache: dict[str, tuple[float, MetadataSearchResult]] = {}
        self._lock = threading.Lock()

    def search(self, query: MetadataQuery) -> MetadataSearchResult:
        key = query.cache_key()
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return replace(cached[1], cache_hit=True)
            if cached:
                self._cache.pop(key, None)

        candidates: list[MetadataCandidate] = []
        failures: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        for provider in self.providers:
            try:
                found = provider.search(query)
            except MetadataProviderError:
                failures[provider.name] = "unavailable"
                continue
            for candidate in found:
                identity = (candidate.provider, candidate.provider_id)
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(with_confidence(query, candidate))
        if not candidates and failures:
            raise MetadataProviderError("all metadata providers are unavailable")
        candidates.sort(key=lambda item: (-item.confidence, item.provider, item.provider_id))
        result = MetadataSearchResult(items=tuple(candidates[: query.limit]), provider_failures=failures)
        with self._lock:
            self._cache[key] = (now + self.cache_ttl_seconds, result)
            while len(self._cache) > self.cache_size:
                self._cache.pop(next(iter(self._cache)))
        return result
