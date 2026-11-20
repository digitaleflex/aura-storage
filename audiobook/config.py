"""Environment-driven configuration for the audiobook service.

No secret is hard-coded. The service is intentionally separate from AURA:
it has its own DSN, its own schema and its own session cookies. AURA is reached
only through :class:`audiobook.storage.StoragePort`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ConfigError(RuntimeError):
    """Raised when the process cannot start with the current environment."""


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value


def _int(name: str, default: int) -> int:
    raw = _env(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings.

    Tests construct this directly; production uses :meth:`from_env`.
    """

    dsn: str
    schema: str = "audiobook"
    public_base_url: str = "http://localhost:8080"
    post_login_redirect: str = "/"
    google_client_id: str = ""
    google_client_secret: str = ""
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    oauth_cookie_ttl_seconds: int = 600
    access_decision_ttl_seconds: int = 60
    playback_lease_seconds: int = 120
    heartbeat_timeout_seconds: int = 90
    dev_auth: bool = False
    admin_token: str = ""
    aura_api_base_url: str = ""
    aura_service_token: str = ""
    aura_intent_ttl_seconds: int = 900
    cookie_name: str = "audiobook_session"
    csrf_cookie_name: str = "audiobook_csrf"
    oauth_cookie_name: str = "audiobook_oauth"
    cookie_secure: bool = True
    cookie_domain: str = ""
    cors_origins: tuple[str, ...] = field(default_factory=tuple)
    policy_version: str = "lot1-2026-11"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ConfigError("AUDIOBOOK_DSN is required")
        if not _SCHEMA_RE.fullmatch(self.schema):
            raise ConfigError(
                "AUDIOBOOK_SCHEMA must match [a-z_][a-z0-9_]{0,62}"
            )
        if self.session_ttl_seconds <= 0:
            raise ConfigError("session TTL must be positive")
        if self.playback_lease_seconds <= 0:
            raise ConfigError("playback lease must be positive")
        if self.access_decision_ttl_seconds <= 0:
            raise ConfigError("access decision TTL must be positive")
        if self.cookie_secure and urlparse(self.public_base_url).scheme != "https":
            # Never silently insecure: a secure session cookie on an HTTP base
            # URL means sign-in can never work. Local development must opt out
            # explicitly with AUDIOBOOK_COOKIE_SECURE=0.
            raise ConfigError(
                "COOKIE_SECURE=1 requires an https AUDIOBOOK_PUBLIC_BASE_URL; "
                "set AUDIOBOOK_COOKIE_SECURE=0 for local HTTP development"
            )

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/v1/auth/google/callback"

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            origin.strip()
            for origin in _env("AUDIOBOOK_CORS_ORIGINS").split(",")
            if origin.strip()
        )
        return cls(
            dsn=_env("AUDIOBOOK_DSN"),
            schema=_env("AUDIOBOOK_SCHEMA", "audiobook"),
            public_base_url=_env(
                "AUDIOBOOK_PUBLIC_BASE_URL", "http://localhost:8080"
            ).rstrip("/"),
            post_login_redirect=_env("AUDIOBOOK_POST_LOGIN_REDIRECT", "/"),
            google_client_id=_env("GOOGLE_CLIENT_ID"),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
            session_ttl_seconds=_int(
                "AUDIOBOOK_SESSION_TTL_SECONDS", 60 * 60 * 24 * 30
            ),
            oauth_cookie_ttl_seconds=_int(
                "AUDIOBOOK_OAUTH_COOKIE_TTL_SECONDS", 600
            ),
            access_decision_ttl_seconds=_int(
                "AUDIOBOOK_ACCESS_DECISION_TTL_SECONDS", 60
            ),
            playback_lease_seconds=_int(
                "AUDIOBOOK_PLAYBACK_LEASE_SECONDS", 120
            ),
            heartbeat_timeout_seconds=_int(
                "AUDIOBOOK_HEARTBEAT_TIMEOUT_SECONDS", 90
            ),
            dev_auth=_bool("AUDIOBOOK_DEV_AUTH", False),
            admin_token=_env("AUDIOBOOK_ADMIN_TOKEN"),
            aura_api_base_url=_env("AURA_API_BASE_URL").rstrip("/"),
            aura_service_token=_env("AURA_SERVICE_TOKEN"),
            aura_intent_ttl_seconds=_int("AUDIOBOOK_AURA_INTENT_TTL_SECONDS", 900),
            cookie_name=_env("AUDIOBOOK_COOKIE_NAME", "audiobook_session"),
            csrf_cookie_name=_env(
                "AUDIOBOOK_CSRF_COOKIE_NAME", "audiobook_csrf"
            ),
            oauth_cookie_name=_env(
                "AUDIOBOOK_OAUTH_COOKIE_NAME", "audiobook_oauth"
            ),
            cookie_secure=_bool("AUDIOBOOK_COOKIE_SECURE", True),
            cookie_domain=_env("AUDIOBOOK_COOKIE_DOMAIN"),
            cors_origins=origins,
            policy_version=_env("AUDIOBOOK_POLICY_VERSION", "lot1-2026-11"),
            log_level=_env("AUDIOBOOK_LOG_LEVEL", "INFO").upper(),
        )
