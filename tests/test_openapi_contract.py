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


def _operations(spec: dict):
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                yield path, method, operation


def _spec() -> dict:
    import yaml

    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_openapi_document_is_valid_3_1():
    """Full schema validation, not just our own heuristics.

    The hand-maintained YAML is prone to quiet defects: an unquoted comma inside
    a flow mapping (`{ description: A, B }`) silently truncates the description
    and adds a bogus key. That is only caught by a real 3.1 validator, so it
    runs here rather than in review.
    """
    pytest = __import__("pytest")
    validate = pytest.importorskip("openapi_spec_validator").validate

    validate(_spec())


def test_every_operation_carries_a_declared_tag():
    spec = _spec()
    declared = {tag["name"] for tag in spec.get("tags", [])}
    assert declared, "openapi.yaml declares no top-level tags"
    for path, method, operation in _operations(spec):
        tags = operation.get("tags") or []
        assert tags, f"{method.upper()} {path} has no tag"
        unknown = sorted(set(tags) - declared)
        assert not unknown, (
            f"{method.upper()} {path} uses undeclared tag(s) {unknown}; "
            f"declared: {sorted(declared)}"
        )


def test_non_public_operations_document_401():
    """Every authenticated operation must declare its 401.

    The API is default-deny (`api/authz.py`): a caller without a session or a
    valid Bearer token gets 401. Operations that explicitly opt out with
    `security: []` are the only public ones.
    """
    spec = _spec()
    for path, method, operation in _operations(spec):
        if operation.get("security") == []:
            continue
        responses = operation.get("responses") or {}
        assert "401" in {str(code) for code in responses}, (
            f"{method.upper()} {path} is authenticated but documents no 401"
        )


def test_servers_offer_a_same_origin_target():
    """The docs UI must be able to call the API same-origin.

    Swagger "Try it" issues browser requests. The API sends no CORS header, so
    the only target that works from the documentation host is a relative one.
    """
    spec = _spec()
    urls = [server.get("url") for server in spec.get("servers", [])]
    assert urls, "openapi.yaml declares no servers"
    assert any(str(url).startswith("/") for url in urls), (
        f"no same-origin server in {urls}; 'Try it' would be blocked by the browser"
    )


def test_local_references_resolve():
    spec = _spec()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                target = spec
                for part in ref[2:].split("/"):
                    assert part in target, f"unresolved $ref {ref}"
                    target = target[part]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
