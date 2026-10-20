"""M07 — audit search, quotas/usage and supervision.

Offline (SQLite catalogue, stubbed S3 ops where a real storage call would be
made). Covers: request-id correlation, audit permissions, filters,
pagination, empty history, dependency failures, secret hygiene, real usage
values, retention pruning and tenant attribution.
"""
import json
import os
import time
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from tests import catalogue_sql  # noqa: E402
from api import authz  # noqa: E402
from api.auth import hash_password  # noqa: E402
from api.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_audit_log(monkeypatch, tmp_path):
    """Redirect the audit log per test and reset the auth limiters."""
    monkeypatch.setenv("AURA_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    main.reset_login_attempts()
    authz.reset_m2m_attempts()
    yield
    main.reset_login_attempts()
    authz.reset_m2m_attempts()


def _admin():
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _login(username, password):
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _make_app_space(c, headers):
    suffix = uuid.uuid4().hex[:8]
    r = c.post("/api/v1/admin/applications", json={"name": f"m07-app-{suffix}"},
               headers=headers)
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    r = c.post("/api/v1/admin/spaces", json={
        "application_id": app_id, "name": f"m07-space-{suffix}",
        "environment": "test",
    }, headers=headers)
    assert r.status_code == 200, r.text
    return app_id, r.json()["id"], r.json()["bucket"]


def _make_identity(c, headers, space_id, scopes, name="m07-svc"):
    r = c.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": f"{name}-{uuid.uuid4().hex[:6]}",
        "scopes": scopes,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _svc(token):
    return {"Authorization": f"Bearer {token}"}


def _user_with_role(role):
    name = f"m07-{role}-{uuid.uuid4().hex[:8]}"
    password = "m07-password-123"
    app_id, space_id = main.repo.default_scope()
    main.repo.create_user(name, hash_password(password), role=role,
                         space_id=space_id, application_id=app_id)
    return name, password


def _audit_log_lines():
    """Raw log entries: parsed dicts, or the raw string when unparsable."""
    path = os.environ["AURA_AUDIT_LOG"]
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                entries.append(line)
    return entries


FULL = ["objects:read", "objects:write", "objects:delete", "objects:purge"]


# ---------------------------------------------------------------------------
# Request correlation.
# ---------------------------------------------------------------------------
def test_m07_request_id_echoed_and_audited():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]

    r = c.post("/api/v1/objects/upload-intents",
               json={"display_name": "corr.bin", "size_bytes": 1},
               headers={**_svc(token), "X-Request-Id": "m07-client-1"})
    assert r.status_code == 200, r.text
    assert r.headers["x-request-id"] == "m07-client-1"

    found = c.get("/api/v1/admin/audit",
                  params={"request_id": "m07-client-1", "action": "upload-intent"},
                  headers=headers)
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["total"] == 1
    assert body["items"][0]["request_id"] == "m07-client-1"

    # An unsafe client value is replaced by a server-minted id, never refused.
    # (Fresh client: the admin client still holds its session cookie.)
    r = TestClient(main.app).get("/api/v1/me", headers={"X-Request-Id": "bad id"})
    assert r.status_code == 401  # no credential on this path
    assert r.headers["x-request-id"] and r.headers["x-request-id"] != "bad id"


# ---------------------------------------------------------------------------
# Permissions on the observability surface.
# ---------------------------------------------------------------------------
def test_m07_observability_permissions():
    c, headers = _admin()
    name, password = _user_with_role("user")
    u, uh = _login(name, password)
    oname, opwd = _user_with_role("operator")
    o, oh = _login(oname, opwd)
    _, space, _ = _make_app_space(c, headers)
    svc = _svc(_make_identity(c, headers, space, FULL)["token"])
    anon = TestClient(main.app)

    for path in ("/api/v1/admin/audit", "/api/v1/admin/usage",
                 "/api/v1/admin/health"):
        assert anon.get(path).status_code in (401, 403)
        assert u.get(path, headers=uh).status_code == 403
        assert c.get(path, headers=svc).status_code == 403
        assert c.get(path, headers=headers).status_code == 200
        # Operator holds admin:read: reads pass...
        assert o.get(path, headers=oh).status_code == 200
    # ... but retention pruning stays admin:write.
    assert anon.post("/api/v1/admin/audit/prune").status_code in (401, 403)
    assert u.post("/api/v1/admin/audit/prune", headers=uh).status_code == 403
    assert o.post("/api/v1/admin/audit/prune", headers=oh).status_code == 403
    assert c.post("/api/v1/admin/audit/prune", headers=svc).status_code == 403
    assert c.post("/api/v1/admin/audit/prune", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# Filters, pagination, empty history, bad parameters.
# ---------------------------------------------------------------------------
def test_m07_audit_filters_and_pagination():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]
    for i in range(3):
        r = c.post("/api/v1/objects/upload-intents",
                   json={"display_name": f"page-{i}.bin", "size_bytes": 1},
                   headers=_svc(token))
        assert r.status_code == 200, r.text
    # A failed login is auditable by actor substring and result.
    bad = TestClient(main.app).post(
        "/api/v1/login", json={"username": "nobody-here", "password": "x"})
    assert bad.status_code == 401

    def search(**params):
        r = c.get("/api/v1/admin/audit", params=params, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    intents = search(action="upload-intent")
    assert intents["total"] >= 3
    assert all(i["action"] == "upload-intent" for i in intents["items"])
    assert intents["truncated"] is False

    failures = search(result="failure", actor="nobody-here")
    assert failures["total"] >= 1
    assert all(i["result"] == "failure" for i in failures["items"])

    by_space = search(space_id=space, action="upload-intent")
    assert by_space["total"] >= 3

    page1 = search(action="upload-intent", limit=2, offset=0)
    page2 = search(action="upload-intent", limit=2, offset=2)
    assert len(page1["items"]) == 2 and len(page2["items"]) >= 1
    assert page1["items"][0]["ts"] >= page1["items"][1]["ts"]  # newest first
    assert {i["object_id"] for i in page1["items"]} & \
        {i["object_id"] for i in page2["items"]} == set()

    now = int(time.time())
    assert search(since=now - 3600)["total"] >= 1
    assert search(until=0)["total"] == 0
    assert search(action="no-such-action")["items"] == []

    assert c.get("/api/v1/admin/audit", params={"space_id": "not-a-uuid"},
                 headers=headers).status_code == 422
    assert c.get("/api/v1/admin/audit",
                 params={"since": now, "until": now - 10},
                 headers=headers).status_code == 422


def test_m07_missing_audit_file_is_empty_history(monkeypatch):
    c, headers = _admin()
    monkeypatch.setenv("AURA_AUDIT_LOG", "/tmp/opencode/m07-does-not-exist.jsonl")
    r = c.get("/api/v1/admin/audit", headers=headers)
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["total"] == 0


# ---------------------------------------------------------------------------
# Secret hygiene of everything observability exposes.
# ---------------------------------------------------------------------------
def test_m07_observability_never_discloses_secrets():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    created = _make_identity(c, headers, space, FULL)
    token = created["token"]
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"display_name": "sec.bin", "size_bytes": 1},
                 headers=_svc(token)).json()["id"]
    main.repo.mark_available(oid, 1, "abc")
    c.post(f"/api/v1/objects/{oid}/download-intent", headers=_svc(token))

    raw = open(os.environ["AURA_AUDIT_LOG"], encoding="utf-8").read()
    assert token not in raw
    assert token.rsplit("_", 1)[1] not in raw
    assert "X-Amz-Signature" not in raw
    assert "upload_url" not in raw and "download_url" not in raw
    for record in _audit_log_lines():
        assert {"ts", "actor", "action", "result"} <= set(record)

    for path in ("/api/v1/admin/audit?limit=100", "/api/v1/admin/health",
                 "/api/v1/admin/usage"):
        body = c.get(path, headers=headers).text
        assert token not in body
        assert "secret_hash" not in body
        assert "X-Amz-Signature" not in body


# ---------------------------------------------------------------------------
# Real usage values.
# ---------------------------------------------------------------------------
def test_m07_usage_reports_real_values():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]
    h = _svc(token)
    oid = c.post("/api/v1/objects/upload-intents",
                 json={"display_name": "bytes.bin", "size_bytes": 1},
                 headers=h).json()["id"]
    main.repo.mark_available(oid, 42, "abc")
    c.post("/api/v1/objects/upload-intents",
           json={"display_name": "pending.bin", "size_bytes": 1}, headers=h)

    before = int(time.time())
    r = c.get("/api/v1/admin/usage", params={"space_id": space}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert abs(body["measured_at"] - before) <= 10
    assert body["limits"]["max_object_bytes"] == settings.max_object_bytes
    assert body["limits"]["max_pending_intents"] == settings.max_pending_intents
    (entry,) = body["spaces"]
    assert entry["space_id"] == space
    assert entry["stored_bytes"] == 42
    assert entry["available_count"] == 1
    assert entry["pending_count"] >= 1

    everything = c.get("/api/v1/admin/usage", headers=headers).json()
    assert everything["totals"]["stored_bytes"] >= 42

    assert c.get("/api/v1/admin/usage", params={"space_id": "not-a-uuid"},
                 headers=headers).status_code == 422
    assert c.get(
        "/api/v1/admin/usage",
        params={"space_id": "00000000-0000-4000-8000-000000000000"},
        headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Supervision: components, degraded storage, recent errors.
# ---------------------------------------------------------------------------
def test_m07_health_reports_components_and_degraded_storage():
    c, headers = _admin()
    # A failed login inside the error window must surface as a recent error.
    TestClient(main.app).post(
        "/api/v1/login", json={"username": "ghost", "password": "x"})

    r = c.get("/api/v1/admin/health", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Offline the S3 endpoint is unreachable: honestly degraded, never an
    # exception or a fake "ok".
    assert body["status"] == "degraded"
    assert body["components"]["api"]["status"] == "ok"
    assert body["components"]["api"]["uptime_s"] >= 0
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["storage"]["status"] == "down"
    assert body["components"]["storage"]["error"] == "unreachable"
    assert "127.0.0.1" not in r.text and "seaweed" not in r.text.lower()
    disk = body["components"]["disk"]
    assert disk["status"] == "ok" and disk["free_bytes"] > 0
    # No invented object-store capacity figures, only local disk bytes.
    assert "capacity_bytes" not in r.text and "capacity_pct" not in r.text
    errors = body["recent_errors"]
    assert errors["window_s"] == settings.audit_error_window_s
    assert any(e["result"] == "failure" for e in errors["events"])
    assert all(set(e) <= {"ts", "action", "actor", "result", "request_id"}
               for e in errors["events"])


def test_m07_health_ok_when_dependencies_answer(monkeypatch):
    class HealthyS3:
        def list_buckets(self):
            return {"Buckets": []}

    monkeypatch.setattr(main, "s3ops", HealthyS3())
    c, headers = _admin()
    body = c.get("/api/v1/admin/health", headers=headers).json()
    assert body["status"] == "ok"
    assert body["components"]["storage"]["status"] == "ok"
    assert "latency_ms" in body["components"]["storage"]


# ---------------------------------------------------------------------------
# Retention pruning.
# ---------------------------------------------------------------------------
def test_m07_prune_enforces_retention_window():
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]
    c.post("/api/v1/objects/upload-intents",
           json={"display_name": "fresh.bin", "size_bytes": 1},
           headers=_svc(token))
    path = os.environ["AURA_AUDIT_LOG"]
    old = {"ts": int(time.time()) - 100 * 86400, "actor": "old",
           "action": "upload-intent", "result": "success"}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(old) + "\n")
        fh.write("not-json-at-all\n")

    r = c.post("/api/v1/admin/audit/prune", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dropped"] == 1
    assert body["retention_days"] == settings.audit_retention_days
    assert body["kept"] >= 2  # fresh event + prune event + timestamp-less line

    remaining = _audit_log_lines()
    assert all(
        not isinstance(rec, dict) or rec.get("ts", 0) >= body["cutoff"]
        for rec in remaining
    )
    # The timestamp-less line is conservatively kept.
    assert any(rec == "not-json-at-all" for rec in remaining
               if isinstance(rec, str))


# ---------------------------------------------------------------------------
# Tenant attribution of audit events.
# ---------------------------------------------------------------------------
def test_m07_audit_events_carry_tenant_and_request():
    c, headers = _admin()
    app_a, space_a, _ = _make_app_space(c, headers)
    _, space_b, _ = _make_app_space(c, headers)
    token_a = _make_identity(c, headers, space_a, FULL)["token"]
    c.post("/api/v1/objects/upload-intents",
           json={"display_name": "tenant.bin", "size_bytes": 1},
           headers=_svc(token_a))

    def search(**params):
        r = c.get("/api/v1/admin/audit", params=params, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    mine = search(space_id=space_a, action="upload-intent")
    assert mine["total"] >= 1
    assert all(i["application_id"] == app_a for i in mine["items"]
               if "application_id" in i)
    assert search(space_id=space_b, action="upload-intent",
                  actor=token_a)["total"] == 0

    # Pre-authentication events correlate by request id but carry no tenant.
    failed = TestClient(main.app).post(
        "/api/v1/login", json={"username": "ghost-tenant", "password": "x"})
    rid = failed.headers["x-request-id"]
    assert rid
    events = search(request_id=rid)["items"]
    assert len(events) == 1
    assert "space_id" not in events[0] and "application_id" not in events[0]


# ---------------------------------------------------------------------------
# Review follow-ups: middleware coverage, window semantics, clamps,
# attribution isolation, whitelist contract, prune concurrency.
# ---------------------------------------------------------------------------
def test_m07_request_id_present_on_error_responses():
    c, headers = _admin()
    # 404 with a request id: unknown object, authenticated caller.
    r = c.get("/api/v1/objects/00000000-0000-4000-8000-000000000000",
              headers=headers)
    assert r.status_code == 404
    assert r.headers["x-request-id"]
    # 403 with a request id: valid session, forbidden admin route.
    name, password = _user_with_role("user")
    u, uh = _login(name, password)
    r = u.get("/api/v1/admin/stats", headers=uh)
    assert r.status_code == 403
    assert r.headers["x-request-id"]


def test_m07_truncated_window_semantics():
    from api.audit import query_audit_log
    for i in range(5):
        c, headers = _admin()
        c.post("/api/v1/objects/upload-intents",
               json={"display_name": f"win-{i}.bin", "size_bytes": 1},
               headers=headers)
    out = query_audit_log(action="upload-intent", limit=100, offset=0,
                          max_scan_lines=3)
    assert out["scanned"] == 3
    assert out["truncated"] is True
    assert out["total"] <= 3
    full = query_audit_log(action="upload-intent", limit=100, offset=0)
    assert full["truncated"] is False
    assert full["total"] >= out["total"]


def test_m07_audit_pagination_clamp_edges():
    c, headers = _admin()

    def search(**params):
        r = c.get("/api/v1/admin/audit", params=params, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    assert len(search(limit=0)["items"]) <= 1  # clamped to limit=1
    huge = search(limit=99999)
    assert len(huge["items"]) <= 500  # clamped to limit=500
    assert search(offset=10 ** 9)["items"] == []
    assert search(action="no-such-action", limit=0)["total"] == 0


def test_m07_audit_attribution_isolated_across_threads():
    import threading
    from api.audit import (audit_event, bind_request_context,
                           reset_request_context, set_request_principal)
    seen: dict = {}

    def emit(tag, space):
        holder, token = bind_request_context(f"rid-{tag}")
        try:
            set_request_principal(space, f"app-{tag}")
            audit_event("m07.probe", f"actor-{tag}", "success")
            seen[tag] = dict(holder)
        finally:
            reset_request_context(token)

    threads = [threading.Thread(target=emit, args=(f"t{i}", f"space-{i}"))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i in range(8):
        assert seen[f"t{i}"]["request_id"] == f"rid-t{i}"
        assert seen[f"t{i}"]["space_id"] == f"space-{i}"


def test_m07_audit_whitelist_and_explicit_scope_win():
    import threading
    from api.audit import (audit_event, bind_request_context,
                           reset_request_context, set_request_principal)
    holder, token = bind_request_context("rid-white")
    try:
        set_request_principal("ambient-space", "ambient-app")
        audit_event("m07.probe", "actor", "success", {
            "ok_id": "x", "count": 3, "flag": True, "nothing": None,
            "nested": {"a": 1}, "items": [1, 2],
            "space_id": "explicit-space",
        })
    finally:
        reset_request_context(token)
    records = [r for r in _audit_log_lines() if isinstance(r, dict)
               and r.get("request_id") == "rid-white"]
    assert len(records) == 1
    rec = records[0]
    assert rec["ok_id"] == "x" and rec["count"] == 3
    assert "nested" not in rec and "items" not in rec
    assert rec["space_id"] == "explicit-space"  # explicit wins
    assert rec["application_id"] == "ambient-app"


def test_m07_prune_preserves_concurrent_appends():
    import threading
    from api.audit import audit_event
    c, headers = _admin()
    stop = threading.Event()
    errors: list = []

    def writer(n):
        try:
            for i in range(20):
                audit_event("m07.writer", f"w-{n}", "success", {"n": i})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    r = c.post("/api/v1/admin/audit/prune", headers=headers)
    for t in threads:
        t.join()
    assert r.status_code == 200, r.text
    assert not errors
    kept = [rec for rec in _audit_log_lines()
            if isinstance(rec, dict) and rec.get("action") == "m07.writer"]
    assert len(kept) == 80


# ---------------------------------------------------------------------------
# #87 follow-ups: orphan candidates (read-only) and bounded reconcile.
# ---------------------------------------------------------------------------
def test_m07_orphan_candidates_are_read_only(monkeypatch):
    from api import authz as _authz

    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]
    h = _svc(token)
    healthy_oid = c.post("/api/v1/objects/upload-intents",
                         json={"display_name": "whole.bin", "size_bytes": 1},
                         headers=h).json()["id"]
    main.repo.mark_available(healthy_oid, 1, "abc")
    missing_oid = c.post("/api/v1/objects/upload-intents",
                         json={"display_name": "ghost.bin", "size_bytes": 1},
                         headers=h).json()["id"]
    main.repo.mark_available(missing_oid, 1, "def")

    class SelectiveS3:
        def head_object(self, Bucket, Key):
            row = main.repo.get_object(missing_oid, space_id=space,
                                       owner_id=None)
            if row is not None and Key == dict(row)["object_key"]:
                raise RuntimeError("NoSuchKey")
            return {"ContentLength": 1}

        def list_buckets(self):
            return {"Buckets": []}

    monkeypatch.setattr(main, "s3ops", SelectiveS3())
    r = c.get("/api/v1/admin/orphans", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] >= 2
    ids = {item["id"] for item in body["candidates"]}
    assert missing_oid in ids and healthy_oid not in ids
    # Read-only: both rows are untouched and still downloadable in principle.
    assert c.get(f"/api/v1/objects/{missing_oid}",
                 headers=h).json()["status"] == "available"

    # Permissions mirror the other observability reads.
    anon = TestClient(main.app)
    assert anon.get("/api/v1/admin/orphans").status_code in (401, 403)
    name, password = _user_with_role("user")
    u, uh = _login(name, password)
    assert u.get("/api/v1/admin/orphans", headers=uh).status_code == 403
    assert c.get("/api/v1/admin/orphans",
                 headers=h).status_code == 403  # service: no admin:read


def test_m07_reconcile_sweep_is_bounded(monkeypatch):
    c, headers = _admin()
    _, space, _ = _make_app_space(c, headers)
    token = _make_identity(c, headers, space, FULL)["token"]
    oids = [c.post("/api/v1/objects/upload-intents",
                   json={"display_name": f"stale-{i}.bin", "size_bytes": 1},
                   headers=_svc(token)).json()["id"] for i in range(3)]
    for oid in oids:
        catalogue_sql.execute(
            "UPDATE objects SET created_at = ? WHERE id = ?",
            (main.repo.now() - 7200, oid),
        )

    class HealthyS3:
        def delete_object(self, Bucket, Key):
            return {}

    monkeypatch.setattr(main, "s3ops", HealthyS3())
    first = c.post("/api/v1/admin/reconcile", params={"limit": 2},
                   headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["expired"] == 2
    second = c.post("/api/v1/admin/reconcile", headers=headers)
    assert second.json()["expired"] == 1


def test_m07_reconcile_uses_the_derived_intent_window(monkeypatch):
    # The sweep window must be derived from the same settings that govern intent
    # death (intent_ttl + intent_grace_s), never reconcile_pending's own default:
    # otherwise a commit arriving inside the grace window could be swept out from
    # under the uploader.
    c, headers = _admin()
    captured = {}

    def _spy(repo_, s3_, *, expire_after_s, limit, multipart_expired_before):
        captured["expire_after_s"] = expire_after_s
        captured["limit"] = limit
        # A multipart session (#72) is only swept after its own expiry + grace.
        captured["multipart_expired_before"] = multipart_expired_before
        return {"expired": 0, "storage_deletes_attempted": 0, "storage_failures": 0}

    monkeypatch.setattr(main, "reconcile_pending", _spy)
    r = c.post("/api/v1/admin/reconcile", headers=headers)
    assert r.status_code == 200, r.text
    assert captured["expire_after_s"] == (
        main.settings.intent_ttl + main.settings.intent_grace_s
    )
    assert captured["multipart_expired_before"] <= int(time.time()) - main.settings.intent_grace_s
