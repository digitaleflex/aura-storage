"""Catalogue concurrency: the single shared connection must survive a threadpool.

FastAPI runs sync endpoints in a worker threadpool, so the one catalogue
connection (SQLite in dev/test, psycopg on the pilot) is used from several
threads at once. Neither ``sqlite3`` nor ``psycopg`` supports that: it surfaced
as ``sqlite3.InterfaceError: bad parameter or other API misuse`` and, through the
auth path, as transient 401/500 responses. The repository must serialize access.

Runs on a disposable SQLite file; no PostgreSQL or S3 endpoint needed.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")

from api.db import Repository  # noqa: E402


def test_concurrent_repository_access_is_serialized(tmp_path):
    repo = Repository(str(tmp_path / "concurrency.db"))
    uid = repo.create_user("concurrency-user", "hash", role="user")
    sid = repo.create_session(uid, "csrf", int(time.time()) + 3600)
    bucket_space = repo.default_scope()[1]
    assert bucket_space is not None

    workers = 12
    rounds = 150
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def reader():
        try:
            barrier.wait()
            for _ in range(rounds):
                # The auth hot path: read a session, read the catalogue, count.
                assert repo.get_session(sid) is not None
                repo.get_user(uid)
                repo.get_space(bucket_space)
                repo.list_applications()
                repo.stats()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def writer(index):
        try:
            barrier.wait()
            for n in range(rounds):
                aid = repo.create_application(f"w-{index}-{n}")
                repo.update_application(aid, status="disabled")
                repo.application_name_exists(f"w-{index}-{n}", exclude_id=aid)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(reader) for _ in range(workers - 4)]
        futures += [pool.submit(writer, i) for i in range(4)]
        for future in futures:
            future.result()

    # No interleaving may corrupt the shared connection.
    assert errors == [], errors[:3]
