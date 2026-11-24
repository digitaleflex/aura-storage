from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4


def _seed_paid_edition(client, admin_headers, *, title="Payant", territory="WORLD"):
    work = client.post(
        "/api/v1/admin/works",
        headers=admin_headers,
        json={"title": title, "language": "fr", "description": "Desc"},
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
        json={
            "storage_object_id": f"obj-cover-{uuid4()}",
            "kind": "cover",
            "status": "ready",
        },
    ).json()
    audio = client.post(
        "/api/v1/admin/assets",
        headers=admin_headers,
        json={
            "storage_object_id": f"obj-audio-{uuid4()}",
            "kind": "source",
            "content_type": "audio/mpeg",
            "duration_ms": 60000,
            "status": "ready",
        },
    ).json()
    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work["id"],
            "title": title,
            "language": "fr",
            "description": "Edition payante",
            "duration_ms": 60000,
            "cover_asset_id": cover["id"],
            "access_model": "paid",
        },
    ).json()
    track = client.post(
        f"/api/v1/admin/editions/{edition['id']}/tracks",
        headers=admin_headers,
        json={
            "position": 1,
            "title": "Piste",
            "start_ms": 0,
            "end_ms": 60000,
            "asset_id": audio["id"],
            "status": "ready",
        },
    ).json()
    client.post(
        f"/api/v1/admin/editions/{edition['id']}/rights",
        headers=admin_headers,
        json={
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2030-01-01T00:00:00Z",
            "territory_code": territory,
            "status": "active",
        },
    )
    publish = client.post(
        f"/api/v1/admin/editions/{edition['id']}/publish", headers=admin_headers
    )
    assert publish.status_code == 200, publish.text
    return {
        "work_id": work["id"],
        "edition_id": edition["id"],
        "track_id": track["id"],
    }


def test_library_does_not_grant_access_without_entitlement(
    client, admin_headers, listener
):
    seeded = _seed_paid_edition(client, admin_headers, title="Sans droit")
    add = client.post(
        "/api/v1/library",
        headers=listener["headers"],
        json={"work_id": seeded["work_id"]},
    )
    assert add.status_code == 200

    access = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert access.status_code == 200
    assert access.json()["allowed"] is False
    assert access.json()["reason_code"] == "NO_ACTIVE_ENTITLEMENT"


def test_revoked_or_expired_entitlement_denies_access(client, admin_headers, listener):
    seeded = _seed_paid_edition(client, admin_headers, title="Révoqué")
    grant = client.post(
        "/api/v1/admin/entitlements",
        headers=admin_headers,
        json={
            "listener_id": listener["listener"]["id"],
            "source_type": "manual",
            "source_id": "grant-revoke",
            "scope_type": "edition",
            "scope_id": seeded["edition_id"],
            "status": "active",
        },
    )
    assert grant.status_code == 200, grant.text
    entitlement_id = grant.json()["id"]

    allowed = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert allowed.json()["allowed"] is True

    revoke = client.post(
        f"/api/v1/admin/entitlements/{entitlement_id}/revoke",
        headers=admin_headers,
        json={"reason": "refund"},
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"

    denied = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert denied.json()["allowed"] is False
    assert denied.json()["reason_code"] == "NO_ACTIVE_ENTITLEMENT"

    # Expired entitlement (validity window in the past) must not grant access.
    expired_seed = _seed_paid_edition(client, admin_headers, title="Expiré")
    past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    older = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    client.post(
        "/api/v1/admin/entitlements",
        headers=admin_headers,
        json={
            "listener_id": listener["listener"]["id"],
            "source_type": "promotion",
            "source_id": "promo-expired",
            "scope_type": "edition",
            "scope_id": expired_seed["edition_id"],
            "valid_from": older,
            "valid_until": past,
            "status": "active",
        },
    )
    expired = client.get(
        f"/api/v1/access/{expired_seed['edition_id']}", headers=listener["headers"]
    )
    assert expired.json()["allowed"] is False
    assert expired.json()["reason_code"] == "NO_ACTIVE_ENTITLEMENT"


def test_rights_withdrawal_or_territory_restriction_denies_access(
    client, admin_headers, listener, app
):
    seeded = _seed_paid_edition(
        client, admin_headers, title="Territoire", territory="FR"
    )
    client.post(
        "/api/v1/admin/entitlements",
        headers=admin_headers,
        json={
            "listener_id": listener["listener"]["id"],
            "source_type": "manual",
            "source_id": "grant-fr",
            "scope_type": "edition",
            "scope_id": seeded["edition_id"],
            "status": "active",
        },
    )

    denied = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Territory": "US"},
    )
    assert denied.status_code == 200
    assert denied.json()["allowed"] is False
    assert denied.json()["reason_code"] == "TERRITORY_RESTRICTED"

    allowed = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Territory": "FR"},
    )
    assert allowed.json()["allowed"] is True

    # Withdraw rights by terminating the active window: no diffusion.
    with app.state.db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE rights_windows SET status = 'terminated' WHERE edition_id = %s",
                (seeded["edition_id"],),
            )
    withdrawn = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Territory": "FR"},
    )
    assert withdrawn.json()["allowed"] is False
    assert withdrawn.json()["reason_code"] == "NO_ACTIVE_RIGHTS"


def test_device_authorization_and_history_stats(client, seeded, listener, app, admin_headers):
    repo = app.state.repo
    device = repo.create_device(
        listener["listener"]["id"], name="Phone", platform="ios"
    )

    allowed = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Device-Id": str(device["id"])},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True

    # Unknown/revoked device in access context is denied.
    denied = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Device-Id": str(uuid4())},
    )
    assert denied.status_code == 200
    assert denied.json()["allowed"] is False
    assert denied.json()["reason_code"] == "DEVICE_NOT_AUTHORIZED"

    repo.revoke_device(listener["listener"]["id"], device["id"])
    revoked = client.get(
        f"/api/v1/access/{seeded['edition_id']}",
        headers={**listener["headers"], "X-Device-Id": str(device["id"])},
    )
    assert revoked.json()["allowed"] is False
    assert revoked.json()["reason_code"] == "DEVICE_NOT_AUTHORIZED"

    # Listening history/stats (basic, from events/progress).
    active_device = repo.create_device(
        listener["listener"]["id"], name="Tablet", platform="android"
    )
    start = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={
            "edition_id": seeded["edition_id"],
            "device_id": str(active_device["id"]),
        },
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session"]["id"]
    for seq, kind, pos in [(1, "start", 0), (2, "ended", 600000)]:
        ev = client.post(
            f"/api/v1/playback/sessions/{session_id}/events",
            headers=listener["headers"],
            json={
                "client_seq": seq,
                "kind": kind,
                "position_ms": pos,
                "track_id": seeded["track_id"],
                "duration_ms": 600000,
            },
        )
        assert ev.status_code == 200, ev.text

    history = client.get("/api/v1/history", headers=listener["headers"])
    assert history.status_code == 200
    assert len(history.json()["items"]) >= 1
    assert history.json()["items"][0]["edition_id"] == seeded["edition_id"]

    stats = client.get("/api/v1/stats", headers=listener["headers"])
    assert stats.status_code == 200
    body = stats.json()
    assert body["started"] >= 1
    assert body["completed"] >= 1
    assert body["applied_events"] >= 2


def test_access_refusal_dashboard_and_contracts(client, admin_headers, listener):
    # Generate refusals.
    missing = uuid4()
    denied = client.get(
        f"/api/v1/access/{missing}", headers=listener["headers"]
    )
    assert denied.status_code == 404

    paid = _seed_paid_edition(client, admin_headers, title="Refusé")
    refusal = client.get(
        f"/api/v1/access/{paid['edition_id']}", headers=listener["headers"]
    )
    assert refusal.json()["allowed"] is False

    dashboard = client.get(
        "/api/v1/admin/access-refusals", headers=admin_headers
    )
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert any(r["reason_code"] == "NO_ACTIVE_ENTITLEMENT" for r in body["by_reason"])
    assert len(body["recent"]) >= 1

    contract = client.post(
        "/api/v1/admin/contracts",
        headers=admin_headers,
        json={
            "name": "Contrat catalogue",
            "licensor": "Éditeur",
            "territory_scope": "WORLD",
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2030-01-01T00:00:00Z",
            "status": "active",
            "notes": "Lot 2",
        },
    )
    assert contract.status_code == 200, contract.text
    contracts = client.get("/api/v1/admin/contracts", headers=admin_headers)
    assert contracts.status_code == 200
    assert any(c["id"] == contract.json()["id"] for c in contracts.json()["items"])


def test_listener_territory_used_when_header_absent(client, admin_headers, listener):
    seeded = _seed_paid_edition(client, admin_headers, title="Profil FR", territory="FR")
    client.post(
        "/api/v1/admin/entitlements",
        headers=admin_headers,
        json={
            "listener_id": listener["listener"]["id"],
            "source_type": "manual",
            "source_id": "grant-fr-profile",
            "scope_type": "edition",
            "scope_id": seeded["edition_id"],
            "status": "active",
        },
    )
    # Default listener territory is WORLD -> FR-only rights deny as territory restricted.
    denied = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert denied.json()["allowed"] is False
    assert denied.json()["reason_code"] == "TERRITORY_RESTRICTED"

    updated = client.patch(
        "/api/v1/me",
        headers=listener["headers"],
        json={"territory_code": "FR"},
    )
    assert updated.status_code == 200, updated.text

    allowed = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert allowed.json()["allowed"] is True


def test_preferences_validate_and_persist(client, listener):
    body = {
        "preferred_languages": ["fr"],
        "preferred_category_slugs": ["roman"],
        "preferred_authors": ["Awa Diallo"],
        "preferred_narrators": ["Nora Mensah"],
        "min_duration_ms": 60_000,
        "max_duration_ms": 3_600_000,
        "prefer_completed": False,
    }
    saved = client.put(
        "/api/v1/me/preferences", headers=listener["headers"], json=body
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["preferences"]["preferred_authors"] == ["Awa Diallo"]

    read = client.get("/api/v1/me/preferences", headers=listener["headers"])
    assert read.status_code == 200, read.text
    assert read.json()["preferences"]["preferred_languages"] == ["fr"]

    invalid = client.put(
        "/api/v1/me/preferences",
        headers=listener["headers"],
        json={**body, "min_duration_ms": 5_000_000},
    )
    assert invalid.status_code == 422, invalid.text


def test_recommendations_use_preferences_and_explain_them(client, listener, seeded):
    client.put(
        "/api/v1/me/preferences",
        headers=listener["headers"],
        json={
            "preferred_languages": ["fr"],
            "preferred_category_slugs": [],
            "preferred_authors": ["Awa Diallo"],
            "preferred_narrators": [],
            "min_duration_ms": None,
            "max_duration_ms": None,
            "prefer_completed": False,
        },
    )
    result = client.get(
        "/api/v1/me/recommendations?limit=5", headers=listener["headers"]
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["meta"]["has_explicit_preferences"] is True
    assert body["meta"]["candidate_count"] >= 1
    assert body["items"], "the published seeded edition must be a candidate"
    top = body["items"][0]
    assert top["edition_id"] == seeded["edition_id"]
    assert "preferred_author" in top["reasons"]
    assert "preferred_language" in top["reasons"]
