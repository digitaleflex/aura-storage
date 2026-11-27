"""The shared rate counter must be exact whatever the wall clock says.

Regression for the intermittent ``test_login_rate_limit_429_after_window_exhausted`` and
``test_hls_and_subtitle_routes_are_rate_limited`` failures on PostgreSQL. The cause was
real and not a flaky test: ``public_rate_counters.window_start`` was ``REAL``, a 4-byte
float on PostgreSQL. A Unix time (~1.8e9) is then stored with 128 s granularity, so a
60 s window started up to 64 s off. For about one start time in ten, ten failed logins
did not block the eleventh attempt, i.e. brute-force protection silently failed.

These tests use simulated clocks, so they are deterministic and run on both backends.
"""
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

import api.main as main  # noqa: E402

BASE = 1_795_000_000.0  # a realistic Unix time: the magnitude is what matters
WINDOW = 60
LIMIT = 10


def _key() -> str:
    return f"precision-test:{uuid.uuid4().hex}"


def test_ten_failures_always_block_the_eleventh_attempt():
    """The login scenario at every offset of a 4-minute span (covers two 128 s grids)."""
    repo = main.repo
    blocked_wrongly = []
    for offset in range(0, 256):
        key, start = _key(), BASE + offset + 0.3
        for i in range(LIMIT):  # ten failed logins, one second apart
            repo.rate_hit(key, now=start + i, window=WINDOW, limit=LIMIT)
        allowed, retry = repo.rate_peek(key, now=start + LIMIT, window=WINDOW, limit=LIMIT)
        if allowed or retry < 1:
            blocked_wrongly.append(offset)
    assert not blocked_wrongly, (
        f"{len(blocked_wrongly)} start times let the limit be exceeded, e.g. {blocked_wrongly[:8]}"
    )


def test_the_window_really_lasts_sixty_seconds():
    repo = main.repo
    wrong = []
    for offset in range(0, 256, 3):
        key, start = _key(), BASE + offset + 0.3
        for i in range(LIMIT + 1):
            repo.rate_hit(key, now=start, window=WINDOW, limit=LIMIT)
        still, _ = repo.rate_peek(key, now=start + WINDOW - 1, window=WINDOW, limit=LIMIT)
        over, _ = repo.rate_peek(key, now=start + WINDOW + 1, window=WINDOW, limit=LIMIT)
        if still or not over:
            wrong.append((offset, still, over))
    assert not wrong, f"window length is off for start offsets: {wrong[:5]}"


def test_a_counter_restarts_after_its_window_and_counts_again():
    repo = main.repo
    for offset in (0, 37, 64, 100, 127):
        key, start = _key(), BASE + offset + 0.3
        for _ in range(LIMIT + 2):
            repo.rate_hit(key, now=start, window=WINDOW, limit=LIMIT)
        assert repo.rate_hit(key, now=start + 5, window=WINDOW, limit=LIMIT)[0] is False
        assert repo.rate_hit(key, now=start + WINDOW + 1, window=WINDOW, limit=LIMIT)[0] is True
        for _ in range(LIMIT - 1):
            assert repo.rate_hit(key, now=start + WINDOW + 2, window=WINDOW, limit=LIMIT)[0] is True
        assert repo.rate_hit(key, now=start + WINDOW + 3, window=WINDOW, limit=LIMIT)[0] is False


@pytest.mark.skipif(main.repo.dialect != "postgres", reason="PostgreSQL column type")
def test_postgres_stores_the_window_start_in_double_precision():
    kind = main.repo._one(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'public_rate_counters' AND column_name = 'window_start'"
    )["data_type"]
    assert kind == "double precision"
    key = _key()
    main.repo.rate_hit(key, now=BASE + 0.25, window=WINDOW, limit=LIMIT)
    stored = main.repo._one("SELECT window_start FROM public_rate_counters WHERE key = %s", (key,))
    assert stored["window_start"] == BASE + 0.25  # sub-second exactness


@pytest.mark.skipif(main.repo.dialect != "postgres", reason="PostgreSQL migration")
def test_an_existing_four_byte_column_is_widened_by_the_migration():
    """A catalogue created before the fix must be repaired at the next start."""
    from api.migrations import apply_migrations

    repo = main.repo
    repo._run("ALTER TABLE public_rate_counters ALTER COLUMN window_start TYPE REAL")
    legacy = repo._one(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'public_rate_counters' AND column_name = 'window_start'"
    )["data_type"]
    assert legacy == "real"
    apply_migrations(repo.conn, "postgres")
    fixed = repo._one(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'public_rate_counters' AND column_name = 'window_start'"
    )["data_type"]
    assert fixed == "double precision"
    apply_migrations(repo.conn, "postgres")  # idempotent: second start changes nothing
