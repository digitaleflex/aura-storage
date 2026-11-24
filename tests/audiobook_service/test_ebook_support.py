from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from audiobook.domain import (
    EbookAssetFact,
    PublicationFacts,
    RightsWindowFact,
    TrackFact,
    validate_publication,
)


def _facts(**overrides) -> PublicationFacts:
    now = datetime.now(timezone.utc)
    values = {
        "work_id": uuid4(),
        "work_title": "Livre",
        "work_language": "fr",
        "work_status": "approved",
        "authors": ("Auteur",),
        "narrators": (),
        "edition_title": "Livre",
        "edition_language": "fr",
        "edition_description": "Description",
        "duration_ms": 0,
        "cover_asset_id": uuid4(),
        "tracks": (),
        "rights": (
            RightsWindowFact(
                id=uuid4(),
                territory_code="WORLD",
                channel="stream",
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=1),
                status="active",
            ),
        ),
        "now": now,
        "publication_kind": "ebook",
        "ebook_assets": (
            EbookAssetFact(id=uuid4(), format="epub", asset_status="ready"),
        ),
    }
    values.update(overrides)
    return PublicationFacts(**values)


def test_ebook_publication_does_not_require_narrator_duration_or_tracks():
    assert validate_publication(_facts()) == ()


def test_audiobook_publication_still_requires_narrator_duration_and_tracks():
    blockers = validate_publication(
        _facts(
            publication_kind="audiobook",
            narrators=("Narrateur",),
            duration_ms=600_000,
            tracks=(
                TrackFact(id=uuid4(), position=1, status="ready", asset_status="ready"),
            ),
        )
    )
    assert blockers == ()


def test_ebook_without_asset_or_with_duration_is_blocked():
    blockers = validate_publication(
        _facts(ebook_assets=(), duration_ms=1_000)
    )
    codes = {blocker.code for blocker in blockers}
    assert "NO_EBOOK_ASSET" in codes
    assert "DURATION_NOT_APPLICABLE" in codes


def _create_ebook_edition(client, admin_headers):
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": "Ebook API", "language": "fr", "description": "Test"},
    )
    assert work.status_code == 200, work.text
    work_id = work.json()["id"]
    client.post(
        f"/api/v1/admin/works/{work_id}/contributors",
        headers=admin_headers,
        json={"name": "Auteur", "role": "author"},
    )
    client.post(f"/api/v1/admin/works/{work_id}/approve", headers=admin_headers)
    cover = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={"storage_object_id": f"cover-{uuid4()}", "kind": "cover", "status": "ready"},
    ).json()
    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work_id,
            "title": "Ebook API",
            "language": "fr",
            "description": "Livre numérique",
            "publication_kind": "ebook",
            "cover_asset_id": cover["id"],
            "access_model": "free",
        },
    )
    assert edition.status_code == 200, edition.text
    return work_id, edition.json()["id"]


def test_admin_rejects_invalid_duration_for_each_kind(client, admin_headers):
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": "Validation", "language": "fr", "description": "Test"},
    ).json()
    invalid_ebook = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work["id"],
            "title": "Ebook invalide",
            "language": "fr",
            "description": "Test",
            "publication_kind": "ebook",
            "duration_ms": 1000,
        },
    )
    assert invalid_ebook.status_code == 422
    invalid_audio = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work["id"],
            "title": "Audio invalide",
            "language": "fr",
            "description": "Test",
            "publication_kind": "audiobook",
        },
    )
    assert invalid_audio.status_code == 422


def test_published_ebook_can_be_listed_and_delivered(client, admin_headers, listener):
    _, edition_id = _create_ebook_edition(client, admin_headers)
    asset = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={
            "storage_object_id": f"ebook-{uuid4()}",
            "kind": "ebook",
            "content_type": "application/epub+zip",
            "size_bytes": 4096,
            "status": "ready",
        },
    )
    assert asset.status_code == 200, asset.text
    linked = client.post(
        f"/api/v1/admin/editions/{edition_id}/ebook-assets",
        headers=admin_headers,
        json={"asset_id": asset.json()["id"], "format": "epub"},
    )
    assert linked.status_code == 200, linked.text
    rights = client.post(
        f"/api/v1/admin/editions/{edition_id}/rights",
        headers=admin_headers,
        json={
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2030-01-01T00:00:00Z",
            "territory_code": "WORLD",
            "channel": "stream",
            "status": "active",
        },
    )
    assert rights.status_code == 200, rights.text
    published = client.post(
        f"/api/v1/admin/editions/{edition_id}/publish", headers=admin_headers
    )
    assert published.status_code == 200, published.text

    catalog = client.get("/api/v1/catalog").json()["items"]
    item = next(row for row in catalog if row["id"] == edition_id)
    assert item["publication_kind"] == "ebook"
    assert item["ebook_asset_count"] == 1

    url = client.get(
        f"/api/v1/ebooks/{edition_id}/url", headers=listener["headers"]
    )
    assert url.status_code == 200, url.text
    assert url.json()["url"].startswith("https://media.test/")
    assert url.json()["decision"]["allowed"] is True


def test_ingested_epub_is_linked_to_ebook_edition(client, admin_headers, tmp_path, settings, db):
    _, edition_id = _create_ebook_edition(client, admin_headers)
    path = tmp_path / "book.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OEBPS/chapter.xhtml", "<p>Test</p>")
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from audiobook.main import create_app
    from audiobook.storage import FakeStoragePort

    ingest_settings = replace(
        settings, ingest_staging_dir=str(tmp_path), ingest_ffprobe_command=""
    )
    app = create_app(
        ingest_settings,
        db,
        FakeStoragePort(),
        initialize_schema=False,
        metadata_providers=(),
    )
    with TestClient(app) as ingest_client:
        started = ingest_client.post(
            "/api/v1/admin/ingestions",
            headers=admin_headers,
            json={
                "source": "manual",
                "source_ref": "epub-1",
                "filename": "book.epub",
                "staged_path": str(path),
                "target_edition_id": edition_id,
            },
        )
        assert started.status_code == 200, started.text
        imported = ingest_client.post(
            f"/api/v1/admin/ingestions/{started.json()['id']}/import",
            headers=admin_headers,
        )
        assert imported.status_code == 200, imported.text
        bundle = ingest_client.get(
            f"/api/v1/admin/editions/{edition_id}", headers=admin_headers
        ).json()
        assert len(bundle["ebook_assets"]) == 1
        assert bundle["ebook_assets"][0]["format"] == "epub"
