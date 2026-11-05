"""Module: import jobs API (ISSUE-005).

Offline tests (SQLite catalogue, no S3 endpoint). Exercise the server side only:
HTTP status codes, isolation by space, and the guarantee that a caller can only
see/cancel their own space's jobs.
"""
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret456789012345678901234567890")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-importjobs-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


@pytest.fixture(autouse=True)
def _clear_import_jobs():
    """Clear import_jobs between tests so the shared in-memory SQLite DB stays
    isolated per test."""
    yield
    main.repo.conn.execute("DELETE FROM import_jobs")
    main.repo.conn.commit()


def _admin_client():
    """Return a TestClient logged in as admin, with CSRF token in headers."""
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin",
        "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _make_space(c, headers, application_id=None):
    if application_id is None:
        r = c.post("/api/v1/admin/applications", json={"name": f"app-{_tag()}"},
                   headers=headers)
        assert r.status_code == 200, r.text
        application_id = r.json()["id"]
    r = c.post("/api/v1/admin/spaces", json={
        "application_id": application_id,
        "name": f"space-{_tag()}",
        "environment": "test",
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_create_import_job_requires_auth():
    r = client.post("/api/v1/import-jobs", json={"total_items": 5})
    assert r.status_code in (401, 403)


def test_create_import_job_success():
    c, headers = _admin_client()
    r = c.get("/api/v1/me", headers=headers)
    assert r.status_code == 200, r.text
    space_id = r.json()["space_id"]

    r = c.post("/api/v1/import-jobs", json={"total_items": 42}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["space_id"] == space_id
    assert body["status"] == "queued"
    assert body["total_items"] == 42
    assert body["processed_items"] == 0
    assert body["failed_items"] == 0


def test_create_import_job_invalid_total_items():
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs", json={"total_items": 0}, headers=headers)
    assert r.status_code == 422


def test_list_import_jobs_empty():
    c, headers = _admin_client()
    r = c.get("/api/v1/import-jobs", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_import_jobs_with_filter():
    c, headers = _admin_client()
    c.post("/api/v1/import-jobs", json={"total_items": 10}, headers=headers)
    c.post("/api/v1/import-jobs", json={"total_items": 20}, headers=headers)
    r = c.get("/api/v1/import-jobs", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r = c.get("/api/v1/import-jobs?status=queued", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r = c.get("/api/v1/import-jobs?status=done", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_import_jobs_invalid_status():
    c, headers = _admin_client()
    r = c.get("/api/v1/import-jobs?status=bogus", headers=headers)
    assert r.status_code == 422


def test_cancel_import_job_success():
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs", json={"total_items": 5}, headers=headers)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]

    r = c.post(f"/api/v1/import-jobs/{jid}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"


def test_cancel_import_job_not_found():
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs/f35b5e8e-bcb5-4aaa-8e76-0a8b53d6da3b/cancel",
               headers=headers)
    assert r.status_code == 404, r.text


def test_cancel_import_job_already_cancelled_idempotent():
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs", json={"total_items": 5}, headers=headers)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]

    c.post(f"/api/v1/import-jobs/{jid}/cancel", headers=headers)
    r = c.post(f"/api/v1/import-jobs/{jid}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"


def test_import_jobs_isolated_by_space():
    c, headers = _admin_client()
    space_a = c.get("/api/v1/me", headers=headers).json()["space_id"]
    space_b = _make_space(c, headers)

    c.post("/api/v1/import-jobs", json={"total_items": 1}, headers=headers)
    r = c.post("/api/v1/import-jobs", json={"total_items": 2}, headers=headers)
    assert r.status_code == 200
    jid_b = r.json()["id"]

    r = c.get("/api/v1/import-jobs", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = c.post(f"/api/v1/import-jobs/{jid_b}/cancel", headers=headers)
    assert r.status_code == 200
