"""Environment-driven settings. No secrets are hard-coded; all secrets come from env."""
import os


def _req(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    # Admin bootstrap credential (initial password; hashed into the DB on boot).
    admin_user: str = os.environ.get("AURA_API_ADMIN_USER", "admin")
    admin_password: str = _req("AURA_API_ADMIN_PASSWORD")
    # S3 data plane (server-side only; never sent to browsers).
    s3_endpoint: str = os.environ.get("AURA_S3_ENDPOINT", "https://aura-storage.eurinhash.com")
    s3_access_key: str = _req("AURA_S3_ACCESS_KEY")
    s3_secret_key: str = _req("AURA_S3_SECRET_KEY")
    s3_region: str = os.environ.get("AURA_S3_REGION", "us-east-1")
    # Catalogue database path (SQLite for #18; PostgreSQL replaces it in #19).
    db_path: str = os.environ.get("AURA_API_DB", "aura-catalogue.db")
    # Lifetimes (seconds).
    session_ttl: int = int(os.environ.get("AURA_SESSION_TTL", "28800"))
    intent_ttl: int = int(os.environ.get("AURA_INTENT_TTL", "900"))
    # Cookie security.
    cookie_secure: bool = os.environ.get("AURA_COOKIE_SECURE", "1") == "1"
    # Audit log (JSON-lines, IDs and statuses only — never secrets or URLs).
    audit_log: str = os.environ.get("AURA_AUDIT_LOG", "aura-audit.jsonl")
    # Login rate limit (attempts per window, per client IP).
    login_rate_limit: int = int(os.environ.get("AURA_LOGIN_RATE_LIMIT", "10"))
    login_rate_window: int = int(os.environ.get("AURA_LOGIN_RATE_WINDOW", "60"))


settings = Settings()
