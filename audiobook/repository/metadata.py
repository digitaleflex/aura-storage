"""Repository: external metadata candidates, provenance and reviews."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from ..errors import ConflictError, NotFoundError, ValidationError
from ..ids import new_id
from ..metadata.models import MetadataCandidate
from .base import BaseRepository, _jsonable


class MetadataRepository(BaseRepository):
    def save_metadata_candidates(
        self, candidates: tuple[MetadataCandidate, ...], *, ttl_seconds: int
    ) -> list[dict]:
        rows: list[dict] = []
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                for candidate in candidates:
                    fetched_at = candidate.fetched_at
                    expires_at = fetched_at + timedelta(seconds=max(0, ttl_seconds))
                    cur.execute(
                        """
                        INSERT INTO metadata_candidates
                          (id, provider, provider_id, kind, normalized_json,
                           payload_hash, confidence, fetched_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (provider, provider_id) DO UPDATE SET
                          kind = EXCLUDED.kind,
                          normalized_json = EXCLUDED.normalized_json,
                          payload_hash = EXCLUDED.payload_hash,
                          confidence = EXCLUDED.confidence,
                          fetched_at = EXCLUDED.fetched_at,
                          expires_at = EXCLUDED.expires_at,
                          status = CASE
                            WHEN metadata_candidates.payload_hash = EXCLUDED.payload_hash
                              THEN metadata_candidates.status
                            ELSE 'new'
                          END,
                          updated_at = now()
                        RETURNING *
                        """,
                        (
                            new_id(),
                            candidate.provider,
                            candidate.provider_id,
                            candidate.kind,
                            Jsonb(_jsonable(candidate.to_dict())),
                            candidate.payload_hash,
                            candidate.confidence,
                            fetched_at,
                            expires_at,
                        ),
                    )
                    rows.append(dict(cur.fetchone()))
        return rows

    def get_metadata_candidate(self, candidate_id: UUID) -> dict:
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM metadata_candidates WHERE id = %s",
                    (candidate_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise NotFoundError("metadata candidate not found", code="METADATA_CANDIDATE_NOT_FOUND")
        return dict(row)

    def list_metadata_candidates(
        self,
        *,
        limit: int = 50,
        provider: str = "",
        status: str = "",
    ) -> list[dict]:
        clauses: list[str] = []
        values: list[Any] = []
        if provider:
            clauses.append("provider = %s")
            values.append(provider)
        if status:
            clauses.append("status = %s")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(limit, 200)))
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM metadata_candidates {where} "
                    "ORDER BY fetched_at DESC, id DESC LIMIT %s",
                    tuple(values),
                )
                return [dict(row) for row in cur.fetchall()]

    def review_metadata_candidate(
        self,
        candidate_id: UUID,
        *,
        decision: str,
        target_entity_type: str | None,
        target_entity_id: UUID | None,
        reviewer_id: str,
        reason: str,
        request_id: str,
    ) -> dict:
        if decision not in {"link_existing", "reject"}:
            raise ValidationError("unsupported metadata review decision")
        if decision == "link_existing":
            if target_entity_type not in {"work", "edition"} or target_entity_id is None:
                raise ValidationError("link_existing requires a work or edition target")
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, provider, provider_id, normalized_json, status "
                    "FROM metadata_candidates WHERE id = %s FOR UPDATE",
                    (candidate_id,),
                )
                candidate = cur.fetchone()
                if candidate is None:
                    raise NotFoundError(
                        "metadata candidate not found", code="METADATA_CANDIDATE_NOT_FOUND"
                    )
                if candidate["status"] != "new":
                    raise ConflictError(
                        "metadata candidate already reviewed", code="METADATA_CANDIDATE_REVIEWED"
                    )
                if decision == "link_existing":
                    self._link_identifiers(
                        cur,
                        candidate,
                        entity_type=str(target_entity_type),
                        entity_id=target_entity_id,
                    )
                new_status = "applied" if decision == "link_existing" else "rejected"
                cur.execute(
                    "UPDATE metadata_candidates SET status = %s, updated_at = now() WHERE id = %s",
                    (new_status, candidate_id),
                )
                cur.execute(
                    """
                    INSERT INTO metadata_reviews
                      (id, candidate_id, decision, target_entity_type, target_entity_id,
                       reviewer_id, reason, request_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_id(),
                        candidate_id,
                        decision,
                        target_entity_type if decision == "link_existing" else None,
                        target_entity_id if decision == "link_existing" else None,
                        reviewer_id,
                        reason,
                        request_id,
                    ),
                )
        return self.get_metadata_candidate(candidate_id)

    @staticmethod
    def _link_identifiers(cur, candidate: dict, *, entity_type: str, entity_id: UUID) -> None:
        table = "works" if entity_type == "work" else "editions"
        cur.execute(f"SELECT id FROM {table} WHERE id = %s", (entity_id,))
        if cur.fetchone() is None:
            raise NotFoundError(f"{entity_type} not found", code="METADATA_TARGET_NOT_FOUND")
        normalized = candidate["normalized_json"]
        if not isinstance(normalized, dict):
            normalized = {}
        identifiers: list[tuple[str, str]] = [
            ("provider_id", str(candidate["provider_id"]))
        ]
        for item in normalized.get("identifiers", []):
            if isinstance(item, dict) and item.get("kind") and item.get("value"):
                identifiers.append((str(item["kind"]), str(item["value"])))
        for kind, value in dict.fromkeys(identifiers):
            cur.execute(
                """
                INSERT INTO external_identifiers
                  (id, entity_type, entity_id, provider, id_kind, external_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (provider, id_kind, external_id) DO NOTHING
                RETURNING id
                """,
                (new_id(), entity_type, entity_id, candidate["provider"], kind, value),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    SELECT entity_type, entity_id FROM external_identifiers
                    WHERE provider = %s AND id_kind = %s AND external_id = %s
                    """,
                    (candidate["provider"], kind, value),
                )
                existing = cur.fetchone()
                if existing and (
                    existing["entity_type"] != entity_type or existing["entity_id"] != entity_id
                ):
                    raise ConflictError(
                        "external identifier already linked to another entity",
                        code="EXTERNAL_IDENTIFIER_CONFLICT",
                    )

    def list_external_identifiers(
        self, *, entity_type: str, entity_id: UUID
    ) -> list[dict]:
        if entity_type not in {"work", "edition"}:
            raise ValidationError("unsupported entity type")
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider, id_kind, external_id, created_at
                    FROM external_identifiers
                    WHERE entity_type = %s AND entity_id = %s
                    ORDER BY provider, id_kind
                    """,
                    (entity_type, entity_id),
                )
                return [dict(row) for row in cur.fetchall()]
