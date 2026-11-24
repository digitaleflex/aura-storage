"""Static guards for the S1 and D1 audit fixes.

S1: the API must run as its dedicated least-privilege SeaweedFS identity, never
falling back to the bootstrap `Admin` key.

D1: the frontend is published as an immutable release outside the worktree, so a
running release cannot change when `web/dist` is rebuilt or the checkout moves.

These assertions are offline and cheap; they catch a silent regression without a
live host.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
GENERATE_CONFIG = ROOT / "scripts" / "generate-config.sh"
DEPLOY = ROOT / "scripts" / "deploy.sh"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_api_uses_dedicated_s3_identity_without_fallback() -> None:
    environment = _compose()["services"]["api"]["environment"]
    access = str(environment["AURA_S3_ACCESS_KEY"])
    secret = str(environment["AURA_S3_SECRET_KEY"])

    assert "${S3_API_ACCESS_KEY:?" in access
    assert "${S3_API_SECRET_KEY:?" in secret
    # No silent fallback to the bootstrap Admin credentials.
    assert "${S3_ACCESS_KEY" not in access
    assert "${S3_SECRET_KEY" not in secret


def test_frontend_mounts_use_the_release_directory_parameter() -> None:
    services = _compose()["services"]
    volumes = [
        str(volume)
        for service in ("app", "s3-landing")
        for volume in services[service]["volumes"]
    ]
    web_volumes = [
        volume
        for volume in volumes
        if "/usr/share/nginx/html" in volume or "/opt/aura-landing-fonts" in volume
    ]

    assert len(web_volumes) == 2, f"expected two frontend mounts, got {web_volumes}"
    for volume in web_volumes:
        source = volume.split(":", 1)[0]
        assert source.startswith("${AURA_WEB_DIST_DIR"), volume

    raw = COMPOSE.read_text(encoding="utf-8")
    assert "\n      - ./web/dist:" not in raw
    assert "\n      - ./web/dist/fonts:" not in raw


def test_deploy_publishes_an_immutable_frontend_release() -> None:
    script = DEPLOY.read_text(encoding="utf-8")

    assert "AURA_RELEASES_DIR" in script
    assert "AURA_KEEP_RELEASES" in script
    assert 'export AURA_WEB_DIST_DIR' in script
    assert 'cp -a "${ROOT_DIR}/web/dist/." "${RELEASE_DIR}/"' in script


def test_deploy_reconciles_all_services_before_conditional_recreates() -> None:
    """An image bump must not be lost when nginx templates also changed."""
    script = DEPLOY.read_text(encoding="utf-8")
    assert (
        'docker compose up -d --wait --wait-timeout 180 --remove-orphans\n'
        'if [[ -f "${NGINX_HASH_FILE}" ]]'
    ) in script
    assert "${AURA_WEB_DIST_DIR}${ASSET_PATH}" in script


def test_generate_config_requires_dedicated_credentials() -> None:
    script = GENERATE_CONFIG.read_text(encoding="utf-8")

    assert "${S3_API_ACCESS_KEY:?" in script
    assert "${S3_API_SECRET_KEY:?" in script
    # The old fallback blanked the identity then dropped it from the output.
    assert 'credential["accessKey"] = ""' not in script
    assert 'data["identities"] = [' not in script


def test_generate_config_forbids_admin_on_the_api_identity() -> None:
    script = GENERATE_CONFIG.read_text(encoding="utf-8")

    # The template is editable; the generator must refuse to emit an Admin API
    # identity even if someone reintroduces it in s3.json.example.
    assert 'allowed_actions = {"Read", "Write", "List"}' in script
    assert 'if "Admin" in actions:' in script
    assert "aura-api actions must be a subset of Read/Write/List" in script


def test_bootstrap_generates_api_credentials_safely() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")

    assert "ensure_api_credentials()" in script
    # Idempotence guard: valid keys return before any rewrite.
    assert 'if [[ -n "$ak" && -n "$sk"' in script
    # Atomic .env rewrite, never widening permissions.
    assert "tempfile.mkstemp(" in script
    assert "os.replace(tmp_path, env_path)" in script
    assert "min(mode, 0o600)" in script
    assert "os.fsync(" in script


def test_bootstrap_ignores_comments_when_checking_placeholders() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")

    # `.env.example` documents invalid sample domains in comments; those must
    # not make a fully-configured .env fail the placeholder check.
    assert "grep -Ev '^[[:space:]]*#' .env | grep -Eq" in script


def test_deploy_reloads_the_s3_gateway_when_its_config_changes() -> None:
    script = DEPLOY.read_text(encoding="utf-8")

    # SeaweedFS 4.48 reads -s3.config at startup and on SIGHUP only: a new API
    # key is inert until the gateway reloads it.
    assert "S3_CONFIG_HASH_FILE" in script
    assert 'docker compose restart seaweed-filer' in script
    assert '"${CURRENT_S3_CONFIG_HASH}"' in script


def test_deploy_refuses_to_serve_the_worktree() -> None:
    script = DEPLOY.read_text(encoding="utf-8")

    # Both the release directory and the exported mount source are checked.
    assert script.count('"${ROOT_DIR}"|"${ROOT_DIR}"/*)') == 2
    assert "release directory" in script
    assert "resolves inside the worktree" in script
    # Release retention must be deterministic and base-10 safe.
    assert "KEEP_RELEASES=$((10#${AURA_KEEP_RELEASES}))" in script
    assert "sort -r" in script
