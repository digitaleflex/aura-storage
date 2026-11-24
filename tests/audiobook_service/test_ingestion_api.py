from __future__ import annotations

from audiobook.storage import CommitResult


def _audio_file(tmp_path, name="livre.mp3"):
    path = tmp_path / name
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 4096)
    return path


def _create_edition(client, admin_headers):
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": "Ingestion", "language": "fr", "description": "Test"},
    )
    assert work.status_code == 200, work.text
    work_id = work.json()["id"]
    contributor = client.post(
        f"/api/v1/admin/works/{work_id}/contributors",
        headers=admin_headers,
        json={"name": "Auteur", "role": "author"},
    )
    assert contributor.status_code == 200, contributor.text
    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work_id,
            "title": "Ingestion",
            "language": "fr",
            "description": "Édition pour ingestion",
            "duration_ms": 600_000,
            "access_model": "free",
        },
    )
    assert edition.status_code == 200, edition.text
    return edition.json()["id"]


def test_ingest_start_requires_admin_and_hides_staging_path(ingest_client):
    client, _, _, tmp_path = ingest_client
    path = _audio_file(tmp_path)
    body = {
        "source": "manual",
        "source_ref": "file-1",
        "filename": "livre.mp3",
        "staged_path": str(path),
        "duration_ms": 600_000,
    }
    denied = client.post("/api/v1/admin/ingestions", json=body)
    assert denied.status_code == 401
    started = client.post(
        "/api/v1/admin/ingestions", headers={"Authorization": "Bearer test-admin-token"}, json=body
    )
    assert started.status_code == 200, started.text
    item = started.json()
    assert item["state"] == "validating"
    assert item["duplicate"] is False
    assert "staging_path" not in item
    assert item["detected_content_type"] == "audio/mpeg"
    assert item["sha256"]


def test_ingest_rejects_path_outside_staging(ingest_client, admin_headers, tmp_path):
    client, _, _, _ = ingest_client
    outside = tmp_path.parent / "hors-staging.mp3"
    outside.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    try:
        response = client.post(
            "/api/v1/admin/ingestions",
            headers=admin_headers,
            json={
                "source": "manual",
                "source_ref": "outside",
                "filename": "hors-staging.mp3",
                "staged_path": str(outside),
                "duration_ms": 1000,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"] == "INGEST_PATH_OUTSIDE_STAGING"
    finally:
        outside.unlink(missing_ok=True)


def test_full_import_attaches_asset_track_and_chapter(ingest_client, admin_headers, tmp_path):
    client, app, _, tmp_path = ingest_client
    edition_id = _create_edition(client, admin_headers)
    path = _audio_file(tmp_path)
    started = client.post(
        "/api/v1/admin/ingestions",
        headers=admin_headers,
        json={
            "source": "shelfmark",
            "source_ref": "book-1",
            "filename": "livre.mp3",
            "staged_path": str(path),
            "target_edition_id": edition_id,
            "track_position": 1,
            "track_title": "Chapitre 1",
            "duration_ms": 600_000,
        },
    )
    assert started.status_code == 200, started.text
    item_id = started.json()["id"]

    imported = client.post(
        f"/api/v1/admin/ingestions/{item_id}/import", headers=admin_headers
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["state"] == "completed"
    assert body["asset_id"] is not None
    assert body["storage_object_id"].startswith("fake-")

    edition = client.get(
        f"/api/v1/admin/editions/{edition_id}", headers=admin_headers
    )
    assert edition.status_code == 200, edition.text
    assert len(edition.json()["tracks"]) == 1
    assert len(edition.json()["chapters"]) == 1

    audit = client.get("/api/v1/admin/audit?limit=200", headers=admin_headers)
    actions = [row["action"] for row in audit.json()["items"]]
    assert "ingest.started" in actions
    assert "ingest.imported" in actions


def test_duplicate_sha_is_not_imported_twice(ingest_client, admin_headers, tmp_path):
    client, _, _, tmp_path = ingest_client
    path = _audio_file(tmp_path)
    payload = {
        "source": "manual",
        "source_ref": "dup-1",
        "filename": "livre.mp3",
        "staged_path": str(path),
        "duration_ms": 600_000,
    }
    first = client.post(
        "/api/v1/admin/ingestions", headers=admin_headers, json=payload
    )
    second = client.post(
        "/api/v1/admin/ingestions", headers=admin_headers, json=payload
    )
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    listed = client.get("/api/v1/admin/ingestions", headers=admin_headers)
    assert len(listed.json()["items"]) == 1


def test_retry_after_commit_failure_is_idempotent(ingest_client, admin_headers, tmp_path):
    client, _, storage, tmp_path = ingest_client
    path = _audio_file(tmp_path)
    started = client.post(
        "/api/v1/admin/ingestions",
        headers=admin_headers,
        json={
            "source": "manual",
            "source_ref": "retry-1",
            "filename": "livre.mp3",
            "staged_path": str(path),
            "duration_ms": 600_000,
        },
    ).json()
    storage.commit_failures[started["idempotency_key"]] = 1
    failed = client.post(
        f"/api/v1/admin/ingestions/{started['id']}/import", headers=admin_headers
    )
    assert failed.status_code == 503
    assert failed.json()["error"] == "COMMIT_PENDING"
    status = client.get(
        f"/api/v1/admin/ingestions/{started['id']}", headers=admin_headers
    )
    assert status.json()["state"] == "retryable_failed"
    assert status.json()["error_code"] == "COMMIT_PENDING"

    retried = client.post(
        f"/api/v1/admin/ingestions/{started['id']}/retry", headers=admin_headers
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["state"] == "completed"
    assert retried.json()["attempts"] == 2


def test_checksum_mismatch_never_creates_an_asset(
    ingest_client, admin_headers, tmp_path
):
    client, app, storage, tmp_path = ingest_client
    path = _audio_file(tmp_path)
    started = client.post(
        "/api/v1/admin/ingestions",
        headers=admin_headers,
        json={
            "source": "manual",
            "source_ref": "mismatch-1",
            "filename": "livre.mp3",
            "staged_path": str(path),
            "duration_ms": 600_000,
        },
    ).json()

    def wrong_commit(object_id, *, idempotency_key):
        return CommitResult(
            object_id=object_id,
            status="available",
            size_bytes=1,
            checksum_sha256="0" * 64,
        )

    storage.commit_upload = wrong_commit
    failed = client.post(
        f"/api/v1/admin/ingestions/{started['id']}/import", headers=admin_headers
    )
    assert failed.status_code == 503
    assert failed.json()["error"] == "INGEST_VERIFICATION_FAILED"
    with app.state.db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state, error_code, asset_id FROM ingest_items WHERE id = %s",
                (started["id"],),
            )
            row = dict(cur.fetchone())
    assert row["state"] == "retryable_failed"
    assert row["error_code"] == "INGEST_VERIFICATION_FAILED"
    assert row["asset_id"] is None
