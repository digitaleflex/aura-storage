from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from audiobook.main import create_app
from audiobook.metadata.models import (
    ExternalIdentifier,
    MetadataCandidate,
    MetadataQuery,
)
from audiobook.metadata.transport import MetadataProviderError


class StubProvider:
    name = "stub"

    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls: list[str] = []

    def search(self, query: MetadataQuery):
        self.calls.append(query.text or query.identifier)
        return [candidate for candidate in self.candidates if not query.text or query.text in candidate.title]


class FailingProvider:
    name = "broken"

    def search(self, query):
        raise MetadataProviderError("offline")


@pytest.fixture
def metadata_client(settings, db, storage):
    provider = StubProvider(
        [
            MetadataCandidate(
                provider="stub",
                provider_id="book-1",
                title="Les Voix de la Nuit",
                kind="audiobook",
                language="fr",
                identifiers=(
                    ExternalIdentifier(kind="isbn13", value="9782070000011"),
                ),
            ),
            MetadataCandidate(
                provider="stub",
                provider_id="book-2",
                title="Autre livre",
                kind="ebook",
                language="fr",
            ),
        ]
    )
    app = create_app(
        settings,
        db,
        storage,
        initialize_schema=False,
        metadata_providers=(provider,),
    )
    with TestClient(app) as client:
        yield client, app, provider


def test_metadata_search_requires_admin(metadata_client):
    client, _, _ = metadata_client
    response = client.post("/api/v1/admin/metadata/search", json={"text": "Voix"})
    assert response.status_code == 401


def test_metadata_search_persists_provenance_and_uses_cache(metadata_client, admin_headers):
    client, _, provider = metadata_client
    body = {"text": "Voix", "kind": "audiobook", "language": "fr", "limit": 10}
    first = client.post("/api/v1/admin/metadata/search", headers=admin_headers, json=body)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["cache_hit"] is False
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["provider"] == "stub"
    assert item["status"] == "new"
    assert item["normalized_json"]["identifiers"][0]["value"] == "9782070000011"

    second = client.post("/api/v1/admin/metadata/search", headers=admin_headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json()["cache_hit"] is True
    assert provider.calls == ["Voix"]

    listed = client.get(
        "/api/v1/admin/metadata/candidates", headers=admin_headers, params={"status": "new"}
    )
    assert listed.status_code == 200
    assert any(row["id"] == item["id"] for row in listed.json()["items"])


def test_review_links_identifier_then_rejects_duplicate_review(
    metadata_client, admin_headers
):
    client, app, _ = metadata_client
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": "Les Voix de la Nuit", "language": "fr", "description": "Test"},
    )
    assert work.status_code == 200, work.text
    work_id = work.json()["id"]

    search = client.post(
        "/api/v1/admin/metadata/search",
        headers=admin_headers,
        json={"text": "Voix"},
    )
    candidate_id = search.json()["items"][0]["id"]
    review = client.post(
        f"/api/v1/admin/metadata/candidates/{candidate_id}/review",
        headers=admin_headers,
        json={
            "decision": "link_existing",
            "target_entity_type": "work",
            "target_entity_id": work_id,
            "reason": "correspondance ISBN exacte",
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "applied"

    with app.state.db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, id_kind, external_id FROM external_identifiers "
                "WHERE entity_type = 'work' AND entity_id = %s ORDER BY id_kind",
                (work_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
    assert any(row["external_id"] == "9782070000011" for row in rows)
    assert any(row["id_kind"] == "provider_id" for row in rows)

    again = client.post(
        f"/api/v1/admin/metadata/candidates/{candidate_id}/review",
        headers=admin_headers,
        json={"decision": "reject", "reason": "doublon"},
    )
    assert again.status_code == 409
    assert again.json()["error"] == "METADATA_CANDIDATE_REVIEWED"


def test_candidate_can_be_rejected_and_provider_failure_is_explicit(
    settings, db, storage, admin_headers
):
    client_ok = create_app(
        settings,
        db,
        storage,
        initialize_schema=False,
        metadata_providers=(StubProvider([_candidate_to_reject()]),),
    )
    with TestClient(client_ok) as client:
        search = client.post(
            "/api/v1/admin/metadata/search",
            headers=admin_headers,
            json={"text": "Autre"},
        )
        assert search.status_code == 200, search.text
        candidate_id = search.json()["items"][0]["id"]
        rejected = client.post(
            f"/api/v1/admin/metadata/candidates/{candidate_id}/review",
            headers=admin_headers,
            json={"decision": "reject", "reason": "mauvaise édition"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

    client_bad = create_app(
        settings,
        db,
        storage,
        initialize_schema=False,
        metadata_providers=(FailingProvider(),),
    )
    with TestClient(client_bad) as client:
        failed = client.post(
            "/api/v1/admin/metadata/search",
            headers=admin_headers,
            json={"text": "Indisponible"},
        )
        assert failed.status_code == 503
        assert failed.json()["error"] == "METADATA_UNAVAILABLE"


def _candidate_to_reject() -> MetadataCandidate:
    return MetadataCandidate(
        provider="stub",
        provider_id="book-2",
        title="Autre livre",
        kind="ebook",
    )
