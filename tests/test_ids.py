"""Canonical identifiers (``api/ids.py``) and their enforcement at the API edge.

Every id AURA issues is a lowercase UUID v4 in 8-4-4-4-12 form. These tests pin
the unit contract, then exercise the FastAPI boundary: malformed ids are refused
with 422 instead of silently becoming a lookup miss, and alternate spellings are
normalized to the canonical form.
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
from api import authz, ids  # noqa: E402

client = TestClient(main.app)

LEGACY_SENTINEL = "00000000-0000-0000-0000-000000000001"


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


# ---------------------------------------------------------------------------
# Unit contract
# ---------------------------------------------------------------------------
def test_new_id_is_canonical_uuid4():
    for _ in range(50):
        value = ids.new_id()
        assert ids.is_canonical(value)
        assert uuid.UUID(value).version == 4


def test_canonical_normalizes_alternate_spellings():
    canonical = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    parsed = uuid.UUID(canonical)
    assert parsed.version == 4  # guard: the fixture really is a v4 UUID
    for spelling in (
        canonical,
        canonical.upper(),
        "{" + canonical + "}",
        "urn:uuid:" + canonical,
        canonical.replace("-", ""),
    ):
        assert ids.canonical(spelling) == canonical


def test_canonical_rejects_non_v4_and_junk():
    # The legacy seed sentinel is a syntactically valid UUID but not a v4.
    assert ids.canonical(LEGACY_SENTINEL) is None
    assert ids.canonical(str(uuid.uuid1())) is None  # version 1
    assert ids.canonical(str(uuid.uuid5(uuid.NAMESPACE_DNS, "aura"))) is None
    assert ids.canonical("not-a-uuid") is None
    assert ids.canonical("") is None
    assert ids.canonical(None) is None
    assert ids.canonical(123) is None
    # A valid UUID embedded in noise is still rejected (no partial match).
    assert ids.canonical("x" + ids.new_id()) is None


def test_is_canonical_is_strict():
    canonical = ids.new_id()
    assert ids.is_canonical(canonical)
    assert not ids.is_canonical(canonical.upper())
    assert not ids.is_canonical("{" + canonical + "}")
    assert not ids.is_canonical(canonical.replace("-", ""))


# ---------------------------------------------------------------------------
# API boundary
# ---------------------------------------------------------------------------
def test_malformed_path_ids_are_rejected():
    c, headers = _admin()
    for bad in ("not-a-uuid", LEGACY_SENTINEL, "12345"):
        assert c.get(f"/api/v1/folders/{bad}", headers=headers).status_code == 422
        assert c.get(f"/api/v1/objects/{bad}", headers=headers).status_code == 422
        assert c.post(
            f"/api/v1/admin/identities/{bad}/rotate", headers=headers
        ).status_code == 422


def test_alternate_spelling_is_normalized_to_canonical():
    c, headers = _admin()
    created = c.post("/api/v1/folders", json={"name": "canonical-case"},
                     headers=headers).json()
    fid = created["id"]
    assert ids.is_canonical(fid)
    # The same id in upper case resolves to the canonical row.
    r = c.get(f"/api/v1/folders/{fid.upper()}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == fid


def test_upload_intent_refuses_malformed_folder_id():
    c, headers = _admin()
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": "a.txt", "size_bytes": 1, "folder_id": "not-a-uuid",
    }, headers=headers)
    assert r.status_code == 422


def test_admin_bodies_refuse_malformed_ids():
    c, headers = _admin()
    r = c.post("/api/v1/admin/spaces", json={
        "application_id": "not-a-uuid", "name": "s", "environment": "test",
    }, headers=headers)
    assert r.status_code == 422
    r = c.post("/api/v1/admin/identities", json={
        "space_id": LEGACY_SENTINEL, "name": "svc",
    }, headers=headers)
    assert r.status_code == 422
    r = c.post("/api/v1/folders", json={"name": "child", "parent_id": "nope"},
               headers=headers)
    assert r.status_code == 422


def test_token_with_non_canonical_identity_id_is_unauthorized():
    # A structurally valid token whose id is not a canonical UUID v4 must not
    # authenticate (defence in depth in api/identity.py).
    r = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer aura_{LEGACY_SENTINEL}_{'a' * 64}"},
    )
    assert r.status_code == 401
