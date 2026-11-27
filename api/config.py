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


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be a number")


def _csv_lower(name: str) -> tuple[str, ...]:
    """Parse a comma-separated setting into normalized, non-empty values."""
    return tuple(
        part.strip().lower()
        for part in os.environ.get(name, "").split(",")
        if part.strip()
    )


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
    # Integrated PostgreSQL pool (#325). A single VPS has no separate proxy:
    # psycopg_pool keeps a bounded set of connections per process and reports
    # acquisitions/timeouts through Repository.pool_metrics().
    db_pool_min: int = _int("AURA_DB_POOL_MIN", 2)
    db_pool_max: int = _int("AURA_DB_POOL_MAX", 10)
    db_pool_timeout_s: float = _float("AURA_DB_POOL_TIMEOUT", 5.0)
    # Lifetimes (seconds).
    # Human session cookie lifetime: 8 hours by default (audit H6 kept the
    # default short). A longer session (e.g. 2592000 = 30 days) widens the window
    # during which a stolen cookie stays valid; that is compensated by the
    # HttpOnly + Secure + SameSite=Strict cookie and the CSRF double-submit
    # enforced in api/main.py. The expiry is fixed at login (no rolling renewal),
    # so logout or TTL expiry truly ends the session. Override deliberately via
    # AURA_SESSION_TTL in .env if a longer session is an operational requirement.
    session_ttl: int = _int("AURA_SESSION_TTL", 28800)
    intent_ttl: int = _int("AURA_INTENT_TTL", 900)
    # Grace period after intent_ttl during which a commit is still accepted
    # (upload may finish just before expiry; #37).
    intent_grace_s: int = _int("AURA_INTENT_GRACE_SECONDS", 300)
    replay_refresh_margin_s: int = _int("AURA_REPLAY_REFRESH_MARGIN_SECONDS", 60)
    # Public share links (api/shares.py). A share is an unauthenticated,
    # revocable read-only capability for one object: the token is stored as a
    # SHA-256 fingerprint and redeemed through a 302 to a presigned URL.
    # `share_base_url` is the externally reachable origin used to build the
    # absolute link. It is configuration and is never derived from the request
    # Host header, which a client controls.
    share_base_url: str = os.environ.get("AURA_SHARE_BASE_URL", "").rstrip("/")
    # Default lifetime (7 days) and hard ceiling (30 days). The ceiling is a
    # policy limit: a longer request is refused, not clamped silently.
    share_ttl_default: int = _int("AURA_SHARE_TTL_DEFAULT", 604800)
    share_ttl_max: int = _int("AURA_SHARE_TTL_MAX", 2592000)
    # Lifetime of the presigned URL behind each redemption. Kept short so a
    # copied redirect target (browser history, proxy log) is useless quickly.
    share_presign_ttl: int = _int("AURA_SHARE_PRESIGN_TTL", 60)
    # Audit log (JSON-lines, IDs and statuses only — never secrets or URLs).
    # The Compose stack pins an absolute path on the persistent `api-audit`
    # volume, so events survive container recreations; this relative default is
    # for local/dev runs only. `audit_event` creates the parent directory on
    # first write, and the /admin/health disk probe measures that directory, not
    # the file, so a not-yet-written log never reports the disk as unreadable.
    audit_log: str = os.environ.get("AURA_AUDIT_LOG", "aura-audit.jsonl")
    # Login rate limit (failed attempts per window, per client IP). A successful
    # login clears the counter for that client.
    login_rate_limit: int = _int("AURA_LOGIN_RATE_LIMIT", 10)
    login_rate_window: int = _int("AURA_LOGIN_RATE_WINDOW", 60)
    # Machine-to-machine authentication failure rate limit (per client IP; #38).
    m2m_rate_limit: int = _int("AURA_M2M_RATE_LIMIT", 60)
    quota_bytes_per_day: int = _int("AURA_QUOTA_BYTES_PER_DAY", 0)
    quota_files_per_day: int = _int("AURA_QUOTA_FILES_PER_DAY", 0)
    m2m_rate_window: int = _int("AURA_M2M_RATE_WINDOW", 60)
    # Reverse proxies trusted to set X-Forwarded-For when resolving the client
    # IP for the rate limiters (#35/#38). Comma-separated IPs or CIDRs; defaults
    # to the loopback/RFC1918 ranges Docker uses, since the API is only reachable
    # on the internal network. See api/netinfo.py.
    trusted_proxies: tuple[str, ...] = tuple(
        part.strip()
        for part in os.environ.get(
            "AURA_TRUSTED_PROXIES",
            "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        ).split(",")
        if part.strip()
    )
    # Upload/commit technical limits (#37, #40). Defaults are guard rails, not billing.
    #
    # ``max_object_bytes`` is the single-request upload ceiling. It must stay at
    # or below the S3 backend's single-PUT limit (SeaweedFS/AWS: 5 GiB) until the
    # multipart workflow is implemented and compatibility-tested; see
    # docs/TRANSFER-ENGINE.md. The default equals that limit on purpose.
    max_object_bytes: int = _int("AURA_MAX_OBJECT_BYTES", 5 * 1024 * 1024 * 1024)
    # Multipart upload (#72). Off by default until the compatibility gate in
    # docs/MULTIPART-UPLOAD-PLAN.md is recorded on the pinned SeaweedFS image.
    # When on, files at or above the threshold are sent as independently
    # retried parts and may exceed ``max_object_bytes`` up to the multipart cap.
    multipart_enabled: bool = os.environ.get("AURA_MULTIPART_ENABLED", "0") == "1"
    # In-process HLS worker (one job at a time, ffmpeg nice + 1 thread). Disable
    # when running several API replicas until the lease/queue is externalised.
    media_worker_enabled: bool = os.environ.get("AURA_MEDIA_WORKER", "1") == "1"
    # AI audio analysis / classification. Disabled by default: enabling requires
    # explicit opt-in and valid provider keys. Gemini is the primary provider
    # (native audio input); Claude is the fallback (transcript/text classification).
    ai_classification_enabled: bool = os.environ.get("AURA_AI_CLASSIFICATION_ENABLED", "0") == "1"
    ai_primary_provider: str = os.environ.get("AURA_AI_PRIMARY_PROVIDER", "gemini").strip().lower()
    ai_fallback_provider: str = os.environ.get("AURA_AI_FALLBACK_PROVIDER", "claude").strip().lower()
    gemini_api_key: str = os.environ.get("AURA_GEMINI_API_KEY", "")
    gemini_model: str = os.environ.get("AURA_GEMINI_MODEL", "gemini-4-hydrogen")
    anthropic_api_key: str = os.environ.get("AURA_ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.environ.get("AURA_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ai_confidence_threshold: float = _float("AURA_AI_CONFIDENCE_THRESHOLD", 0.80)
    ai_timeout_s: int = _int("AURA_AI_TIMEOUT_S", 120)
    multipart_threshold_bytes: int = _int("AURA_MULTIPART_THRESHOLD_BYTES", 100 * 1024 * 1024)
    # Each part is one request through the edge proxy: keep part / slowest
    # supported rate well under Traefik's readTimeout (see the plan).
    multipart_part_bytes: int = _int("AURA_MULTIPART_PART_BYTES", 16 * 1024 * 1024)
    # Never allow a planned part above S3's 5 GiB ceiling: 5,000 operational
    # parts × 5 GiB (≈ 24.4 TiB) is the largest object the server can plan.
    multipart_max_object_bytes: int = min(
        _int("AURA_MULTIPART_MAX_OBJECT_BYTES", 1024 * 1024 * 1024 * 1024),
        5_000 * 5 * 1024 * 1024 * 1024,
    )
    # A multipart session outlives a single-PUT intent: a large upload may be
    # paused (reload, sleep, network loss) and resumed within this window.
    multipart_session_ttl: int = _int("AURA_MULTIPART_SESSION_TTL", 7 * 24 * 3600)
    # Asynchronous integrity check (N5). At or above this size, commit answers
    # 202 'verifying' and a worker hashes the object outside the request.
    verify_async_threshold_bytes: int = _int(
        "AURA_VERIFY_ASYNC_THRESHOLD_BYTES", 32 * 1024 * 1024
    )
    # Hold verification back while uploads are running: the re-read competes
    # with the PUTs for the disk (5.8-7.1x slower under 4 concurrent writes,
    # docs/engineering/commit-latency-bench.md). A pending intent created within
    # the window counts as a running upload; abandoned ones age out of it.
    verify_pause_while_uploading: bool = _int("AURA_VERIFY_PAUSE_WHILE_UPLOADING", 1) != 0
    verify_pause_window_s: int = _int("AURA_VERIFY_PAUSE_WINDOW_S", 300)
    # "inline": a worker thread inside the API process (default). "off": run
    # `python -m api.verifier` as its own process instead.
    verify_worker: str = os.environ.get("AURA_VERIFY_WORKER", "inline")
    verify_lease_s: int = _int("AURA_VERIFY_LEASE_SECONDS", 300)
    verify_heartbeat_bytes: int = _int("AURA_VERIFY_HEARTBEAT_BYTES", 256 * 1024 * 1024)
    verify_max_attempts: int = _int("AURA_VERIFY_MAX_ATTEMPTS", 8)
    verify_poll_s: int = _int("AURA_VERIFY_POLL_SECONDS", 2)
    # Scrubber: treat transfers started within this window as "disk busy".
    scrub_busy_window_s: int = _int("AURA_SCRUB_BUSY_WINDOW_S", 1800)
    # Hard deadline for a single commit response (seconds). Objects above the
    # async threshold return 202 quickly; this guards the synchronous path.
    av_scan_cmd: str = os.environ.get("AURA_AV_SCAN_CMD", "")
    # A hung scanner must not hold a request (or the verification worker).
    av_scan_timeout_s: int = _int("AURA_AV_SCAN_TIMEOUT_S", 120)
    # Master mode: how long a password-confirmed elevation for bulk purges
    # lasts on one session (seconds), and the most objects one call may purge.
    master_mode_ttl: int = _int("AURA_MASTER_MODE_SECONDS", 900)
    master_bulk_max: int = _int("AURA_MASTER_BULK_MAX", 500)
    # Capacity guard: the usable object-store capacity in bytes (0 = off) and
    # the fill level, in percent, above which new uploads are refused (507).
    # Every upload reserves its declared size from the moment its intent is
    # issued, so concurrent imports cannot overfill the single disk.
    storage_capacity_bytes: int = _int("AURA_STORAGE_CAPACITY_BYTES", 0)
    storage_high_watermark_pct: int = _int("AURA_STORAGE_HIGH_WATERMARK", 90)
    # Periodic integrity scrub (api/scrubber.py): every available object is
    # re-hashed at least once per interval, oldest check first, within a byte
    # budget per run so the disk is never saturated. Read-only: it reports,
    # it never deletes or rewrites.
    scrub_enabled: bool = os.environ.get("AURA_SCRUB_ENABLED", "1") == "1"
    scrub_interval_days: int = _int("AURA_SCRUB_INTERVAL_DAYS", 30)
    scrub_bytes_per_run: int = _int("AURA_SCRUB_BYTES_PER_RUN", 10 * 1024 ** 3)
    scrub_period_s: int = _int("AURA_SCRUB_PERIOD_SECONDS", 3600)
    # Storage orphans (api/storage_reconcile.py): bytes younger than this are
    # never reported or removed, so an upload in flight is never mistaken for one.
    orphan_grace_s: int = _int("AURA_ORPHAN_GRACE_SECONDS", 86400)
    # Automatic reconciliation sweep (#144). The sweep existed only as an
    # admin route nothing called; it now runs on its own, like the verifier
    # and the scrubber. ``reconcile_extra_grace_s`` is the safety margin the
    # automatic sweep adds on top of the intent life (intent_ttl +
    # intent_grace_s): a slow upload in progress must never lose its bytes to
    # a sweep, so the automatic window is wider than the manual route's.
    reconcile_enabled: bool = os.environ.get("AURA_RECONCILE_ENABLED", "1") == "1"
    # Compose historically injected AURA_RECONCILE_INTERVAL_SECONDS while the
    # code read AURA_RECONCILE_INTERVAL_S: raising the interval in .env had no
    # effect. Accept both names; the short one wins when both are set.
    reconcile_interval_s: int = _int(
        "AURA_RECONCILE_INTERVAL_S",
        _int("AURA_RECONCILE_INTERVAL_SECONDS", 300),
    )
    reconcile_limit: int = _int("AURA_RECONCILE_LIMIT", 500)
    reconcile_extra_grace_s: int = _int("AURA_RECONCILE_EXTRA_GRACE_SECONDS", 3600)

    # Import jobs worker (api/import_worker.py): processes queued bulk-import
    # jobs booked by the API. The current contract carries no per-item payload,
    # so the worker completes booked batches as a stub (marking items processed)
    # while providing lease/claim, cancellation handling and crash recovery.
    import_worker_enabled: bool = os.environ.get("AURA_IMPORT_WORKER_ENABLED", "1") == "1"
    import_worker_poll_s: int = _int("AURA_IMPORT_WORKER_POLL_SECONDS", 2)
    import_worker_lease_s: int = _int("AURA_IMPORT_WORKER_LEASE_SECONDS", 300)
    # Append-only terminal transfer journal (#246). Rows older than this are
    # purged by the reconciliation sweep; the journal is a retention window,
    # never the source of truth (that stays `objects`).
    transfer_history_retention_days: int = _int(
        "AURA_TRANSFER_HISTORY_RETENTION_DAYS", 90
    )
    commit_chunk_bytes: int = _int("AURA_COMMIT_CHUNK_BYTES", 1024 * 1024)
    # Global deadline for one commit request (hashing phase, #120): past it the
    # intent is marked failed and the client gets 504 instead of an unbounded
    # wait. Must stay *below* the app proxy's read timeout for the commit route
    # (app/nginx.conf, 310 s) so the API's structured 504 wins over the proxy's
    # generic one; change both together.
    commit_deadline_s: int = _int(
        "AURA_COMMIT_DEADLINE_S", _int("AURA_COMMIT_DEADLINE_SECONDS", 300)
    )
    max_pending_intents: int = _int("AURA_MAX_PENDING_INTENTS", 100)
    # Per-owner ceiling on *declared* pending bytes. Without it a single account
    # can reserve the whole capacity with 100 huge intents and never send a
    # byte (multipart raises the per-intent ceiling to 1 TiB for 7 days).
    # 0 disables the per-owner cap (the global capacity guard still applies).
    max_pending_bytes_per_owner: int = _int(
        "AURA_MAX_PENDING_BYTES_PER_OWNER", 100 * 1024 ** 3
    )
    # Zero-byte objects are refused by default: an empty upload is usually a
    # client bug rather than intent. Enable only when a caller legitimately needs
    # empty placeholders (the commit path verifies the empty SHA-256 either way).
    allow_empty_objects: bool = os.environ.get("AURA_ALLOW_EMPTY_OBJECTS", "0") == "1"
    # Optional server-side content-type allow-list, comma-separated and
    # case-insensitive (``image/png,application/pdf,text/*``). Empty means every
    # syntactically valid media type is accepted. This is a server-enforced
    # control: a frontend ``accept`` attribute is never trusted as a policy.
    allowed_content_types: tuple[str, ...] = tuple(
        part.strip().lower()
        for part in os.environ.get("AURA_ALLOWED_CONTENT_TYPES", "").split(",")
        if part.strip()
    )
    # Audit observability bounds (M07). Reads scan a bounded tail so a large
    # history cannot exhaust the API; retention pruning drops only lines older
    # than the window and never lines without a valid timestamp.
    audit_retention_days: int = _int("AURA_AUDIT_RETENTION_DAYS", 90)
    audit_max_scan_lines: int = _int("AURA_AUDIT_MAX_SCAN_LINES", 20000)
    audit_error_scan_lines: int = _int("AURA_AUDIT_ERROR_SCAN_LINES", 5000)
    audit_error_window_s: int = _int("AURA_AUDIT_ERROR_WINDOW_S", 3600)
    # Upper bound (characters) for a client-supplied ``Idempotency-Key`` header.
    idempotency_key_max: int = _int("AURA_IDEMPOTENCY_KEY_MAX", 200)
    # Refuse to commit an object the storage does not report as encrypted at
    # rest (SSE-S3 ``AES256``). Disable only against a backend without SSE-S3.
    require_sse: bool = os.environ.get("AURA_REQUIRE_SSE", "1") == "1"
    # Cookie security.
    cookie_secure: bool = os.environ.get("AURA_COOKIE_SECURE", "1") == "1"

    # Public portal (dedicated subdomain). The domain is configuration, never
    # derived from a client-supplied Host header: it builds the OAuth redirect
    # URI and guards the HTML root. Empty = portal disabled (routes answer 503).
    public_domain: str = os.environ.get("PUBLIC_DOMAIN", "").strip().lower()
    # Separate cookie from the admin console: host-only on the public domain,
    # SameSite=Lax is required for the redirect back from Google (Strict would
    # drop the cookie on a cross-site top-level navigation).
    public_session_cookie: str = "aura_public_session"
    public_session_ttl: int = _int("AURA_PUBLIC_SESSION_TTL", 7 * 24 * 3600)
    # A book is hours long; the 15-minute upload intent TTL would break seeks
    # and buffered playback once the browser followed the /m/<slug> redirect.
    # This TTL applies only to published public media, never to upload intents.
    public_media_ttl: int = _int("AURA_PUBLIC_MEDIA_TTL", 12 * 3600)
    # Lifetime of a service-issued /a/<token> media grant (gate D-08). The
    # audiobook service mints one only after its own entitlement decision. Keep
    # this shorter than the permanent /m/ playback TTL: the storage redirect
    # issued on redemption is capped by the grant's remaining lifetime.
    public_access_grant_ttl: int = _int("AURA_PUBLIC_ACCESS_GRANT_TTL", 15 * 60)
    # Recommendation engine for the public "Pour vous" shelf. "audiobook"
    # reuses the scoring extracted from the audiobook service; "local" keeps
    # the historical author-only recommender.
    public_recommendations_engine: str = os.environ.get(
        "AURA_PUBLIC_RECOMMENDATIONS_ENGINE", "audiobook"
    ).strip().lower()
    # Gate D-08: slugs listed here stop resolving through the permanent public
    # URL. Paid/entitled titles must instead be served by a short service-issued
    # URL decided by the audiobook service (docs/audiobook/README.md §2.3).
    public_media_restricted_slugs: tuple[str, ...] = _csv_lower(
        "AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS"
    )
    # /m/{slug} used to be a permanent anonymous download URL. Full listening is
    # now reserved to signed-in visitors by default; only explicitly allowlisted
    # slugs (trusted course embeds) remain open. Set to 0 to restore the old
    # behaviour, but that also restores anonymous full-book downloads.
    public_media_require_auth: bool = os.environ.get(
        "AURA_PUBLIC_MEDIA_REQUIRE_AUTH", "1"
    ).strip().lower() not in ("0", "false", "no", "off")
    public_media_open_slugs: tuple[str, ...] = _csv_lower(
        "AURA_PUBLIC_MEDIA_OPEN_SLUGS"
    )
    # Anonymous browsing of the published catalogue (landing, book pages, sitemap).
    # Listening in full still goes through the signed-in portal; set to 0 to
    # restore the sign-in-only front page.
    public_browse: bool = os.environ.get("AURA_PUBLIC_BROWSE", "1").strip().lower() not in (
        "0", "false", "no", "off")
    # Free preview length for anonymous visitors (MP3 only); 0 disables it.
    public_preview_seconds: int = _int("AURA_PUBLIC_PREVIEW_SECONDS", 60)
    # Append-only listening events (#320). Events older than this are pruned
    # when a visitor's stats are projected; the legacy position-based estimate
    # remains available for comparisons. Anonymised events keep aggregate value
    # without identifying a deleted account.
    listen_event_retention_days: int = _int("AURA_LISTEN_EVENT_RETENTION_DAYS", 365)
    # Legacy switch kept for compatibility: it used to gate full-file access.
    # Listening is now always available to signed-in listeners (/m/{slug});
    # use public_download_require_premium for the paid capability.
    public_require_premium: bool = os.environ.get(
        "AURA_PUBLIC_REQUIRE_PREMIUM", "1"
    ).strip().lower() not in ("0", "false", "no", "off")
    # Download is the paid capability: /d/{slug} and share links for published
    # objects always require a "premium" plan unless explicitly set to 0.
    public_download_require_premium: bool = os.environ.get(
        "AURA_PUBLIC_DOWNLOAD_REQUIRE_PREMIUM", "1"
    ).strip().lower() not in ("0", "false", "no", "off")
    # Bootstrap: verified e-mail addresses promoted to "premium" at sign-in.
    # Existing premium rows are never downgraded when this list changes.
    premium_emails: tuple[str, ...] = tuple(
        part.strip().lower()
        for part in os.environ.get("AURA_PREMIUM_EMAILS", "").split(",")
        if part.strip()
    )
    # E-mail sign-in link ("magic link") for visitors without a Google account.
    # Disabled until a mail server is configured; the link is single-use and
    # short-lived, and it only confirms control of the mailbox.
    smtp_host: str = os.environ.get("AURA_SMTP_HOST", "").strip()
    smtp_port: int = _int("AURA_SMTP_PORT", 587)
    smtp_user: str = os.environ.get("AURA_SMTP_USER", "").strip()
    smtp_password: str = os.environ.get("AURA_SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("AURA_SMTP_FROM", "").strip()
    smtp_starttls: bool = os.environ.get("AURA_SMTP_STARTTLS", "1").strip().lower() not in (
        "0", "false", "no", "off")
    email_link_ttl: int = _int("AURA_EMAIL_LINK_TTL", 900)
    # Google OAuth 2.0 Authorization Code + PKCE. No secret is hard-coded; both
    # values come from .env and are passed to the API container explicitly.
    google_client_id: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    google_allowed_email_domains: tuple[str, ...] = tuple(
        part.strip().lower()
        for part in os.environ.get("GOOGLE_ALLOWED_EMAIL_DOMAINS", "").split(",")
        if part.strip()
    )


settings = Settings()

# Fail fast on misconfigured audit observability bounds (M07). A zero/negative
# scan window would silently disable reads and a negative retention would make
# pruning unbounded, so refuse the process at import instead of degrading at
# runtime. The readers in api/audit.py are also hardened defensively.
if settings.audit_retention_days < 1:
    raise RuntimeError("AURA_AUDIT_RETENTION_DAYS must be >= 1")
if settings.audit_max_scan_lines < 1:
    raise RuntimeError("AURA_AUDIT_MAX_SCAN_LINES must be >= 1")
if settings.audit_error_scan_lines < 1:
    raise RuntimeError("AURA_AUDIT_ERROR_SCAN_LINES must be >= 1")
if settings.audit_error_window_s < 0:
    raise RuntimeError("AURA_AUDIT_ERROR_WINDOW_S must be >= 0")
# A zero/negative commit deadline would fail every commit instead of
# guarding one (#120), so refuse the process at boot.
if settings.commit_deadline_s < 1:
    raise RuntimeError("AURA_COMMIT_DEADLINE_S must be >= 1")
# A sweep every second would hammer the storage and the catalogue (#144).
if settings.reconcile_interval_s < 30:
    raise RuntimeError("AURA_RECONCILE_INTERVAL_S must be >= 30")
if settings.transfer_history_retention_days < 1:
    raise RuntimeError("AURA_TRANSFER_HISTORY_RETENTION_DAYS must be >= 1")
if settings.listen_event_retention_days < 1:
    raise RuntimeError("AURA_LISTEN_EVENT_RETENTION_DAYS must be >= 1")
if settings.db_pool_min < 1 or settings.db_pool_max < settings.db_pool_min:
    raise RuntimeError("AURA_DB_POOL_MIN/MAX must satisfy 1 <= min <= max")
if settings.db_pool_timeout_s <= 0:
    raise RuntimeError("AURA_DB_POOL_TIMEOUT must be > 0")
