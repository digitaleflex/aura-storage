"""Audio classification sandbox: opt-in enqueue, review and tag application."""
import json
import os
import time
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402


def _admin():
    client = TestClient(main.app)
    response = client.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def _object(display_name: str, content_type: str) -> str:
    application_id, space_id = main.repo.default_scope()[:2]
    oid = main.repo.create_pending_object(
        space_id=space_id, application_id=application_id, environment="test",
        bucket="aura", object_key=f"aura/{uuid.uuid4()}",
        display_name=display_name, content_type=content_type, owner_id=None,
        actor_id="tester", actor_kind="user",
        intent_expires_at=int(time.time()) + 900,
    )
    main.repo.mark_available(oid, 1000, "checksum")
    return oid


def test_enqueue_is_opt_in():
    client, headers = _admin()
    response = client.post(
        "/api/v1/audio-classifications/enqueue",
        json={"object_ids": [str(uuid.uuid4())]}, headers=headers,
    )
    assert response.status_code == 409, response.text


def test_enqueue_review_and_tag_application(monkeypatch):
    monkeypatch.setattr(main.settings, "ai_classification_enabled", True)
    client, headers = _admin()
    audio_id = _object("Auteur - Méditation.mp3", "audio/mpeg")

    response = client.post(
        "/api/v1/audio-classifications/enqueue",
        json={"object_ids": [audio_id, str(uuid.uuid4())]}, headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["enqueued"]) == 1
    assert payload["skipped"][0]["reason"] == "not_found"
    jid = payload["enqueued"][0]["job_id"]

    # A second enqueue reuses the active job instead of flooding the queue.
    again = client.post(
        "/api/v1/audio-classifications/enqueue",
        json={"object_ids": [audio_id]}, headers=headers,
    )
    assert again.json()["enqueued"][0]["job_id"] == jid
    jobs = client.get("/api/v1/audio-classifications", headers=headers).json()["items"]
    assert len([job for job in jobs if job["id"] == jid]) == 1

    main.repo.complete_audio_classification_job(
        jid, provider="heuristic", model="none", confidence=0.9,
        suggested_category="meditation",
        suggested_themes=json.dumps(["calme"]), suggested_language="fr",
        suggested_folder="Audiobooks/meditation", quality_json="{}",
        transcript_excerpt=None, reason="test", result_json="{}",
    )
    detail = client.get(f"/api/v1/audio-classifications/{jid}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "needs_review"
    assert detail.json()["suggested_themes"] == ["calme"]

    accepted = client.post(
        f"/api/v1/audio-classifications/{jid}/review",
        json={"action": "accept"}, headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    tags = main.repo.get_object_tags(audio_id)
    assert {"categorie-meditation", "theme-calme", "langue-fr"} <= set(tags)

    # A reviewed job is immutable; the catalogue is not moved or published.
    again = client.post(
        f"/api/v1/audio-classifications/{jid}/review",
        json={"action": "reject"}, headers=headers,
    )
    assert again.status_code == 409
    assert main.repo.get_object_global(audio_id)["status"] == "available"


def test_enqueue_skips_non_audio_objects(monkeypatch):
    monkeypatch.setattr(main.settings, "ai_classification_enabled", True)
    client, headers = _admin()
    text_id = _object("notes.txt", "text/plain")
    response = client.post(
        "/api/v1/audio-classifications/enqueue",
        json={"object_ids": [text_id]}, headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["enqueued"] == []
    assert response.json()["skipped"][0]["reason"] == "not_audio"
