"""The pending-intent cap must only count *live* intents.

An interrupted import (session loss, reload) leaves its intents ``pending``
until the reconciliation sweep deletes their bytes. Those rows used to count
against ``AURA_MAX_PENDING_INTENTS``, so a resume minting fresh intents was
answered with 429 and crawled on retries. Expired rows are now ignored.
"""
import os
import time
import uuid

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")

import api.main as main  # noqa: E402


def _pending(space_id: str, owner_id: str, expires_at: int) -> None:
    main.repo.create_pending_object(
        space_id=space_id,
        application_id=None,
        environment=None,
        bucket="bucket",
        object_key=f"key-{uuid.uuid4()}",
        display_name="file.txt",
        content_type="text/plain",
        owner_id=owner_id,
        actor_id=owner_id,
        actor_kind="user",
        intent_expires_at=expires_at,
        expected_size_bytes=4,
    )


def test_count_pending_ignores_expired_intents():
    # PostgreSQL enforces the users/spaces foreign keys (SQLite does not), so
    # the fixture must create a real tenant instead of an arbitrary id.
    application_id, _ = main.repo.default_scope()
    assert application_id is not None
    space_id = main.repo.create_space(
        application_id, f"pending-{uuid.uuid4().hex}", "test"
    )
    owner_id = main.repo.create_user(
        f"pending-{uuid.uuid4().hex}", "x", "user", space_id=space_id,
        application_id=application_id,
    )
    now = int(time.time())
    for _ in range(3):
        _pending(space_id, owner_id, now - 3600)  # expired long ago, not swept yet
    _pending(space_id, owner_id, now + 600)  # live

    assert main.repo.count_pending(space_id=space_id) == 4
    assert main.repo.count_pending(
        space_id=space_id, min_expires_at=now - 300
    ) == 1
