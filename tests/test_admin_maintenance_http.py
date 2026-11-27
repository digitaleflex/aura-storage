"""HTTP authorization guards for the five admin Storage maintenance actions."""
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-issue-328-http-audit.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import authz  # noqa: E402
from api.auth import hash_password  # noqa: E402

ROUTES = (
    ("/api/v1/admin/integrity/scrub", {}),
    ("/api/v1/admin/objects/{oid}/reverify", {"oid": "11111111-1111-4111-8111-111111111111"}),
    ("/api/v1/admin/storage-orphans/cleanup", {"json": {"bucket": "aura", "keys": []}}),
    ("/api/v1/admin/reconcile-terminal", {}),
    ("/api/v1/admin/reconcile-reverse", {}),
)


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _login(username: str, password: str):
    client = TestClient(main.app)
    response = client.post("/api/v1/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def _operator():
    username = f"operator-{uuid.uuid4().hex[:8]}"
    main.repo.create_user(
        username,
        hash_password("operator-password-123"),
        role="operator",
        space_id=main.repo.default_scope()[1],
    )
    return _login(username, "operator-password-123")


@pytest.mark.parametrize("path,kwargs", ROUTES, ids=[path for path, _ in ROUTES])
def test_maintenance_actions_require_admin_write_and_csrf(path, kwargs):
    request_path = path.format(**kwargs)
    request_kwargs = {key: value for key, value in kwargs.items() if key != "oid"}
    admin, admin_headers = _login("admin", os.environ["AURA_API_ADMIN_PASSWORD"])
    operator, operator_headers = _operator()

    # Operator has admin:read but deliberately not admin:write.
    refused = operator.post(request_path, headers=operator_headers, **request_kwargs)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "forbidden"

    # An admin session without the matching CSRF token never reaches the handler.
    for headers in ({}, {"X-CSRF-Token": "wrong-token"}):
        refused = admin.post(request_path, headers=headers, **request_kwargs)
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == "csrf validation failed"

    anonymous = TestClient(main.app).post(request_path, **request_kwargs)
    assert anonymous.status_code == 401, anonymous.text
