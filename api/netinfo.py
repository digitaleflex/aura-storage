"""Client-address resolution behind the trusted proxy chain (#35/#38).

The Management API is never exposed directly: it listens only on the internal
Docker network and is reached through the app nginx, itself fronted by Traefik.
The socket peer of every request is therefore a *proxy*, and the real client
address only exists in ``X-Forwarded-For``.

Trusting that header blindly would let any client spoof its own address and
dodge the login / machine rate limiters. Resolution rules:

1. If the immediate socket peer is **not** a trusted proxy, its address is used
   and any ``X-Forwarded-For`` value is ignored (a header a client sent itself
   can never be trusted).
2. Otherwise the header is read and we return the **right-most** address that is
   not itself a trusted proxy — i.e. the first hop appended by infrastructure we
   control. Anything a client forged on the left is discarded.

Trusted proxies default to the loopback and RFC1918 ranges Docker uses; override
with ``AURA_TRUSTED_PROXIES`` (comma-separated IPs or CIDRs).
"""
from __future__ import annotations

import ipaddress
from typing import Iterable

from fastapi import Request

from .config import settings

DEFAULT_TRUSTED_PROXIES: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

UNKNOWN_CLIENT = "unknown"


class TrustedProxies:
    """Compiled membership test for a set of IPs / CIDRs / literals."""

    def __init__(self, values: Iterable[str]):
        self._networks: list[ipaddress._BaseNetwork] = []
        self._literals: set[object] = set()
        for raw in values:
            value = raw.strip()
            if not value:
                continue
            try:
                if "/" in value:
                    self._networks.append(ipaddress.ip_network(value, strict=False))
                else:
                    self._literals.add(ipaddress.ip_address(value))
                continue
            except ValueError:
                pass
            # Not an IP: keep the raw token (e.g. the TestClient's "testclient").
            self._literals.add(value)

    def __contains__(self, host: str) -> bool:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return host in self._literals
        if ip in self._literals:
            return True
        return any(ip in network for network in self._networks)


_CACHE: dict[tuple[str, ...], TrustedProxies] = {}


def compile_trusted_proxies(values: Iterable[str]) -> TrustedProxies:
    key = tuple(values)
    compiled = _CACHE.get(key)
    if compiled is None:
        compiled = TrustedProxies(key)
        _CACHE[key] = compiled
    return compiled


def resolve_client_ip(
    peer: str | None, forwarded_for: str | None, trusted: TrustedProxies
) -> str:
    """Return the address the rate limiters should key on."""
    peer = peer or UNKNOWN_CLIENT
    if peer not in trusted:
        return peer
    for candidate in reversed(
        [part.strip() for part in (forwarded_for or "").split(",") if part.strip()]
    ):
        if candidate not in trusted:
            return candidate
    return peer


def client_ip(request: Request, trusted: Iterable[str] | None = None) -> str:
    """Resolve the client address of ``request`` for rate limiting."""
    values = settings.trusted_proxies if trusted is None else tuple(trusted)
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer, request.headers.get("x-forwarded-for"), compile_trusted_proxies(values)
    )
