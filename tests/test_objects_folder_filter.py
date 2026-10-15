"""Issue #62: object list exposes and filters by folder (offline, SQLite).

The objects catalogue has always carried ``folder_id``; the list/get responses
now surface it and ``GET /api/v1/objects`` accepts an optional ``folder_id``
filter ("root" = not filed). No S3 endpoint is contacted: upload intents only
create a pending row and presign a URL.
"""
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _new_folder(c, headers, name):
    r = c.post("/api/v1/folders", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(c, headers, name, folder_id=None):
    body = {"display_name": name, "size_bytes": 1}
    if folder_id is not None:
        body["folder_id"] = folder_id
    r = c.post("/api/v1/objects/upload-intents", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ids(payload):
    return {i["id"] for i in payload["items"]}


def test_objects_expose_and_filter_by_folder():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    fid = _new_folder(c, headers, f"folder-{tag}")

    filed = _upload(c, headers, f"filed-{tag}.txt", folder_id=fid)
    unfiled = _upload(c, headers, f"unfiled-{tag}.txt")

    # The response now carries folder_id.
    everything = c.get("/api/v1/objects", headers=headers).json()
    by_id = {i["id"]: i for i in everything["items"]}
    assert by_id[filed]["folder_id"] == fid
    assert by_id[unfiled]["folder_id"] is None

    # Filtering by the folder returns only the filed object.
    in_folder = c.get("/api/v1/objects", params={"folder_id": fid}, headers=headers)
    assert in_folder.status_code == 200
    assert _ids(in_folder.json()) == {filed}

    # "root" returns only the unfiled object.
    root = c.get("/api/v1/objects", params={"folder_id": "root"}, headers=headers)
    assert root.status_code == 200
    root_ids = _ids(root.json())
    assert unfiled in root_ids
    assert filed not in root_ids

    # GET by id also surfaces folder_id.
    got = c.get(f"/api/v1/objects/{filed}", headers=headers)
    assert got.status_code == 200 and got.json()["folder_id"] == fid


def test_folder_filter_rejects_malformed_id():
    c, headers = _admin()
    r = c.get("/api/v1/objects", params={"folder_id": "not-a-uuid"}, headers=headers)
    assert r.status_code == 422


def test_folder_filter_unknown_folder_matches_nothing():
    c, headers = _admin()
    tag = uuid.uuid4().hex[:8]
    _upload(c, headers, f"loose-{tag}.txt")
    other = c.get(
        "/api/v1/objects", params={"folder_id": str(uuid.uuid4())}, headers=headers
    )
    assert other.status_code == 200
    assert other.json()["items"] == []
