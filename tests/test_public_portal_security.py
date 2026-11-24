"""Phase 0 du portail public : cache, fin de session, slugs restreints, débit.

Ces tests sont volontairement dans un fichier séparé de ``test_public_portal.py``
pour ne pas toucher aux travaux en cours sur ce dernier.
"""
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

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
from api.config import _csv_lower  # noqa: E402
from tests import catalogue_sql  # noqa: E402

OID = "11111111-2222-4333-8444-555555555555"
SLUG = "livre-phase0"
CATALOG = [{
    "id": "col-phase0",
    "title": "Un livre",
    "description": "Roman",
    "items": [{
        "id": OID,
        "title": "Chapitre 1",
        "author": "Auteur Test",
        "duration_seconds": 120,
        "chapters": [{"title": "Chapitre 1", "start": 0}],
    }],
}]


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    main.reset_login_attempts()
    monkeypatch.setattr(main.settings, "public_domain", "testserver")
    monkeypatch.setattr(main, "_public_catalog", lambda: CATALOG)
    # The book page now resolves a single pack directly (issue #299).
    monkeypatch.setattr(main.repo, "get_published_collections_for_object", lambda oid: [
        {"id": "col-phase0", "title": "Un livre", "updated_at": 0},
    ])
    monkeypatch.setattr(main, "_library_items", lambda col, only_published=False: CATALOG[0]["items"])
    monkeypatch.setattr(main.repo, "get_audio_chapters_map", lambda ids: {})
    monkeypatch.setattr(main.repo, "get_object_unscoped", lambda oid: {
        "id": oid, "status": "available", "published_at": int(time.time()),
        "public_slug": "livre-phase0", "bucket": "aura", "object_key": f"aura/{oid}",
        "space_id": main.repo.default_scope()[1], "content_type": "audio/mpeg",
        "size_bytes": 1000, "duration_seconds": 120,
        "display_name": "Auteur Test - Chapitre 1.mp3",
    })
    yield
    main.reset_login_attempts()


def test_anonymous_book_page_is_publicly_cacheable():
    r = TestClient(main.app).get(f"/livre/{OID}")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "public, max-age=60"
    assert r.headers["vary"] == "Cookie"


def test_personalised_book_page_is_never_cached(monkeypatch):
    monkeypatch.setattr(
        main, "authenticate_public",
        lambda request: {"id": "reader-1", "csrf": "csrf-token"},
    )
    r = TestClient(main.app).get(f"/livre/{OID}")
    assert r.status_code == 200, r.text
    assert "private" in r.headers["cache-control"]
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["vary"] == "Cookie"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert 'name="csrf-token"' in r.text


def test_restricted_slug_blocks_every_public_media_route(monkeypatch):
    # A restricted title must not resolve through its permanent URL, HLS
    # derivatives or VTT, even before the authentication/premium gate runs.
    monkeypatch.setattr(main.settings, "public_media_require_auth", True)
    monkeypatch.setattr(main.settings, "public_download_require_premium", True)
    monkeypatch.setattr(main.settings, "public_media_open_slugs", ())
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", (SLUG,))
    monkeypatch.setattr(
        main, "_require_premium",
        lambda request: pytest.fail("restricted media reached the session gate"),
    )
    monkeypatch.setattr(
        main.repo, "get_object_by_slug",
        lambda slug: pytest.fail("restricted media reached the catalogue lookup"),
    )
    client = TestClient(main.app)
    for path in (
        f"/m/{SLUG}",
        f"/d/{SLUG}",
        f"/hls/{SLUG}.m3u8",
        f"/hls/{SLUG}/seg_00000.ts",
        f"/m/{SLUG}/subtitles.vtt",
    ):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 404, (path, r.text)
        assert "location" not in r.headers


def test_public_slug_lists_are_normalized(monkeypatch):
    monkeypatch.setenv("AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS", " LIVRE-PAYANT , ,Autre ")
    monkeypatch.setenv("AURA_PUBLIC_MEDIA_OPEN_SLUGS", " COURS-PUBLIC ")
    assert _csv_lower("AURA_PUBLIC_MEDIA_RESTRICTED_SLUGS") == (
        "livre-payant", "autre",
    )
    assert _csv_lower("AURA_PUBLIC_MEDIA_OPEN_SLUGS") == ("cours-public",)


def _stub_public_video(monkeypatch):
    row = {
        "id": OID,
        "status": "available",
        "published_at": int(time.time()),
        "public_slug": SLUG,
        "bucket": "aura",
        "object_key": f"aura/{OID}",
        "space_id": main.repo.default_scope()[1],
        "content_type": "video/mp4",
        "size_bytes": 1000,
        "display_name": "Cours.mp4",
        "hls_prefix": f"aura/{OID}.hls",
        "subtitle_object_id": OID,
    }
    subtitle = {
        "id": OID,
        "status": "available",
        "bucket": "aura",
        "object_key": f"aura/{OID}.vtt",
    }
    monkeypatch.setattr(main.repo, "get_object_by_slug", lambda slug: row)
    monkeypatch.setattr(main.repo, "get_object_global", lambda oid: subtitle)
    monkeypatch.setattr(main, "_record_object_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "s3ops", SimpleNamespace(
        get_object=lambda **kwargs: {
            "Body": SimpleNamespace(read=lambda: b"#EXTM3U\n#EXTINF:6.0,\nseg_00000.ts\n"),
        },
    ))
    monkeypatch.setattr(
        main, "presigned_get",
        lambda *args, **kwargs: "https://media.invalid/signed",
    )


def test_public_media_derivatives_require_the_same_session_gate(monkeypatch):
    monkeypatch.setattr(main.settings, "public_media_require_auth", True)
    monkeypatch.setattr(main.settings, "public_download_require_premium", False)
    monkeypatch.setattr(main.settings, "public_media_open_slugs", ())
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", ())
    client = TestClient(main.app)
    for path in (
        f"/m/{SLUG}",
        f"/d/{SLUG}",
        f"/hls/{SLUG}.m3u8",
        f"/hls/{SLUG}/seg_00000.ts",
        f"/m/{SLUG}/subtitles.vtt",
    ):
        assert client.get(path, follow_redirects=False).status_code == 401, path


def test_signed_in_session_unlocks_streaming_and_all_derivatives(monkeypatch):
    _stub_public_video(monkeypatch)
    monkeypatch.setattr(main.settings, "public_media_require_auth", True)
    monkeypatch.setattr(main.settings, "public_download_require_premium", True)
    monkeypatch.setattr(main.settings, "public_media_open_slugs", ())
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", ())
    calls = []
    monkeypatch.setattr(
        main, "authenticate_public", lambda request: calls.append(request) or {}
    )
    client = TestClient(main.app)
    expected = {
        f"/m/{SLUG}": 302,
        f"/hls/{SLUG}.m3u8": 200,
        f"/hls/{SLUG}/seg_00000.ts": 302,
        f"/m/{SLUG}/subtitles.vtt": 302,
    }
    for path, status in expected.items():
        r = client.get(path, follow_redirects=False)
        assert r.status_code == status, (path, r.text)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
    assert len(calls) == len(expected)


def test_explicit_download_requires_premium_even_when_streaming_is_open(monkeypatch):
    _stub_public_video(monkeypatch)
    monkeypatch.setattr(main.settings, "public_media_require_auth", True)
    monkeypatch.setattr(main.settings, "public_download_require_premium", True)
    monkeypatch.setattr(main.settings, "public_media_open_slugs", ())
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", ())
    calls = []
    monkeypatch.setattr(main, "_require_premium", lambda request: calls.append(request) or {})
    client = TestClient(main.app)
    assert client.get(f"/d/{SLUG}", follow_redirects=False).status_code == 302
    assert len(calls) == 1


def test_allowlisted_slug_is_open_for_media_and_derivatives(monkeypatch):
    _stub_public_video(monkeypatch)
    monkeypatch.setattr(main.settings, "public_media_require_auth", True)
    monkeypatch.setattr(main.settings, "public_download_require_premium", True)
    monkeypatch.setattr(main.settings, "public_media_open_slugs", (SLUG,))
    monkeypatch.setattr(main.settings, "public_media_restricted_slugs", ())
    calls = []
    monkeypatch.setattr(main, "_require_premium", lambda request: calls.append(request) or {})
    client = TestClient(main.app)
    for path, status in {
        f"/m/{SLUG}": 302,
        f"/hls/{SLUG}.m3u8": 200,
        f"/hls/{SLUG}/seg_00000.ts": 302,
        f"/m/{SLUG}/subtitles.vtt": 302,
    }.items():
        assert client.get(path, follow_redirects=False).status_code == status, path
    # The embed exemption covers listening only, never the explicit download.
    assert calls == []
    assert client.get(f"/d/{SLUG}", follow_redirects=False).status_code == 302
    assert len(calls) == 1


def test_hls_and_subtitle_routes_are_rate_limited(monkeypatch):
    monkeypatch.setattr(main.settings, "public_media_require_auth", False)
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "hls", 2)
    monkeypatch.setitem(main._PUBLIC_RATE_LIMITS, "subtitle", 2)
    main.reset_login_attempts()
    client = TestClient(main.app)

    for path in (f"/hls/{SLUG}.m3u8", f"/m/{SLUG}/subtitles.vtt"):
        main.reset_login_attempts()
        assert client.get(path).status_code == 404  # slug inconnu, mais compté
        assert client.get(path).status_code == 404
        limited = client.get(path)
        assert limited.status_code == 429, limited.text
        assert limited.headers.get("retry-after")


def test_service_worker_forgets_pages_on_session_end():
    source = (Path(main.__file__).parent / "portal_assets" / "sw.js").read_text()
    assert "event.data.type === 'forget-pages'" in source
    assert "'/profil/supprimer'" in source
    assert "response.status === 401" in source


def test_rate_counters_are_shared_in_the_catalogue():
    main.reset_login_attempts()
    TestClient(main.app).get(f"/hls/{SLUG}.m3u8")
    row = catalogue_sql.fetch_one("SELECT COUNT(*) AS n FROM public_rate_counters")
    assert row["n"] >= 1
    main.reset_login_attempts()
    assert catalogue_sql.fetch_one("SELECT COUNT(*) AS n FROM public_rate_counters")["n"] == 0


def test_service_issued_media_grant_is_revocable(monkeypatch):
    monkeypatch.setattr(main.settings, "public_access_grant_ttl", 120)
    redirect_ttls = []

    def fake_presigned_get(s3, bucket, key, ttl, **kwargs):
        redirect_ttls.append(ttl)
        return "https://media.invalid/granted"

    monkeypatch.setattr(main, "presigned_get", fake_presigned_get)
    admin = TestClient(main.app)
    login = admin.post("/api/v1/login", json={
        "username": "admin", "password": os.environ["AURA_API_ADMIN_PASSWORD"],
    })
    assert login.status_code == 200, login.text
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    app_id, space_id = main.repo.default_scope()
    suffix = uuid.uuid4().hex[:10]
    writer = admin.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": f"grant-writer-{suffix}",
        "scopes": ["objects:write"],
    }, headers=headers)
    assert writer.status_code == 200, writer.text
    writer_auth = {"Authorization": f"Bearer {writer.json()['token']}"}
    identity = admin.post("/api/v1/admin/identities", json={
        "space_id": space_id, "name": f"grant-service-{suffix}",
        "scopes": ["objects:read", "objects:write"],
    }, headers=headers)
    assert identity.status_code == 200, identity.text
    service = {"Authorization": f"Bearer {identity.json()['token']}"}

    oid = main.repo.create_pending_object(
        space_id=space_id, application_id=app_id, environment="test",
        bucket="aura", object_key=f"aura/grant-{uuid.uuid4().hex}",
        display_name="Livre payant.mp3", content_type="audio/mpeg",
        owner_id=None, actor_id="tester", actor_kind="user",
        intent_expires_at=int(time.time()) + 900,
    )
    main.repo.mark_available(oid, 1000, "checksum")

    # An anonymous caller cannot mint a grant, and write-only cannot buy itself
    # read access by minting a public bearer grant.
    anon = TestClient(main.app)
    assert anon.post(f"/api/v1/objects/{oid}/public-access").status_code == 401
    assert admin.post(
        f"/api/v1/objects/{oid}/public-access", headers=writer_auth,
    ).status_code == 403
    assert admin.delete(
        f"/api/v1/objects/{oid}/public-access", headers=writer_auth,
    ).status_code == 403

    grant = admin.post(f"/api/v1/objects/{oid}/public-access", headers=service)
    assert grant.status_code == 200, grant.text
    token = grant.json()["token"]
    assert grant.json()["url"] == f"/a/{token}"

    redeem = anon.get(f"/a/{token}", follow_redirects=False)
    assert redeem.status_code == 302, redeem.text
    assert redeem.headers["cache-control"] == "no-store"
    assert redirect_ttls and 0 < redirect_ttls[0] <= 120

    revoked = admin.delete(f"/api/v1/objects/{oid}/public-access", headers=service)
    assert revoked.status_code == 200 and revoked.json()["revoked"] == 1
    assert anon.get(f"/a/{token}", follow_redirects=False).status_code == 404

    # This module shares the in-memory catalogue with the rest of the suite:
    # leave no object, grant or usage event behind for analytics/publication
    # tests that count rows globally.
    main.repo.revoke_public_access_grants_for_object(oid, int(time.time()))
    # A revoked grant still has an FK to the object: remove it physically in
    # the test catalogue before deleting the object (PostgreSQL enforces it).
    catalogue_sql.execute("DELETE FROM public_access_grants WHERE object_id = ?", (oid,))
    catalogue_sql.execute("DELETE FROM object_usage_monthly WHERE object_id = ?", (oid,))
    main.repo.delete_object_row(oid)


def test_expired_media_grant_never_reaches_storage(monkeypatch):
    monkeypatch.setattr(main.repo, "get_public_access_grant", lambda token_hash: {
        "object_id": OID,
        "actor_id": "service",
        "revoked_at": None,
        "expires_at": int(time.time()) - 1,
    })
    monkeypatch.setattr(
        main.repo, "get_object_unscoped",
        lambda oid: pytest.fail("expired grant reached the object lookup"),
    )
    r = TestClient(main.app).get("/a/expired", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers


def test_media_grant_redirect_is_capped_by_remaining_lifetime(monkeypatch):
    monkeypatch.setattr(main.repo, "get_public_access_grant", lambda token_hash: {
        "object_id": OID,
        "actor_id": "service",
        "revoked_at": None,
        "expires_at": int(time.time()) + 5,
    })
    ttls = []
    monkeypatch.setattr(
        main, "presigned_get",
        lambda *args, **kwargs: ttls.append(args[3]) or "https://media.invalid/signed",
    )
    monkeypatch.setattr(main, "_record_object_event", lambda *args, **kwargs: None)
    r = TestClient(main.app).get("/a/nearly-expired", follow_redirects=False)
    assert r.status_code == 302
    assert ttls and 1 <= ttls[0] <= 5


def test_media_grant_expiring_during_lookup_is_not_presigned(monkeypatch):
    grant = {
        "object_id": OID,
        "actor_id": "service",
        "revoked_at": None,
        "expires_at": int(time.time()) + 10,
    }
    row = {
        "id": OID,
        "status": "available",
        "bucket": "aura",
        "object_key": f"aura/{OID}",
        "space_id": main.repo.default_scope()[1],
        "content_type": "audio/mpeg",
        "size_bytes": 1000,
        "display_name": "Livre.mp3",
    }
    monkeypatch.setattr(main.repo, "get_public_access_grant", lambda token_hash: grant)

    def slow_lookup(oid):
        grant["expires_at"] = int(time.time())
        return row

    monkeypatch.setattr(main.repo, "get_object_unscoped", slow_lookup)
    monkeypatch.setattr(
        main, "presigned_get",
        lambda *args, **kwargs: pytest.fail("expired grant was presigned"),
    )
    r = TestClient(main.app).get("/a/slow-lookup", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers


def test_fractional_time_does_not_extend_a_media_grant(monkeypatch):
    now = 1_800_000_000.9
    monkeypatch.setattr(main.time, "time", lambda: now)
    monkeypatch.setattr(main.repo, "get_public_access_grant", lambda token_hash: {
        "object_id": OID,
        "actor_id": "service",
        "revoked_at": None,
        "expires_at": int(now) + 2,
    })
    monkeypatch.setattr(main.repo, "get_object_unscoped", lambda oid: {
        "id": OID,
        "status": "available",
        "bucket": "aura",
        "object_key": f"aura/{OID}",
        "space_id": main.repo.default_scope()[1],
        "content_type": "audio/mpeg",
        "size_bytes": 1000,
        "display_name": "Livre.mp3",
    })
    monkeypatch.setattr(
        main, "presigned_get",
        lambda *args, **kwargs: pytest.fail("fractional grant was over-extended"),
    )
    r = TestClient(main.app).get("/a/fractional", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers
