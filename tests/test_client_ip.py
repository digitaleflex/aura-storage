"""#35/#38: client-IP resolution behind the trusted proxy chain.

The API never listens publicly: a browser is seen after Traefik -> nginx -> api,
so every socket peer is a proxy and the real client only exists in
``X-Forwarded-For``. These tests pin the rules that key the login and M2M rate
limiters, so that (a) a real client is rate-limited per client and (b) a client
cannot spoof its address to evade the limiter.
"""
import os

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")

from starlette.requests import Request  # noqa: E402

from api import netinfo  # noqa: E402
from api.config import settings  # noqa: E402
from api.netinfo import TrustedProxies, resolve_client_ip  # noqa: E402

TRUSTED = TrustedProxies(["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])

NGINX = "172.18.0.4"      # immediate peer of the API
TRAEFIK = "172.18.0.3"    # peer of nginx
CLIENT = "203.0.113.9"    # a public client


def make_request(peer, forwarded_for=None):
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request({"type": "http", "headers": headers, "client": (peer, 50000)})


def test_direct_untrusted_peer_wins_and_headers_are_ignored():
    # If the API were ever reached without a proxy, a forged header must not win.
    assert resolve_client_ip(CLIENT, "198.51.100.1", TRUSTED) == CLIENT
    assert netinfo.client_ip(make_request(CLIENT, "198.51.100.1")) == CLIENT


def test_single_proxy_appends_client():
    assert resolve_client_ip(NGINX, f"{CLIENT}, {NGINX}", TRUSTED) == CLIENT


def test_two_hop_chain_resolves_original_client():
    # Traefik -> nginx: nginx appends its own peer (Traefik) to the client value.
    assert resolve_client_ip(NGINX, f"{CLIENT}, {TRAEFIK}", TRUSTED) == CLIENT
    assert netinfo.client_ip(make_request(NGINX, f"{CLIENT}, {TRAEFIK}")) == CLIENT


def test_client_forged_leftmost_entry_cannot_spoof():
    # A client may send its own X-Forwarded-For; proxies append the real one.
    forged = f"6.6.6.6, {CLIENT}, {TRAEFIK}"
    assert resolve_client_ip(NGINX, forged, TRUSTED) == CLIENT


def test_all_trusted_chain_falls_back_to_peer():
    # Internal-to-internal traffic (e.g. health probe) has no external client.
    assert resolve_client_ip(NGINX, f"{TRAEFIK}, {NGINX}", TRUSTED) == NGINX


def test_missing_or_empty_header_falls_back_to_peer():
    assert resolve_client_ip(NGINX, None, TRUSTED) == NGINX
    assert resolve_client_ip(NGINX, "   ,  ", TRUSTED) == NGINX
    assert resolve_client_ip(None, None, TRUSTED) == "unknown"


def test_ipv6_client_and_loopback_proxy():
    trusted = TrustedProxies(["::1/128", "172.16.0.0/12"])
    assert resolve_client_ip("::1", "2001:db8::10, ::1", trusted) == "2001:db8::10"


def test_version_mismatch_does_not_match():
    # An IPv6 candidate must not be treated as inside an IPv4 trusted range.
    trusted = TrustedProxies(["10.0.0.0/8"])
    assert resolve_client_ip("10.0.0.5", "::1, 10.0.0.5", trusted) == "::1"


def test_default_settings_trust_private_and_loopback():
    assert "172.16.0.0/12" in settings.trusted_proxies
    assert "127.0.0.0/8" in settings.trusted_proxies


def test_client_ip_reads_forwarded_header_from_request():
    request = make_request("testclient", f"{CLIENT}, 10.1.2.3")
    assert netinfo.client_ip(request, trusted=["testclient", "10.0.0.0/8"]) == CLIENT


def test_login_limiter_is_per_client_not_global(monkeypatch):
    """Regression for the review finding: behind the proxy, the login limiter
    must key on the real client, otherwise a few attempts lock out everybody."""
    from fastapi.testclient import TestClient

    import api.main as main

    monkeypatch.setattr(settings, "trusted_proxies", ("testclient",))
    main.reset_login_attempts()
    client = TestClient(main.app)

    def attempt(address):
        return client.post(
            "/api/v1/login",
            json={"username": "admin", "password": "definitely-wrong"},
            headers={"X-Forwarded-For": address},
        ).status_code

    for _ in range(settings.login_rate_limit):
        assert attempt("198.51.100.7") == 401
    assert attempt("198.51.100.7") == 429  # first client is now limited
    assert attempt("198.51.100.8") == 401  # a different client is unaffected
