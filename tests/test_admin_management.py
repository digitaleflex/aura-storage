"""Module M04: operational management of applications, spaces and buckets.

All tests are offline (SQLite catalogue, no S3 endpoint). They exercise the
server side only: HTTP status codes, isolation and the guarantee that no S3
credential is ever part of a bucket payload. The forms in the console are UX; the
authority is always the API (see docs/AUTHORIZATION-MATRIX.md).
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
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-m04-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402
from api.auth import hash_password  # noqa: E402
from api.ids import canonical  # noqa: E402

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


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _create_application(c, headers, name=None):
    name = name or f"app-{_tag()}"
    r = c.post("/api/v1/admin/applications", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"], name


def _create_space(c, headers, application_id, *, name=None, environment="test",
                  default_bucket=None):
    name = name or f"space-{_tag()}"
    body = {"application_id": application_id, "name": name, "environment": environment}
    if default_bucket:
        body["default_bucket"] = default_bucket
    r = c.post("/api/v1/admin/spaces", json=body, headers=headers)
    return r


def _make_app_space(c, headers):
    app_id, _ = _create_application(c, headers)
    r = _create_space(c, headers, app_id)
    assert r.status_code == 200, r.text
    return app_id, r.json()["id"], r.json()["bucket"]


def _make_identity(c, headers, space_id, scopes):
    r = c.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": f"svc-{_tag()}", "scopes": scopes,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _ordinary_user():
    name = f"user-{_tag()}"
    password = "user-password-123"
    main.repo.create_user(name, hash_password(password), role="user",
                          space_id=main.repo.default_scope()[1])
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def test_application_detail_exposes_stable_id_and_update():
    c, headers = _admin()
    aid, name = _create_application(c, headers)

    detail = c.get(f"/api/v1/admin/applications/{aid}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == aid and canonical(aid) == aid
    assert body["name"] == name and body["status"] == "active"
    assert body["space_count"] == 0

    new_name = f"renamed-{_tag()}"
    r = c.patch(f"/api/v1/admin/applications/{aid}", json={"name": new_name},
                headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == new_name
    # The stable id is never derived from the name: it is unchanged.
    assert r.json()["id"] == aid


def test_application_name_is_unique_and_rename_excludes_self():
    c, headers = _admin()
    aid_a, name_a = _create_application(c, headers)
    aid_b, _ = _create_application(c, headers)

    # Renaming B onto A's name is a conflict, not a database error.
    r = c.patch(f"/api/v1/admin/applications/{aid_b}", json={"name": name_a},
                headers=headers)
    assert r.status_code == 409, r.text
    # Renaming A to its own name is accepted (self excluded from the check).
    r = c.patch(f"/api/v1/admin/applications/{aid_a}", json={"name": name_a},
                headers=headers)
    assert r.status_code == 200, r.text
    # A fresh duplicate create is still refused.
    assert c.post("/api/v1/admin/applications", json={"name": name_a},
                  headers=headers).status_code == 409


def test_application_validation_errors():
    c, headers = _admin()
    aid, _ = _create_application(c, headers)

    # Nothing to update, an explicit null, an unknown field and a bad status.
    assert c.patch(f"/api/v1/admin/applications/{aid}", json={},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/applications/{aid}", json={"name": None},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/applications/{aid}", json={"status": None},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/applications/{aid}", json={"status": "frozen"},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/applications/{aid}", json={"nope": 1},
                   headers=headers).status_code == 422
    # A whitespace-only name cannot be created.
    assert c.post("/api/v1/admin/applications", json={"name": "   "},
                  headers=headers).status_code == 422
    # Unknown id -> 404; a non-canonical id -> 422 (never a silent 404).
    assert c.get(f"/api/v1/admin/applications/{main.repo.new_id()}",
                 headers=headers).status_code == 404
    assert c.get("/api/v1/admin/applications/not-a-uuid",
                 headers=headers).status_code == 422


def test_deactivated_application_refuses_new_spaces_then_reactivates():
    c, headers = _admin()
    aid, _ = _create_application(c, headers)

    r = c.patch(f"/api/v1/admin/applications/{aid}", json={"status": "disabled"},
                headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    # A space may only be attached to an allowed (active) application.
    assert _create_space(c, headers, aid).status_code == 409

    assert c.patch(f"/api/v1/admin/applications/{aid}", json={"status": "active"},
                   headers=headers).status_code == 200
    assert _create_space(c, headers, aid).status_code == 200


def test_space_creation_requires_an_existing_application():
    c, headers = _admin()
    r = _create_space(c, headers, main.repo.new_id())
    assert r.status_code == 404, r.text
    # A malformed application id is a 422 at the boundary.
    r = c.post("/api/v1/admin/spaces", json={
        "application_id": "not-a-uuid", "name": "x", "environment": "test",
    }, headers=headers)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------
def test_space_duplicate_is_a_conflict_not_a_server_error():
    c, headers = _admin()
    aid, _ = _create_application(c, headers)
    name = f"space-{_tag()}"
    assert _create_space(c, headers, aid, name=name, environment="test").status_code == 200
    # Same (application_id, name, environment) -> 409.
    assert _create_space(c, headers, aid, name=name, environment="test").status_code == 409
    # A different environment is a distinct space.
    assert _create_space(c, headers, aid, name=name, environment="staging").status_code == 200


def test_space_detail_lists_buckets_and_counts():
    c, headers = _admin()
    aid, _, bucket = _make_app_space(c, headers)
    sid = None
    for s in c.get("/api/v1/admin/spaces", headers=headers).json()["items"]:
        if s["application_id"] == aid:
            sid = s["id"]
    assert sid

    detail = c.get(f"/api/v1/admin/spaces/{sid}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == sid and canonical(sid) == sid
    assert body["application_id"] == aid and body["status"] == "active"
    assert body["application_name"]
    assert [b["name"] for b in body["buckets"]] == [bucket]
    assert body["buckets"][0]["is_default"] is True
    assert body["counts"] == {"buckets": 1, "identities": 0, "objects": 0}


def test_space_update_and_immutable_application():
    c, headers = _admin()
    aid, sid, _ = _make_app_space(c, headers)

    new_name = f"renamed-{_tag()}"
    r = c.patch(f"/api/v1/admin/spaces/{sid}",
                json={"name": new_name, "environment": "staging"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == new_name and r.json()["environment"] == "staging"
    assert r.json()["id"] == sid

    # `application_id` is not an editable field: reassignment is refused.
    other_app, _ = _create_application(c, headers)
    r = c.patch(f"/api/v1/admin/spaces/{sid}",
                json={"application_id": other_app}, headers=headers)
    assert r.status_code == 422, r.text
    assert c.get(f"/api/v1/admin/spaces/{sid}", headers=headers).json()[
        "application_id"] == aid

    # A rename that collides with a sibling space in the same environment is 409.
    sibling = _create_space(c, headers, aid, name=f"sib-{_tag()}", environment="staging")
    assert sibling.status_code == 200, sibling.text
    r = c.patch(f"/api/v1/admin/spaces/{sid}",
                json={"name": sibling.json()["name"]}, headers=headers)
    assert r.status_code == 409, r.text


def test_space_validation_errors():
    c, headers = _admin()
    _, sid, _ = _make_app_space(c, headers)
    assert c.patch(f"/api/v1/admin/spaces/{sid}", json={},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/spaces/{sid}", json={"name": None},
                   headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/spaces/{sid}", json={"status": "paused"},
                   headers=headers).status_code == 422
    assert c.get(f"/api/v1/admin/spaces/{main.repo.new_id()}",
                 headers=headers).status_code == 404
    assert c.get("/api/v1/admin/spaces/not-a-uuid", headers=headers).status_code == 422
    assert c.patch(f"/api/v1/admin/spaces/{main.repo.new_id()}",
                   json={"status": "disabled"}, headers=headers).status_code == 404


def test_disabled_space_blocks_new_uploads_and_identities_but_stays_readable():
    c, headers = _admin()
    _, sid, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, sid, ["objects:read", "objects:write"])["token"]
    svc = {"Authorization": f"Bearer {token}"}

    # While active, an upload intent succeeds.
    ok = c.post("/api/v1/objects/upload-intents",
                json={"display_name": "before.txt", "size_bytes": 1}, headers=svc)
    assert ok.status_code == 200, ok.text

    assert c.patch(f"/api/v1/admin/spaces/{sid}", json={"status": "disabled"},
                   headers=headers).status_code == 200

    # A disabled space refuses new writes and new identities...
    blocked = c.post("/api/v1/objects/upload-intents",
                     json={"display_name": "after.txt", "size_bytes": 1}, headers=svc)
    assert blocked.status_code == 403, blocked.text
    assert c.post("/api/v1/admin/identities", json={
        "space_id": sid, "name": "no", "scopes": ["objects:read"],
    }, headers=headers).status_code == 409
    # ...but existing data stays readable.
    assert c.get("/api/v1/objects", headers=svc).status_code == 200


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------
def test_bucket_listing_shows_attachment_and_no_secrets():
    c, headers = _admin()
    aid, sid, bucket = _make_app_space(c, headers)

    r = c.get("/api/v1/admin/buckets", headers=headers)
    assert r.status_code == 200, r.text
    item = next(b for b in r.json()["items"] if b["space_id"] == sid)
    assert item["name"] == bucket and item["is_default"] is True
    assert item["application_id"] == aid and item["application_name"]
    assert item["space_name"] and item["environment"] == "test"
    assert canonical(item["id"])

    # Never any S3 credential: only the name and its attachment are exposed.
    for forbidden in ("secret", "access_key", "credential", "password", "token"):
        assert forbidden not in r.text.lower()


def test_register_bucket_validations_and_default_toggle():
    c, headers = _admin()
    _, sid, default_bucket = _make_app_space(c, headers)

    # Invalid S3 name, duplicate name and unknown space are refused.
    assert c.post(f"/api/v1/admin/spaces/{sid}/buckets",
                  json={"name": "Bad_Bucket"}, headers=headers).status_code == 422
    assert c.post(f"/api/v1/admin/spaces/{sid}/buckets",
                  json={"name": default_bucket}, headers=headers).status_code == 409
    assert c.post(f"/api/v1/admin/spaces/{main.repo.new_id()}/buckets",
                  json={"name": f"aura-{_tag()}"}, headers=headers).status_code == 404

    extra = f"aura-extra-{_tag()}"
    r = c.post(f"/api/v1/admin/spaces/{sid}/buckets", json={"name": extra},
               headers=headers)
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    assert r.json()["is_default"] is False

    # Making it the default clears the flag on the previous default: exactly one.
    r = c.patch(f"/api/v1/admin/buckets/{bid}", json={"is_default": True},
                headers=headers)
    assert r.status_code == 200 and r.json()["is_default"] is True
    buckets = c.get(f"/api/v1/admin/spaces/{sid}", headers=headers).json()["buckets"]
    defaults = [b["id"] for b in buckets if b["is_default"]]
    assert defaults == [bid]

    # Clearing it leaves the space without an explicit default bucket. There is
    # no "oldest bucket" fallback: an upload intent for that space is refused
    # with 409 until a default is set again. This is reversible.
    assert c.patch(f"/api/v1/admin/buckets/{bid}", json={"is_default": False},
                   headers=headers).json()["is_default"] is False
    assert c.patch(f"/api/v1/admin/buckets/{main.repo.new_id()}",
                   json={"is_default": True}, headers=headers).status_code == 404
    assert c.patch(f"/api/v1/admin/buckets/{bid}", json={},
                   headers=headers).status_code == 422


# ---------------------------------------------------------------------------
# Server-side authorization (the console alone is never enough)
# ---------------------------------------------------------------------------
def test_non_admin_principals_are_forbidden_on_every_management_route():
    c, headers = _admin()
    aid, sid, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, sid, ["objects:read", "objects:write"])["token"]
    svc = {"Authorization": f"Bearer {token}"}
    user, uheaders = _ordinary_user()

    for caller, hdrs in ((user, uheaders), (c, svc)):
        assert caller.get(f"/api/v1/admin/applications/{aid}", headers=hdrs).status_code == 403
        assert caller.patch(f"/api/v1/admin/applications/{aid}", json={"name": "x"},
                            headers=hdrs).status_code == 403
        assert caller.get(f"/api/v1/admin/spaces/{sid}", headers=hdrs).status_code == 403
        assert caller.patch(f"/api/v1/admin/spaces/{sid}", json={"status": "disabled"},
                            headers=hdrs).status_code == 403
        assert caller.get("/api/v1/admin/buckets", headers=hdrs).status_code == 403
        assert caller.post(f"/api/v1/admin/spaces/{sid}/buckets",
                           json={"name": f"aura-{_tag()}"}, headers=hdrs).status_code == 403
        assert caller.patch(f"/api/v1/admin/buckets/{main.repo.new_id()}",
                            json={"is_default": True}, headers=hdrs).status_code == 403

    # Anonymous callers never reach the handlers (401, no existence leak).
    assert client.get(f"/api/v1/admin/applications/{aid}").status_code == 401
    assert client.get("/api/v1/admin/buckets").status_code == 401


def test_service_identity_never_reaches_another_application():
    c, headers = _admin()
    app_a, space_a, _ = _make_app_space(c, headers)
    app_b, space_b, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space_a, ["objects:read"])["token"]
    svc = {"Authorization": f"Bearer {token}"}

    # A machine identity is data-plane only: it cannot read the registry of its
    # own application, let alone a foreign one, nor mint spaces in either.
    assert c.get("/api/v1/admin/spaces", headers=svc).status_code == 403
    assert c.get(f"/api/v1/admin/spaces/{space_b}", headers=svc).status_code == 403
    assert c.post("/api/v1/admin/spaces", json={
        "application_id": app_b, "name": f"forged-{_tag()}", "environment": "prod",
    }, headers=svc).status_code == 403
    # Its own legitimate object capability is unaffected.
    assert c.get("/api/v1/objects", headers=svc).status_code == 200
