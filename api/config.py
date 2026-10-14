"""Environment-driven settings. No secrets are hard-coded; all secrets come from env."""
import os


def _req(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer")


class Settings:
    # Admin bootstrap credential (initial password; hashed into the DB on boot).
    admin_user: str = os.environ.get("AURA_API_ADMIN_USER", "admin")
    admin_password: str = _req("AURA_API_ADMIN_PASSWORD")
    # S3 data plane (server-side only; never sent to browsers).
    # Public base embedded in presigned URLs (browser-reachable, no call made).
    s3_endpoint: str = os.environ.get("AURA_S3_ENDPOINT", "https://aura-storage.eurinhash.com")
    # Internal endpoint for server-side S3 calls (no egress needed).
    s3_internal_endpoint: str = os.environ.get(
        "AURA_S3_INTERNAL_ENDPOINT", "http://seaweed-filer:8333"
    )
    s3_access_key: str = _req("AURA_S3_ACCESS_KEY")
    s3_secret_key: str = _req("AURA_S3_SECRET_KEY")
    s3_region: str = os.environ.get("AURA_S3_REGION", "us-east-1")
    # Catalogue database path (SQLite for #18; PostgreSQL replaces it in #19).
    db_path: str = os.environ.get("AURA_API_DB", "aura-catalogue.db")
    # Backend: 'sqlite' (default, dev/test) or 'postgres' (pilot, #19).
    db_backend: str = os.environ.get("AURA_API_BACKEND", "sqlite")
    # PostgreSQL DSN, e.g. postgresql://aura:PASSWORD@localhost:5432/aura.
    # Only used when backend is 'postgres'. Never logged.
    db_dsn: str = os.environ.get("AURA_API_DSN", "")
    # Lifetimes (seconds).
    session_ttl: int = _int("AURA_SESSION_TTL", 28800)
    intent_ttl: int = _int("AURA_INTENT_TTL", 900)
    # Grace period after intent_ttl during which a commit is still accepted
    # (upload may finish just before expiry; #37).
    intent_grace_s: int = _int("AURA_INTENT_GRACE_SECONDS", 300)
    # Audit log (JSON-lines, IDs and statuses only — never secrets or URLs).
    audit_log: str = os.environ.get("AURA_AUDIT_LOG", "aura-audit.jsonl")
    # Login rate limit (attempts per window, per client IP).
    login_rate_limit: int = _int("AURA_LOGIN_RATE_LIMIT", 10)
    login_rate_window: int = _int("AURA_LOGIN_RATE_WINDOW", 60)
    # Machine-to-machine authentication failure rate limit (per client IP; #38).
    m2m_rate_limit: int = _int("AURA_M2M_RATE_LIMIT", 60)
    m2m_rate_window: int = _int("AURA_M2M_RATE_WINDOW", 60)
    # Upload/commit technical limits (#37, #40). Defaults are guard rails, not billing.
    max_object_bytes: int = _int("AURA_MAX_OBJECT_BYTES", 5 * 1024 * 1024 * 1024)
    commit_chunk_bytes: int = _int("AURA_COMMIT_CHUNK_BYTES", 1024 * 1024)
    max_pending_intents: int = _int("AURA_MAX_PENDING_INTENTS", 100)
    # Cookie security.
    cookie_secure: bool = os.environ.get("AURA_COOKIE_SECURE", "1") == "1"


settings = Settings()
