"""Service: external metadata search and human review."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from ..errors import UnavailableError
from ..metadata.aggregator import MetadataAggregator
from ..metadata.models import MetadataQuery
from ..metadata.transport import MetadataProviderError
from .base import BaseService


class MetadataService(BaseService):
    def _aggregator(self) -> MetadataAggregator:
        if not self.metadata_providers:
            raise UnavailableError(
                "no metadata provider is configured",
                code="METADATA_NO_PROVIDER",
            )
        if self._metadata_aggregator is None:
            self._metadata_aggregator = MetadataAggregator(
                self.metadata_providers,
                cache_ttl_seconds=self.settings.metadata_cache_ttl_seconds,
            )
        return self._metadata_aggregator

    def search_metadata(
        self,
        *,
        text: str = "",
        kind: str = "unknown",
        language: str = "",
        limit: int = 10,
        identifier: str = "",
        identifier_kind: str = "",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        query = MetadataQuery(
            text=text,
            kind=kind,
            language=language,
            limit=limit,
            identifier=identifier,
            identifier_kind=identifier_kind,
        )
        try:
            result = self._aggregator().search(query)
        except MetadataProviderError as exc:
            self.repo.record_audit(
                actor_type="admin",
                actor_id=actor_id,
                action="metadata.search",
                target_type="metadata_query",
                outcome="failed",
                reason="METADATA_UNAVAILABLE",
                request_id=request_id,
            )
            raise UnavailableError(str(exc), code="METADATA_UNAVAILABLE") from exc
        rows = self.repo.save_metadata_candidates(
            result.items, ttl_seconds=self.settings.metadata_cache_ttl_seconds
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="metadata.search",
            target_type="metadata_query",
            target_id=query.cache_key()[:200],
            outcome="success",
            reason=f"items={len(rows)}",
            request_id=request_id,
        )
        return {
            "items": rows,
            "provider_failures": dict(result.provider_failures),
            "cache_hit": result.cache_hit,
        }

    def list_metadata_candidates(
        self,
        *,
        limit: int = 50,
        provider: str = "",
        status: str = "",
    ) -> dict:
        return {
            "items": self.repo.list_metadata_candidates(
                limit=limit, provider=provider, status=status
            )
        }

    def review_metadata_candidate(
        self,
        candidate_id: UUID,
        *,
        decision: str,
        target_entity_type: str | None,
        target_entity_id: UUID | None,
        reason: str = "",
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        updated = self.repo.review_metadata_candidate(
            candidate_id,
            decision=decision,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            reviewer_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="metadata.review",
            target_type="metadata_candidate",
            target_id=str(candidate_id),
            outcome="success",
            reason=decision,
            request_id=request_id,
        )
        return updated

    def list_external_identifiers(
        self, *, entity_type: str, entity_id: UUID
    ) -> dict[str, Any]:
        return {
            "items": self.repo.list_external_identifiers(
                entity_type=entity_type, entity_id=entity_id
            )
        }
