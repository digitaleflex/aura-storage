from __future__ import annotations

import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audiobook.config import Settings  # noqa: E402
from audiobook.db import Database  # noqa: E402
from audiobook.main import create_app  # noqa: E402
from audiobook.repository import Repository  # noqa: E402
from audiobook.services import AudiobookService  # noqa: E402
from audiobook.storage import FakeStoragePort  # noqa: E402


@pytest.fixture
def pg_dsn() -> str:
    dsn = os.environ.get("AUDIOBOOK_TEST_DSN", "")
    if not dsn:
        pytest.skip("AUDIOBOOK_TEST_DSN is not set; skipping PostgreSQL tests")
    return dsn


@pytest.fixture
def db(pg_dsn: str):
    schema = f"audiobook_test_{uuid.uuid4().hex[:12]}"
    database = Database(pg_dsn, schema)
    database.init_schema()
    try:
        yield database
    finally:
        database.drop_schema()


@pytest.fixture
def settings(pg_dsn: str, db: Database) -> Settings:
    return Settings(
        dsn=pg_dsn,
        schema=db.schema,
        public_base_url="http://testserver",
        dev_auth=True,
        admin_token="test-admin-token",
        cookie_secure=False,
        access_decision_ttl_seconds=60,
        playback_lease_seconds=120,
        policy_version="test",
    )


@pytest.fixture
def repo(db: Database) -> Repository:
    return Repository(db)


@pytest.fixture
def storage() -> FakeStoragePort:
    return FakeStoragePort("https://media.test")


@pytest.fixture
def service(settings: Settings, repo: Repository, storage: FakeStoragePort) -> AudiobookService:
    return AudiobookService(repo, settings, storage)


@pytest.fixture
def app(settings: Settings, db: Database, storage: FakeStoragePort):
    return create_app(
        settings, db, storage, initialize_schema=False
    )


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ingest_client(settings: Settings, db: Database, storage: FakeStoragePort, tmp_path):
    ingest_settings = replace(
        settings,
        ingest_staging_dir=str(tmp_path),
        ingest_ffprobe_command="",
        ingest_av_command="",
    )
    app = create_app(
        ingest_settings,
        db,
        storage,
        initialize_schema=False,
        metadata_providers=(),
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client, app, storage, tmp_path


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def seeded(client, admin_headers):
    """Publish a complete free edition and return its identifiers."""
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={
            "title": "Les Voix de la Nuit",
            "language": "fr",
            "description": "Un roman lu.",
        },
    )
    assert work.status_code == 200, work.text
    work_id = work.json()["id"]

    author = client.post(
        f"/api/v1/admin/works/{work_id}/contributors",
        headers=admin_headers,
        json={"name": "Awa Diallo", "role": "author", "position": 0},
    )
    assert author.status_code == 200, author.text
    narrator = client.post(
        f"/api/v1/admin/works/{work_id}/contributors",
        headers=admin_headers,
        json={"name": "Nora Mensah", "role": "narrator", "position": 0},
    )
    assert narrator.status_code == 200, narrator.text

    approve = client.post(
        f"/api/v1/admin/works/{work_id}/approve", headers=admin_headers
    )
    assert approve.status_code == 200, approve.text

    cover = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={
            "storage_object_id": "obj-cover-1",
            "kind": "cover",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
            "status": "ready",
        },
    )
    assert cover.status_code == 200, cover.text
    audio = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={
            "storage_object_id": "obj-audio-1",
            "kind": "source",
            "content_type": "audio/mpeg",
            "size_bytes": 10_000_000,
            "duration_ms": 600_000,
            "status": "ready",
        },
    )
    assert audio.status_code == 200, audio.text

    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work_id,
            "title": "Les Voix de la Nuit",
            "language": "fr",
            "description": "Un roman lu.",
            "duration_ms": 600_000,
            "cover_asset_id": cover.json()["id"],
            "access_model": "free",
        },
    )
    assert edition.status_code == 200, edition.text
    edition_id = edition.json()["id"]

    track = client.post(
        f"/api/v1/admin/editions/{edition_id}/tracks",
        headers=admin_headers,
        json={
            "position": 1,
            "title": "Chapitre 1",
            "start_ms": 0,
            "end_ms": 600_000,
            "asset_id": audio.json()["id"],
            "status": "ready",
        },
    )
    assert track.status_code == 200, track.text

    rights = client.post(
        f"/api/v1/admin/editions/{edition_id}/rights",
        headers=admin_headers,
        json={
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "territory_code": "WORLD",
            "channel": "stream",
            "status": "active",
        },
    )
    assert rights.status_code == 200, rights.text

    publish = client.post(
        f"/api/v1/admin/editions/{edition_id}/publish", headers=admin_headers
    )
    assert publish.status_code == 200, publish.text
    return {
        "work_id": work_id,
        "edition_id": edition_id,
        "track_id": track.json()["id"],
        "cover_asset_id": cover.json()["id"],
    }


@pytest.fixture
def listener(client):
    response = client.post(
        "/api/v1/auth/dev-login",
        json={"email": "listener@example.test", "display_name": "Listener"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "listener": body["listener"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "token": body["token"],
        "csrf_token": body["csrf_token"],
    }
