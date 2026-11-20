"""Google OIDC Authorization Code + PKCE adapter.

No token, code or state is logged. The adapter has no dependency on AURA's
settings or tables: the audiobook service owns its listeners and sessions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
SCOPES = "openid email profile"
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
TIMEOUT_S = 10


class OAuthError(Exception):
    """A failed or invalid exchange with Google; never echoed to the client."""


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _post_form(url: str, fields: dict) -> dict:
    body = urlencode(fields).encode("ascii")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, ValueError, TimeoutError) as exc:
        raise OAuthError("token endpoint unavailable") from exc
    if not isinstance(payload, dict):
        raise OAuthError("invalid token response")
    return payload


def exchange_code(settings: Settings, code: str, verifier: str) -> dict:
    payload = _post_form(
        TOKEN_URL,
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "code_challenge_method": "S256",
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_redirect_uri,
        },
    )
    if payload.get("error") or not payload.get("id_token"):
        raise OAuthError("code exchange refused")
    return payload


def verify_id_token(settings: Settings, id_token: str) -> dict:
    query = urlencode({"id_token": id_token})
    request = Request(
        f"{TOKENINFO_URL}?{query}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            claims = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, ValueError, TimeoutError) as exc:
        raise OAuthError("tokeninfo unavailable") from exc
    if not isinstance(claims, dict) or claims.get("error"):
        raise OAuthError("invalid id token")
    if claims.get("aud") != settings.google_client_id:
        raise OAuthError("wrong audience")
    if claims.get("iss") not in ISSUERS:
        raise OAuthError("wrong issuer")
    try:
        expired = float(claims.get("exp", 0)) <= time.time()
    except (TypeError, ValueError) as exc:
        raise OAuthError("invalid expiry") from exc
    if expired:
        raise OAuthError("expired id token")
    verified = claims.get("email_verified")
    verified = verified is True or (
        isinstance(verified, str) and verified.lower() == "true"
    )
    if not claims.get("sub") or not claims.get("email") or not verified:
        raise OAuthError("identity not verified")
    return claims
