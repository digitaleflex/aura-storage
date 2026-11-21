from __future__ import annotations

from uuid import uuid4


def test_catalog_lists_published_free_edition(client, seeded):
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == seeded["edition_id"]
    assert item["access_model"] == "free"
    assert item["ready_track_count"] == 1

    detail = client.get(f"/api/v1/catalog/{seeded['edition_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["edition"]["id"] == seeded["edition_id"]
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["id"] == seeded["track_id"]
    assert body["authors"][0]["name"] == "Awa Diallo"
    assert body["narrators"][0]["name"] == "Nora Mensah"


def test_library_and_free_access_decision_are_audited(client, seeded, listener, admin_headers):
    add = client.post(
        "/api/v1/library",
        headers=listener["headers"],
        json={"work_id": seeded["work_id"]},
    )
    assert add.status_code == 200, add.text
    entry = add.json()
    assert entry["work_id"] == seeded["work_id"]
    assert entry["preferred_edition_id"] == seeded["edition_id"]
    assert entry["removed_at"] is None

    listed = client.get("/api/v1/library", headers=listener["headers"])
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    access = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert access.status_code == 200, access.text
    decision = access.json()
    assert decision["allowed"] is True
    assert decision["reason_code"] == "ALLOWED"
    assert "free" in decision["sources"]
    assert any(s.startswith("rights:") for s in decision["sources"])
    assert decision["expires_at"] is not None

    audit = client.get("/api/v1/admin/audit?limit=200", headers=admin_headers)
    assert audit.status_code == 200, audit.text
    actions = [item["action"] for item in audit.json()["items"]]
    assert "library.add" in actions
    assert "access.stream" in actions
    assert any(
        item["action"] == "access.stream" and item["outcome"] == "success"
        for item in audit.json()["items"]
    )


def test_vertical_slice_two_devices_progress_conflict_and_takeover(
    client, seeded, listener, app, admin_headers
):
    repo = app.state.repo
    device_a = repo.create_device(listener["listener"]["id"], name="Phone", platform="ios")
    device_b = repo.create_device(
        listener["listener"]["id"], name="Tablet", platform="android"
    )

    # Device A starts a session and listens.
    start_a = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": seeded["edition_id"], "device_id": str(device_a["id"])},
    )
    assert start_a.status_code == 200, start_a.text
    session_a = start_a.json()["session"]["id"]
    assert start_a.json()["progress"]["position_ms"] == 0

    event1 = client.post(
        f"/api/v1/playback/sessions/{session_a}/events",
        headers=listener["headers"],
        json={
            "event_id": str(uuid4()),
            "client_seq": 1,
            "kind": "start",
            "position_ms": 0,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert event1.status_code == 200, event1.text
    assert event1.json()["applied"] is True
    assert event1.json()["progress"]["version"] == 2

    event2 = client.post(
        f"/api/v1/playback/sessions/{session_a}/events",
        headers=listener["headers"],
        json={
            "client_seq": 2,
            "kind": "heartbeat",
            "position_ms": 45000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert event2.status_code == 200
    assert event2.json()["progress"]["position_ms"] == 45000

    # Stale sequence from device A is rejected without moving progress.
    stale = client.post(
        f"/api/v1/playback/sessions/{session_a}/events",
        headers=listener["headers"],
        json={
            "client_seq": 2,
            "kind": "heartbeat",
            "position_ms": 90000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["applied"] is False
    assert stale.json()["reason"] == "stale_sequence"
    assert stale.json()["progress"]["position_ms"] == 45000

    # Device B cannot start while A holds the active lease.
    start_b_conflict = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={
            "edition_id": seeded["edition_id"],
            "device_id": str(device_b["id"]),
            "takeover": False,
        },
    )
    assert start_b_conflict.status_code == 409, start_b_conflict.text
    assert start_b_conflict.json()["error"] == "ACTIVE_SESSION_EXISTS"

    # Device B takes over and resumes from authoritative progress.
    progress = client.get(
        f"/api/v1/progress/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert progress.status_code == 200
    assert progress.json()["progress"]["position_ms"] == 45000
    assert progress.json()["active_session_id"] == session_a

    start_b = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={
            "edition_id": seeded["edition_id"],
            "device_id": str(device_b["id"]),
            "takeover": True,
        },
    )
    assert start_b.status_code == 200, start_b.text
    session_b = start_b.json()["session"]["id"]
    assert session_b != session_a
    assert start_b.json()["progress"]["position_ms"] == 45000

    # Old session can no longer advance progress.
    old_event = client.post(
        f"/api/v1/playback/sessions/{session_a}/events",
        headers=listener["headers"],
        json={
            "client_seq": 3,
            "kind": "heartbeat",
            "position_ms": 47000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert old_event.status_code == 200, old_event.text
    assert old_event.json()["applied"] is False
    assert old_event.json()["conflict"] is True
    assert old_event.json()["progress"]["position_ms"] == 45000

    # Device B continues; seek rewinds explicitly and completion is recorded.
    seek = client.post(
        f"/api/v1/playback/sessions/{session_b}/events",
        headers=listener["headers"],
        json={
            "client_seq": 1,
            "kind": "seek",
            "position_ms": 10000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert seek.status_code == 200
    assert seek.json()["applied"] is True
    assert seek.json()["progress"]["position_ms"] == 10000

    ended = client.post(
        f"/api/v1/playback/sessions/{session_b}/events",
        headers=listener["headers"],
        json={
            "client_seq": 2,
            "kind": "ended",
            "position_ms": 600000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["applied"] is True
    assert ended.json()["progress"]["completed_at"] is not None
    assert ended.json()["session_state"] == "ended"

    # Duplicate event id is idempotent.
    fixed_event_id = str(uuid4())
    first = client.post(
        f"/api/v1/playback/sessions/{session_b}/events",
        headers=listener["headers"],
        json={
            "event_id": fixed_event_id,
            "client_seq": 3,
            "kind": "heartbeat",
            "position_ms": 600000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    dup = client.post(
        f"/api/v1/playback/sessions/{session_b}/events",
        headers=listener["headers"],
        json={
            "event_id": fixed_event_id,
            "client_seq": 3,
            "kind": "heartbeat",
            "position_ms": 600000,
            "track_id": seeded["track_id"],
            "duration_ms": 600000,
        },
    )
    assert first.status_code == 200
    assert dup.status_code == 200
    assert dup.json()["duplicate"] is True
    assert dup.json()["progress"]["version"] == first.json()["progress"]["version"]

    audit = client.get("/api/v1/admin/audit?limit=500", headers=admin_headers)
    actions = [item["action"] for item in audit.json()["items"]]
    assert "playback.session.started" in actions
    assert "playback.event" in actions


def test_playback_url_requires_access_and_audits(client, seeded, listener, admin_headers):
    start = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": seeded["edition_id"]},
    )
    assert start.status_code == 200, start.text

    url = client.post(
        f"/api/v1/playback/editions/{seeded['edition_id']}/tracks/{seeded['track_id']}/url",
        headers=listener["headers"],
    )
    assert url.status_code == 200, url.text
    body = url.json()
    assert body["url"].startswith("https://media.test/")
    assert body["decision"]["allowed"] is True
    assert body["content_type"] == "audio/mpeg"

    audit = client.get("/api/v1/admin/audit?limit=200", headers=admin_headers)
    assert any(
        item["action"] == "playback.url.issued" and item["outcome"] == "success"
        for item in audit.json()["items"]
    )


def test_denied_access_for_unpublished_edition_and_paid_without_entitlement(
    client, admin_headers, listener
):
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": "Payant", "language": "fr", "description": "x"},
    ).json()
    client.post(
        f"/api/v1/admin/works/{work['id']}/contributors",
        headers=admin_headers,
        json={"name": "Auteur", "role": "author"},
    )
    client.post(
        f"/api/v1/admin/works/{work['id']}/contributors",
        headers=admin_headers,
        json={"name": "Narrateur", "role": "narrator"},
    )
    client.post(f"/api/v1/admin/works/{work['id']}/approve", headers=admin_headers)
    cover = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={"storage_object_id": "obj-cover-paid", "kind": "cover", "status": "ready"},
    ).json()
    audio = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={
            "storage_object_id": "obj-audio-paid",
            "kind": "source",
            "content_type": "audio/mpeg",
            "duration_ms": 1000,
            "status": "ready",
        },
    ).json()
    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work["id"],
            "title": "Payant",
            "language": "fr",
            "description": "Edition payante",
            "duration_ms": 1000,
            "cover_asset_id": cover["id"],
            "access_model": "paid",
        },
    ).json()
    client.post(
        f"/api/v1/admin/editions/{edition['id']}/tracks",
        headers=admin_headers,
        json={
            "position": 1,
            "title": "Piste",
            "start_ms": 0,
            "end_ms": 1000,
            "asset_id": audio["id"],
            "status": "ready",
        },
    )
    client.post(
        f"/api/v1/admin/editions/{edition['id']}/rights",
        headers=admin_headers,
        json={
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "status": "active",
        },
    )

    # Not published: not visible in public catalog and access denied.
    catalog = client.get("/api/v1/catalog")
    assert all(item["id"] != edition["id"] for item in catalog.json()["items"])
    denied_unpublished = client.get(
        f"/api/v1/access/{edition['id']}", headers=listener["headers"]
    )
    assert denied_unpublished.status_code == 200
    assert denied_unpublished.json()["allowed"] is False
    assert denied_unpublished.json()["reason_code"] == "EDITION_NOT_PUBLISHED"

    publish = client.post(
        f"/api/v1/admin/editions/{edition['id']}/publish", headers=admin_headers
    )
    assert publish.status_code == 200, publish.text

    denied_paid = client.get(
        f"/api/v1/access/{edition['id']}", headers=listener["headers"]
    )
    assert denied_paid.status_code == 200
    assert denied_paid.json()["allowed"] is False
    assert denied_paid.json()["reason_code"] == "NO_ACTIVE_ENTITLEMENT"

    grant = client.post(
        "/api/v1/admin/entitlements",
        headers=admin_headers,
        json={
            "listener_id": listener["listener"]["id"],
            "source_type": "manual",
            "source_id": "grant-1",
            "scope_type": "edition",
            "scope_id": edition["id"],
            "status": "active",
        },
    )
    assert grant.status_code == 200, grant.text

    allowed = client.get(
        f"/api/v1/access/{edition['id']}", headers=listener["headers"]
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True
    assert allowed.json()["reason_code"] == "ALLOWED"
