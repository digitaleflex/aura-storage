from __future__ import annotations

from uuid import uuid4


def _seed_work_edition(client, admin_headers, *, tracks=1, access_model="free", title="Livre"):
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
        json={"storage_object_id": f"obj-cover-{uuid4()}", "kind": "cover", "status": "ready"},
    ).json()
    edition = client.post(
        "/api/v1/admin/editions",
        headers=admin_headers,
        json={
            "work_id": work["id"],
            "title": title,
            "language": "fr",
            "description": "Edition",
            "duration_ms": 1000 * tracks,
            "cover_asset_id": cover["id"],
            "access_model": access_model,
        },
    ).json()
    track_ids = []
    for i in range(1, tracks + 1):
        audio = client.post(
            "/api/v1/admin/assets",
            headers=admin_headers,
            json={
                "storage_object_id": f"obj-audio-{uuid4()}",
                "kind": "source",
                "content_type": "audio/mpeg",
                "duration_ms": 1000,
                "status": "ready",
            },
        ).json()
        track = client.post(
            f"/api/v1/admin/editions/{edition['id']}/tracks",
            headers=admin_headers,
            json={
                "position": i,
                "title": f"Piste {i}",
                "start_ms": (i - 1) * 1000,
                "end_ms": i * 1000,
                "asset_id": audio["id"],
                "status": "ready",
            },
        ).json()
        track_ids.append(track["id"])
    client.post(
        f"/api/v1/admin/editions/{edition['id']}/rights",
        headers=admin_headers,
        json={
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "status": "active",
        },
    )
    publish = client.post(
        f"/api/v1/admin/editions/{edition['id']}/publish", headers=admin_headers
    )
    assert publish.status_code == 200, publish.text
    return {"work_id": work["id"], "edition_id": edition["id"], "track_ids": track_ids}


def test_publish_free_edition_with_three_tracks(client, admin_headers, listener):
    seeded = _seed_work_edition(client, admin_headers, tracks=3, title="Trois pistes")
    detail = client.get(f"/api/v1/catalog/{seeded['edition_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["tracks"]) == 3

    access = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert access.status_code == 200
    assert access.json()["allowed"] is True

    start = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": seeded["edition_id"]},
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session"]["id"]
    # Listen across all three tracks.
    seq = 1
    for track_id in seeded["track_ids"]:
        event = client.post(
            f"/api/v1/playback/sessions/{session_id}/events",
            headers=listener["headers"],
            json={
                "client_seq": seq,
                "kind": "heartbeat",
                "position_ms": seq * 100,
                "track_id": track_id,
                "duration_ms": 3000,
            },
        )
        assert event.status_code == 200
        assert event.json()["applied"] is True
        seq += 1
    progress = client.get(
        f"/api/v1/progress/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert progress.status_code == 200
    assert progress.json()["progress"]["position_ms"] == 300


def test_device_limit_and_management(client, listener):
    created = []
    for i in range(3):
        response = client.post(
            "/api/v1/devices",
            headers=listener["headers"],
            json={"name": f"Device {i+1}", "platform": "ios"},
        )
        assert response.status_code == 200, response.text
        created.append(response.json())

    fourth = client.post(
        "/api/v1/devices",
        headers=listener["headers"],
        json={"name": "Device 4", "platform": "web"},
    )
    assert fourth.status_code == 409, fourth.text
    assert fourth.json()["error"] == "TOO_MANY_DEVICES"

    listed = client.get("/api/v1/devices", headers=listener["headers"])
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 3

    revoke = client.post(
        f"/api/v1/devices/{created[0]['id']}/revoke",
        headers=listener["headers"],
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    # Slot freed after revocation.
    again = client.post(
        "/api/v1/devices",
        headers=listener["headers"],
        json={"name": "Device 4", "platform": "web"},
    )
    assert again.status_code == 200, again.text


def test_simultaneous_playback_session_limit(client, admin_headers, listener):
    editions = [
        _seed_work_edition(client, admin_headers, tracks=1, title=f"Livre {i}")
        for i in range(3)
    ]
    s1 = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": editions[0]["edition_id"]},
    )
    assert s1.status_code == 200, s1.text
    s2 = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": editions[1]["edition_id"]},
    )
    assert s2.status_code == 200, s2.text

    s3 = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": editions[2]["edition_id"]},
    )
    assert s3.status_code == 409, s3.text
    assert s3.json()["error"] == "TOO_MANY_ACTIVE_SESSIONS"

    # Replacing an existing session on the same edition is allowed.
    takeover = client.post(
        "/api/v1/playback/sessions",
        headers=listener["headers"],
        json={"edition_id": editions[0]["edition_id"], "takeover": True},
    )
    assert takeover.status_code == 200, takeover.text


def test_edition_suspend_denies_access(client, seeded, listener, admin_headers):
    suspend = client.post(
        f"/api/v1/admin/editions/{seeded['edition_id']}/suspend",
        headers=admin_headers,
    )
    assert suspend.status_code == 200, suspend.text
    assert suspend.json()["status"] == "suspended"

    access = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert access.status_code == 200
    assert access.json()["allowed"] is False
    assert access.json()["reason_code"] == "EDITION_NOT_PUBLISHED"

    catalog = client.get("/api/v1/catalog")
    assert all(item["id"] != seeded["edition_id"] for item in catalog.json()["items"])

    unsuspend = client.post(
        f"/api/v1/admin/editions/{seeded['edition_id']}/unsuspend",
        headers=admin_headers,
    )
    assert unsuspend.status_code == 200
    assert unsuspend.json()["status"] == "published"

    access2 = client.get(
        f"/api/v1/access/{seeded['edition_id']}", headers=listener["headers"]
    )
    assert access2.status_code == 200
    assert access2.json()["allowed"] is True


def test_profile_update_and_deletion_request(client, listener):
    updated = client.patch(
        "/api/v1/me",
        headers=listener["headers"],
        json={"display_name": "Nouveau Nom", "locale": "en", "timezone": "UTC"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["listener"]["display_name"] == "Nouveau Nom"
    assert updated.json()["listener"]["locale"] == "en"

    deletion = client.post("/api/v1/me/deletion-request", headers=listener["headers"])
    assert deletion.status_code == 200, deletion.text
    assert deletion.json()["listener"]["status"] == "pending_deletion"
    assert deletion.json()["listener"]["deletion_requested_at"] is not None

    # Pending deletion accounts cannot obtain access decisions.
    # (No active session/auth usable here because sessions were revoked; but
    # domain/profile state is recorded.)
    me = client.get("/api/v1/me", headers=listener["headers"])
    assert me.status_code in (401, 403)


def test_personal_collections_are_private_and_non_cascading(client, listener, seeded):
    created = client.post(
        "/api/v1/personal-collections",
        headers=listener["headers"],
        json={"title": "Mes favoris du soir", "description": "Sélection"},
    )
    assert created.status_code == 200, created.text
    collection_id = created.json()["id"]

    added = client.post(
        f"/api/v1/personal-collections/{collection_id}/items",
        headers=listener["headers"],
        json={"work_id": seeded["work_id"], "position": 1},
    )
    assert added.status_code == 200, added.text

    listed = client.get("/api/v1/personal-collections", headers=listener["headers"])
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["item_count"] == 1

    detail = client.get(
        f"/api/v1/personal-collections/{collection_id}", headers=listener["headers"]
    )
    assert detail.status_code == 200
    assert detail.json()["items"][0]["work_id"] == seeded["work_id"]

    deleted = client.delete(
        f"/api/v1/personal-collections/{collection_id}", headers=listener["headers"]
    )
    assert deleted.status_code == 200
    # Deleting a personal collection must not remove the library/work reference.
    library = client.get("/api/v1/library", headers=listener["headers"])
    assert library.status_code == 200

    # Another listener cannot access it.
    other = client.post(
        "/api/v1/auth/dev-login",
        json={"email": "other@example.test", "display_name": "Other"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    forbidden = client.get(
        f"/api/v1/personal-collections/{collection_id}", headers=other_headers
    )
    assert forbidden.status_code == 404


def test_categories_and_editorial_collections(client, admin_headers):
    category = client.post(
        "/api/v1/admin/categories",
        headers=admin_headers,
        json={"slug": "fiction", "name": "Fiction", "description": "Romans"},
    )
    assert category.status_code == 200, category.text
    cats = client.get("/api/v1/categories")
    assert cats.status_code == 200
    assert any(c["slug"] == "fiction" for c in cats.json()["items"])

    seeded = _seed_work_edition(client, admin_headers, tracks=1, title="Collectionné")
    collection = client.post(
        "/api/v1/admin/editorial-collections",
        headers=admin_headers,
        json={"slug": "selection", "title": "Sélection", "description": "x"},
    )
    assert collection.status_code == 200, collection.text
    collection_id = collection.json()["id"]
    add_item = client.post(
        f"/api/v1/admin/editorial-collections/{collection_id}/items",
        headers=admin_headers,
        json={"edition_id": seeded["edition_id"], "position": 1},
    )
    assert add_item.status_code == 200, add_item.text

    # Draft editorial collections are not publicly listed.
    public = client.get("/api/v1/editorial-collections")
    assert public.status_code == 200
    assert all(c["id"] != collection_id for c in public.json()["items"])

    published = client.post(
        f"/api/v1/admin/editorial-collections/{collection_id}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    public2 = client.get("/api/v1/editorial-collections")
    assert any(c["id"] == collection_id for c in public2.json()["items"])
