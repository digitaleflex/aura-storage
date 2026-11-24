from __future__ import annotations

from datetime import datetime, timedelta, timezone

from audiobook.services.ingestion import retry_due


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_retry_due_uses_state_attempts_and_delay():
    now = _now()
    item = {
        "state": "retryable_failed",
        "attempts": 1,
        "updated_at": (now - timedelta(seconds=120)).isoformat(),
    }
    assert retry_due(item, now=now, delay_seconds=60, max_attempts=5)
    assert not retry_due(item, now=now, delay_seconds=300, max_attempts=5)
    assert not retry_due(item, now=now, delay_seconds=60, max_attempts=1)
    assert not retry_due(
        {**item, "state": "completed"}, now=now, delay_seconds=60, max_attempts=5
    )
    assert not retry_due(
        {"state": "retryable_failed", "attempts": 1},
        now=now,
        delay_seconds=60,
        max_attempts=5,
    )


def test_reconcile_retries_due_failure(ingest_client, admin_headers, tmp_path):
    client, app, storage, tmp_path = ingest_client
    path = tmp_path / "livre.mp3"
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 4096)
    started = client.post(
        "/api/v1/admin/ingestions",
        headers=admin_headers,
        json={
            "source": "manual",
            "source_ref": "reconcile-1",
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
    with app.state.db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_items SET updated_at = now() - interval '10 minutes' "
                "WHERE id = %s",
                (started["id"],),
            )
    summary = client.post(
        "/api/v1/admin/ingestions/reconcile", headers=admin_headers
    )
    assert summary.status_code == 200, summary.text
    assert str(started["id"]) in summary.json()["retried"]
    status = client.get(
        f"/api/v1/admin/ingestions/{started['id']}", headers=admin_headers
    )
    assert status.json()["state"] == "completed"


def test_reconcile_marks_stale_import_without_publishing(
    ingest_client, admin_headers, tmp_path
):
    client, app, _, tmp_path = ingest_client
    path = tmp_path / "stale.mp3"
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    started = client.post(
        "/api/v1/admin/ingestions",
        headers=admin_headers,
        json={
            "source": "manual",
            "source_ref": "stale-1",
            "filename": "stale.mp3",
            "staged_path": str(path),
            "duration_ms": 1000,
        },
    ).json()
    with app.state.db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_items SET state = 'importing', "
                "updated_at = now() - interval '1 hour' WHERE id = %s",
                (started["id"],),
            )
    summary = client.post(
        "/api/v1/admin/ingestions/reconcile", headers=admin_headers
    )
    assert summary.status_code == 200, summary.text
    assert str(started["id"]) in summary.json()["stale_marked"]
    status = client.get(
        f"/api/v1/admin/ingestions/{started['id']}", headers=admin_headers
    )
    assert status.json()["state"] == "retryable_failed"
    assert status.json()["error_code"] == "INGEST_STALE_IMPORT"


def test_reconcile_requires_admin(ingest_client):
    client, _, _, _ = ingest_client
    response = client.post("/api/v1/admin/ingestions/reconcile")
    assert response.status_code == 401
