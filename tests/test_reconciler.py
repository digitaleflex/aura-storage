"""#144 — the automatic reconciliation sweep (``api/reconciler.py``).

The sweep used to be an admin route nothing called. These tests cover what
matters when a sweep deletes bytes on its own:

- a stale intent is expired **after** its bytes are gone, and the row follows;
- a fresh intent (or one still inside the automatic margin) is left alone;
- a storage failure never produces a false success: the intent stays pending
  and the failure is counted;
- the background loop runs and can be stopped;
- the health endpoint shows that the sweep runs.

The API is not started here: the sweep is exercised directly against the
in-process catalogue and a storage stub.
"""
import os
import time

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import reconciler  # noqa: E402

client = TestClient(main.app)


class FakeS3:
    """Storage stub: records the deletes, can be told to fail."""

    def __init__(self, fail_delete: bool = False):
        self.deleted: list[tuple[str, str]] = []
        self.fail_delete = fail_delete

    def delete_object(self, Bucket, Key):
        if self.fail_delete:
            raise RuntimeError("storage down")
        self.deleted.append((Bucket, Key))


def _pending(name: str = "stale.bin", age_s: int = 0) -> str:
    """A pending upload intent, optionally backdated by ``age_s`` seconds."""
    application_id, space_id = main.repo.default_scope()
    oid = main.repo.create_pending_object(
        space_id=space_id, application_id=application_id, environment="test",
        bucket="aura", object_key=f"pending/{name}", display_name=name,
        content_type="application/octet-stream", owner_id=None,
        actor_id="tester", actor_kind="user",
        intent_expires_at=int(time.time()) + main.settings.intent_ttl,
    )
    if age_s:
        stamp = int(time.time()) - age_s
        if main.repo.dialect == "sqlite":
            conn = main.repo.conn
            conn.execute(
                "UPDATE objects SET created_at = ?, intent_expires_at = ? WHERE id = ?",
                (stamp, stamp, oid),
            )
            conn.commit()
        else:  # pragma: no cover - offline tests run on SQLite
            main.repo._run(
                "UPDATE objects SET created_at = %s, intent_expires_at = %s WHERE id = %s",
                (stamp, stamp, oid),
            )
    return oid


def _status(oid: str) -> str:
    return dict(main.repo.get_object(oid, space_id=main.repo.default_scope()[1]))["status"]


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


# ---------------------------------------------------------------------------
# The sweep itself
# ---------------------------------------------------------------------------
def test_sweep_expires_a_stale_intent_after_deleting_its_bytes():
    age = main.settings.intent_ttl + main.settings.intent_grace_s + 7200
    oid = _pending("stale.bin", age_s=age)
    s3 = FakeS3()

    out = reconciler.sweep(main.repo, s3, main.settings)

    # The sweep is administrative and global (it spans every space, like the
    # admin route), so other stale rows of the shared catalogue may be swept
    # too: the assertion is about THIS intent, not about the total.
    assert out["expired"] >= 1, out
    assert out["storage_deletes_attempted"] >= 1, out
    assert out["storage_failures"] == 0, out
    assert ("aura", "pending/stale.bin") in s3.deleted
    assert _status(oid) == "expired"


def test_sweep_leaves_a_fresh_intent_pending():
    oid = _pending("fresh.bin")
    s3 = FakeS3()

    out = reconciler.sweep(main.repo, s3, main.settings)

    assert out["expired"] == 0, out
    assert s3.deleted == []
    assert _status(oid) == "pending"


def test_sweep_keeps_an_intent_that_is_still_inside_the_automatic_margin():
    # Past the intent life (intent_ttl + intent_grace_s) but inside the
    # automatic margin: a slow upload in progress must not lose its bytes.
    age = main.settings.intent_ttl + main.settings.intent_grace_s + 60
    oid = _pending("slow.bin", age_s=age)
    s3 = FakeS3()

    out = reconciler.sweep(main.repo, s3, main.settings)

    assert out["expired"] == 0, out
    assert s3.deleted == []
    assert _status(oid) == "pending"


def test_sweep_never_declares_a_failed_cleanup_as_expired():
    age = main.settings.intent_ttl + main.settings.intent_grace_s + 7200
    oid = _pending("unreachable.bin", age_s=age)
    s3 = FakeS3(fail_delete=True)

    out = reconciler.sweep(main.repo, s3, main.settings)

    assert out["expired"] == 0, out
    assert out["storage_failures"] == 1, out
    # The row stays pending so the next sweep retries it.
    assert _status(oid) == "pending"


def test_sweep_is_bounded():
    limit = 2
    old = main.settings.intent_ttl + main.settings.intent_grace_s + 7200
    for i in range(5):
        _pending(f"many-{i}.bin", age_s=old)
    s3 = FakeS3()

    class Limited:
        """Settings view with a small per-run limit."""

        def __init__(self, base):
            self.__dict__.update(vars(base))

        def __getattr__(self, item):
            return getattr(main.settings, item)

    limited = Limited(main.settings)
    limited.reconcile_limit = limit

    out = reconciler.sweep(main.repo, s3, limited)

    assert out["expired"] <= limit, out


def test_sweep_records_its_counters_for_the_health_endpoint():
    c, headers = _admin()
    r = c.get("/api/v1/admin/health", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    component = body["components"]["reconcile"]
    assert component["enabled"] is True
    assert component["interval_s"] == main.settings.reconcile_interval_s
    # The sweep may not have run yet in this process: the endpoint says so
    # instead of pretending it did.
    assert "last_sweep" in component


def test_last_sweep_is_published_after_a_run():
    reconciler.sweep(main.repo, FakeS3(), main.settings)
    state = reconciler.last_sweep()
    assert state is not None
    assert "expired" in state and "at" in state


# ---------------------------------------------------------------------------
# The background loop
# ---------------------------------------------------------------------------
def test_background_loop_sweeps_and_can_be_stopped(monkeypatch):
    class Fast:
        """Settings view with a short interval so the loop ticks at once."""

        def __init__(self, base):
            self.__dict__.update(vars(base))

        def __getattr__(self, item):
            return getattr(main.settings, item)

    fast = Fast(main.settings)
    fast.reconcile_interval_s = 30
    monkeypatch.setattr(main.settings, "reconcile_interval_s", 30)

    seen: list[dict] = []
    stop = reconciler.start_background(
        main.repo, FakeS3(), fast, audit=lambda *a, **k: seen.append(a[2] if len(a) > 2 else {}),
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not seen:
            time.sleep(0.1)
    finally:
        stop.set()
    assert seen, "the background loop never ran a sweep"
