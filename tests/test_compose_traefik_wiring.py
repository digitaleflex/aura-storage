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
    assert share.get("service") == "aura-share"
    assert int(share.get("priority", "0")) > 0
