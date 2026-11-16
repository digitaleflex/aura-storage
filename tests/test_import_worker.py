import os
import uuid

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret456789012345678901234567890")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-importworker-audit.jsonl")
os.environ.setdefault("AURA_IMPORT_WORKER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import import_worker  # noqa: E402


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _admin_client():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin",
        "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


def _clear_import_jobs():
    main.repo.conn.execute("DELETE FROM import_jobs")
    main.repo.conn.commit()


def test_worker_processes_queued_job_to_done():
    _clear_import_jobs()
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs", json={"total_items": 7}, headers=headers)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert r.json()["status"] == "queued"

    outcome = import_worker.run_once(main.repo, main.settings)
    assert outcome == "done"

    row = main.repo.get_import_job_by_id(jid)
    assert row["status"] == "done"
    assert row["processed_items"] == 7
    assert row["failed_items"] == 0
    assert row["summary"]


def test_worker_respects_cancelled_job():
    _clear_import_jobs()
    c, headers = _admin_client()
    r = c.post("/api/v1/import-jobs", json={"total_items": 3}, headers=headers)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]

    r = c.post(f"/api/v1/import-jobs/{jid}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    outcome = import_worker.run_once(main.repo, main.settings)
    assert outcome is None or outcome == "cancelled"

    row = main.repo.get_import_job_by_id(jid)
    assert row["status"] == "cancelled"


def test_worker_idle_when_no_jobs():
    _clear_import_jobs()
    assert import_worker.run_once(main.repo, main.settings) is None
