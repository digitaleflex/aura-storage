"""Static guards on docker-compose.yml Traefik wiring.

A router that omits `service=` is auto-linked only when its container exposes
exactly one Traefik service. The API container exposes two (`aura-share` and
`aura-swagger-api`), so Traefik refuses to link either and drops the router.
The failure is silent at the edge: `/s/<token>` falls through to the SPA
router and answers with index.html instead of the API's 302/404.

These assertions are cheap and catch the regression without a live host.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"

ROUTER = "traefik.http.routers."
SERVICE = "traefik.http.services."


@pytest.fixture(scope="module")
def services() -> dict[str, list[str]]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for name, service in data.get("services", {}).items():
        out[name] = [str(label) for label in service.get("labels", []) or []]
    return out


def _index(labels: list[str], prefix: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for label in labels:
        if not label.startswith(prefix):
            continue
        key, _, value = label.partition("=")
        rest = key[len(prefix):]
        name, _, attr = rest.partition(".")
        if attr:
            out.setdefault(name, {})[attr] = value
    return out


def test_routers_on_multi_service_containers_bind_explicitly(
    services: dict[str, list[str]],
) -> None:
    problems: list[str] = []
    checked = 0
    for name, labels in services.items():
        routers = _index(labels, ROUTER)
        declared = _index(labels, SERVICE)
        for router, cfg in routers.items():
            checked += 1
            if "service" in cfg:
                target = cfg["service"]
                # `api@internal` and other provider-qualified services are not
                # declared by docker labels, so they are not ours to check.
                if "@" not in target and target not in declared:
                    problems.append(
                        f"{name}:{router} -> undeclared service {target!r}"
                    )
                continue
            if len(declared) > 1:
                problems.append(
                    f"{name}:{router} has no service= but the container exposes "
                    f"{len(declared)} services ({sorted(declared)})"
                )
    assert checked > 0, "no Traefik routers found; the guard would be vacuous"
    assert problems == [], "\n".join(problems)


def test_share_router_is_reachable_past_the_spa(
    services: dict[str, list[str]],
) -> None:
    labels = next(
        (lbl for lbl in services.values() if any(f"{ROUTER}aura-share." in x for x in lbl)),
        None,
    )
    assert labels is not None, "the public share router disappeared"
    share = _index(labels, ROUTER)["aura-share"]
    assert "PathPrefix(`/s/`)" in share.get("rule", "")
    assert "PathPrefix(`/f/`)" in share.get("rule", "")
    assert "PathPrefix(`/d/`)" in share.get("rule", "")
    assert "PathPrefix(`/a/`)" in share.get("rule", "")
    assert share.get("service") == "aura-share"
    assert int(share.get("priority", "0")) > 0


def test_public_router_exposes_only_portal_paths(
    services: dict[str, list[str]],
) -> None:
    labels = next(
        (lbl for lbl in services.values() if any(f"{ROUTER}aura-public." in x for x in lbl)),
        None,
    )
    assert labels is not None, "the public portal router disappeared"
    public = _index(labels, ROUTER)["aura-public"]
    rule = public.get("rule", "")
    assert "PUBLIC_DOMAIN" in rule
    assert "Path(`/`)" in rule
    assert "PathPrefix(`/api/public/`)" in rule
    # The HTML player uses relative /m/<slug> URLs: the media redirect must be
    # reachable on this host or every <audio> element returns 404 at the edge.
    assert "PathPrefix(`/m/`)" in rule
    # The premium offline button fetches /d/<slug> on this host.
    assert "PathPrefix(`/d/`)" in rule
    assert "PathPrefix(`/a/`)" in rule
    assert "PathPrefix(`/hls/`)" in rule
    assert "PathPrefix(`/covers/`)" in rule
    assert "PathPrefix(`/api/v1/`)" not in rule
    assert public.get("service") == "aura-public"


def test_nginx_fallback_forwards_service_media_grants() -> None:
    nginx = COMPOSE.with_name("app") / "nginx.conf"
    source = nginx.read_text(encoding="utf-8")
    block = source.split("location /a/ {", 1)[1].split("}", 1)[0]
    assert "access_log off;" in block
    assert "error_log /dev/null;" in block
    assert "proxy_pass http://api:8000;" in block


def test_bearer_grant_paths_are_not_written_to_access_logs() -> None:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    command = data["services"]["traefik"]["command"]
    assert "--accesslog.fields.queryparameters.defaultmode=drop" in command
    assert "--accesslog.fields.names.RequestPath=drop" in command
    dockerfile = COMPOSE.with_name("api") / "Dockerfile"
    assert '"--no-access-log"' in dockerfile.read_text(encoding="utf-8")


def test_public_access_grant_default_is_bounded() -> None:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    environment = data["services"]["api"]["environment"]
    assert environment["AURA_PUBLIC_ACCESS_GRANT_TTL"] == (
        "${AURA_PUBLIC_ACCESS_GRANT_TTL:-900}"
    )


def test_api_has_dedicated_oauth_egress_network() -> None:
    """The OAuth token exchange needs outbound HTTPS, but not the public edge."""
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api = data["services"]["api"]
    assert "oauth" in api.get("networks", [])
    assert "edge" not in api.get("networks", [])
    oauth_network = data["networks"]["oauth"]
    # An internal network has no default route: Google would be unreachable.
    assert oauth_network.get("internal") is not True


def test_tested_traefik_version_is_pinned() -> None:
    """The reviewed HTTP/3 build must win over a stale local .env value."""
    override = COMPOSE.with_name("docker-compose.override.yml")
    data = yaml.safe_load(override.read_text(encoding="utf-8"))
    assert data["services"]["traefik"]["image"] == "traefik:v3.7.20"


def test_idempotent_get_routes_have_retry_and_no_mutation_replay(
    services: dict[str, list[str]],
) -> None:
    middleware_labels = next(
        (
            lbl
            for lbl in services.values()
            if "traefik.http.middlewares.api-get-retry.retry.attempts=2" in lbl
        ),
        None,
    )
    assert middleware_labels is not None, "shared GET retry middleware disappeared"

    routers: dict[str, dict[str, str]] = {}
    for lbl in services.values():
        routers.update(_index(lbl, ROUTER))
    for name, base, priority in (
        ("aura-share-get", "aura-share", 205),
        ("aura-public-get", "aura-public", 215),
        ("aura-s3-get", "aura-s3", 10),
    ):
        router = routers[name]
        assert "Method(`GET`)" in router.get("rule", "")
        assert "Method(`HEAD`)" in router.get("rule", "")
        assert int(router.get("priority", "0")) == priority
        assert "api-get-retry" in router.get("middlewares", "")
        assert router.get("service") == base

    for mutation in ("aura-share", "aura-public", "aura-s3"):
        middlewares = routers[mutation].get("middlewares", "")
        assert "api-get-retry" not in middlewares, mutation
