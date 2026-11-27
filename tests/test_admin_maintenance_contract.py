"""Issue #328: the console's maintenance actions stay aligned with the contract."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "docs" / "openapi.yaml"
MATRIX = ROOT / "docs" / "AUTHORIZATION-MATRIX.md"

MAINTENANCE_PATHS = (
    "/api/v1/admin/integrity/scrub",
    "/api/v1/admin/objects/{oid}/reverify",
    "/api/v1/admin/storage-orphans/cleanup",
    "/api/v1/admin/reconcile-terminal",
    "/api/v1/admin/reconcile-reverse",
)

ORPHAN_REPORT_PATHS = (
    "/api/v1/admin/integrity",
    "/api/v1/admin/storage-orphans",
)


def _documented_path_names():
    root = yaml.compose(OPENAPI.read_text(encoding="utf-8"))
    paths = next(value for key, value in root.value if key.value == "paths")
    return [key.value for key, _ in paths.value]


@pytest.mark.parametrize("path", MAINTENANCE_PATHS)
def test_maintenance_action_is_documented_once_with_admin_write(path):
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = spec["paths"][path]["post"]
    assert "admin:write" in operation["summary"]
    assert {"401", "403"} <= {str(code) for code in operation["responses"]}

    # safe_load keeps only the last duplicate; inspect the YAML nodes as well so
    # an older, weaker definition cannot silently shadow the full contract.
    assert _documented_path_names().count(path) == 1

    assert f"| POST | `{path}` | `admin:write` |" in MATRIX.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ORPHAN_REPORT_PATHS)
def test_orphan_and_integrity_reports_are_documented_once_with_full_read_contract(path):
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = spec["paths"][path]["get"]
    assert "admin:read" in operation["summary"]
    assert operation["responses"]["200"].get("content"), "full response schema was shadowed"
    assert _documented_path_names().count(path) == 1
    assert f"| GET | `{path}` | `admin:read` |" in MATRIX.read_text(encoding="utf-8")


def test_reverify_documents_its_actionable_checksum_mismatch_body():
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = spec["paths"]["/api/v1/admin/objects/{oid}/reverify"]["post"]
    schema = operation["responses"]["409"]["content"]["application/json"]["schema"]
    assert schema["properties"]["status"]["enum"] == ["suspect"]
    assert schema["properties"]["reason"]["enum"] == ["checksum_mismatch"]
    assert {"size_bytes", "checksum_sha256"} <= set(schema["required"])


def test_destructive_maintenance_parameters_match_the_backend():
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    reverse = spec["paths"]["/api/v1/admin/reconcile-reverse"]["post"]
    dry_run = next(p for p in reverse["parameters"] if p["name"] == "dry_run")
    assert dry_run["schema"]["default"] is True

    cleanup = spec["paths"]["/api/v1/admin/storage-orphans/cleanup"]["post"]
    body = cleanup["requestBody"]["content"]["application/json"]["schema"]
    assert body["properties"]["keys"]["maxItems"] == 100
    assert body["properties"]["uploads"]["maxItems"] == 100
