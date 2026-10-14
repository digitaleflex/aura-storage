"""Better Auth session bridge. FastAPI trusts the better-auth `session` table.

The browser holds `aura.session_token=<token>.<signature>` (HttpOnly). The
token part is a server-generated secret; its presence + freshness in the DB
is the authentication check. Mutations additionally require an allow-listed
Origin (CSRF). Production tables come from `better-auth migrate`; tests
create the same minimal shape via ensure_test_tables().
"""
import datetime
import os
import time

TRUSTED_ORIGINS = [
    o for o in os.environ.get("AURA_TRUSTED_ORIGINS", "").split(",") if o
]

_PG_TABLES = """
CREATE TABLE IF NOT EXISTS "user" (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  "emailVerified" BOOLEAN NOT NULL DEFAULT false, image TEXT,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS session (
  id TEXT PRIMARY KEY,
  "expiresAt" TIMESTAMPTZ NOT NULL,
  token TEXT UNIQUE NOT NULL,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
  "ipAddress" TEXT, "userAgent" TEXT,
  "userId" TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS account (
  id TEXT PRIMARY KEY, "accountId" TEXT NOT NULL, "providerId" TEXT NOT NULL,
  "userId" TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  "accessToken" TEXT, "refreshToken" TEXT, "idToken" TEXT,
  "accessTokenExpiresAt" TIMESTAMPTZ, "refreshTokenExpiresAt" TIMESTAMPTZ,
  scope TEXT, password TEXT,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS verification (
  id TEXT PRIMARY KEY, identifier TEXT NOT NULL, value TEXT NOT NULL,
  "expiresAt" TIMESTAMPTZ NOT NULL,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS "user" (
  id TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE,
  "emailVerified" INTEGER, image TEXT,
  "createdAt" INTEGER, "updatedAt" INTEGER
);
CREATE TABLE IF NOT EXISTS session (
  id TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL,
  "expiresAt" INTEGER NOT NULL, "userId" TEXT NOT NULL
);
"""


def _is_sqlite(repo) -> bool:
    return "sqlite3" in type(repo.conn).__module__


def ensure_test_tables(repo) -> None:
    """Create the minimal better-auth table shape for tests (both engines)."""
    if _is_sqlite(repo):
        repo.conn.executescript(_SQLITE_TABLES)
        repo.conn.commit()
    else:
        with repo.conn.cursor() as cur:
            cur.execute(_PG_TABLES)
            for col, typ in (('"createdAt"', "TIMESTAMPTZ"), ('"updatedAt"', "TIMESTAMPTZ")):
                cur.execute(
                    f'ALTER TABLE session ADD COLUMN IF NOT EXISTS {col} {typ}'
                )


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _as_ts(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    dt = value
    if isinstance(value, str):
        dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def lookup_session(repo, token: str):
    """Return {'id': user_id} for a live session token, else None."""
    if _is_sqlite(repo):
        row = repo.conn.execute(
            'SELECT "userId", "expiresAt" FROM session WHERE token = ?', (token,)
        ).fetchone()
        if row is None or _as_ts(row[1]) <= int(time.time()):
            return None
        return {"id": row[0]}
    with repo.conn.cursor() as cur:
        cur.execute(
            'SELECT "userId", "expiresAt" FROM session WHERE token = %s', (token,)
        )
        r = cur.fetchone()
    if r is None or _as_ts(r["expiresAt"]) <= int(time.time()):
        return None
    return {"id": str(r["userId"])}  # uuid.UUID -> str for catalogue keys


def extract_token(cookie_value: str | None) -> str | None:
    if not cookie_value:
        return None
    return cookie_value.split(".")[0] or None
