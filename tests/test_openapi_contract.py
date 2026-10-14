"""Issue #41: keep docs/openapi.yaml in sync with the implemented API.

Every ``/api/v1`` path and method documented in the OpenAPI contract must exist
in ``api/main.py``, and every implemented ``/api/v1`` route must be documented.
This is an offline guard (no S3, no PostgreSQL) so a route added, renamed or
removed without updating the contract fails the pipeline instead of drifting.
"""
import os
from pathlib import Path

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

import yaml  # noqa: E402

import api.main as main  # noqa: E402

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"


def _implemented_routes() -> dict[str, set[str]]:
    routes: dict[str, set[str]] = {}
    for route in main.app.routes:
        if hasattr(route, "methods") and route.path.startswith("/api/v1"):
            routes.setdefault(route.path, set()).update(m.lower() for m in route.methods)
    return routes


def _documented_routes() -> dict[str, set[str]]:
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    routes: dict[str, set[str]] = {}
    for path, methods in spec.get("paths", {}).items():
        if path.startswith("/api/v1"):
            routes[path] = {m.lower() for m in methods if m != "parameters"}
    return routes


def test_openapi_paths_match_implemented_routes():
    implemented = _implemented_routes()
    documented = _documented_routes()
    missing = sorted(set(implemented) - set(documented))
    extra = sorted(set(documented) - set(implemented))
    assert not missing, f"routes implemented but missing from openapi.yaml: {missing}"
    assert not extra, f"routes documented but not implemented: {extra}"


def test_openapi_methods_match_implemented_routes():
    implemented = _implemented_routes()
    documented = _documented_routes()
    for path in sorted(implemented):
        assert implemented[path] == documented[path], (
            f"{path}: implemented {sorted(implemented[path])} "
            f"!= documented {sorted(documented[path])}"
        )


def test_every_documented_operation_is_described():
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    for path, methods in spec.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in methods.items():
            if method == "parameters":
                continue
            assert operation.get("summary"), f"{method.upper()} {path} has no summary"
            responses = operation.get("responses") or {}
            assert any(str(code).startswith("2") for code in responses), (
                f"{method.upper()} {path} documents no 2xx response"
            )
