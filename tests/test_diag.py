"""Diagnostic réseau : routes de mesure du chemin réel navigateur -> Aura.

Ces routes ne stockent rien et ne doivent exposer aucun corps. On vérifie
l'authentification obligatoire, les plafonds, les en-têtes anti-cache et
l'incompressibilité du flux (une mesure faussée par un proxy compressant
serait pire qu'aucune mesure).
"""
import os

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402

client = TestClient(main.app)


def _authed():
    c = TestClient(main.app)
    r = c.post(
        "/api/v1/login",
        json={"username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"]},
    )
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def test_diag_routes_require_authentication():
    assert client.get("/api/v1/diag/ping").status_code in (401, 403)
    assert client.get("/api/v1/diag/download?bytes=1024").status_code in (401, 403)
    assert client.post("/api/v1/diag/upload", content=b"x").status_code in (401, 403)


def test_ping_is_tiny_and_uncached():
    c, _ = _authed()
    r = c.get("/api/v1/diag/ping")
    assert r.status_code == 200
    assert isinstance(r.json()["ts"], int)
    assert r.headers["Cache-Control"] == "no-store"
    assert len(r.content) < 64


def test_download_defaults_to_ten_megabytes_and_is_uncached():
    c, _ = _authed()
    r = c.get("/api/v1/diag/download")
    assert r.status_code == 200
    assert len(r.content) == main.DIAG_DEFAULT_DOWNLOAD
    assert r.headers["Content-Length"] == str(main.DIAG_DEFAULT_DOWNLOAD)
    assert r.headers["Content-Encoding"] == "identity"
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["Content-Type"].startswith("application/octet-stream")


def test_download_clamps_the_requested_size():
    c, _ = _authed()
    capped = c.get("/api/v1/diag/download?bytes=999999999")
    assert capped.status_code == 200
    assert len(capped.content) == main.DIAG_MAX_BYTES
    # A zero (or negative) request still returns one byte: a 0-byte body cannot
    # be timed meaningfully.
    tiny = c.get("/api/v1/diag/download?bytes=0")
    assert len(tiny.content) == 1


def test_download_payload_is_incompressible():
    c, _ = _authed()
    first = c.get("/api/v1/diag/download?bytes=65536").content
    second = c.get("/api/v1/diag/download?bytes=65536").content
    assert first != second
    assert len(set(first)) > 200


def test_upload_reports_the_measured_rate():
    c, headers = _authed()
    payload = b"\0" * (1024 * 1024)
    r = c.post("/api/v1/diag/upload", content=payload, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bytes"] == len(payload)
    assert body["duration_ms"] >= 0
    assert body["bytes_per_second"] > 0
    assert r.headers["Cache-Control"] == "no-store"


def test_upload_above_the_cap_is_refused():
    c, headers = _authed()
    too_big = b"\0" * (main.DIAG_MAX_BYTES + 1)
    r = c.post("/api/v1/diag/upload", content=too_big, headers=headers)
    assert r.status_code == 413
