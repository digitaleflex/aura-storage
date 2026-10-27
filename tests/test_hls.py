"""HLS jobs, playlist rewrite and linked WebVTT subtitles."""
import os
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-audit.jsonl")
os.environ.setdefault("AURA_M2M_RATE_LIMIT", "100000")
os.environ.setdefault("AURA_MEDIA_WORKER", "0")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api.auth import hash_password  # noqa: E402

client = TestClient(main.app)


class Body:
    def __init__(self, data): self.data = data
    def read(self): return self.data


class PlaylistS3:
    def get_object(self, Bucket, Key):
        return {"Body": Body(b"#EXTM3U\n#EXTINF:6.0,\nseg_00000.ts\n")}


@pytest.fixture(autouse=True)
def _reset_limiters():
    main.reset_login_attempts()
    yield
    main.reset_login_attempts()


def _admin():
    name = f"hls-{uuid.uuid4().hex[:10]}"
    main.repo.create_user(name, hash_password("hls-test-password"), role="admin")
    c = TestClient(main.app)
    r = c.post("/api/v1/login", json={"username": name, "password": "hls-test-password"})
    assert r.status_code == 200
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _object(c, headers, ctype="video/mp4", name="cours.mp4", size=1000):
    r = c.post("/api/v1/objects/upload-intents", json={
        "display_name": name, "size_bytes": size, "content_type": ctype,
    }, headers=headers)
    oid = r.json()["id"]
    main.repo.mark_available(oid, size, uuid.uuid4().hex)
    return oid


def test_hls_enqueue_and_status():
    c, headers = _admin()
    video = _object(c, headers)
    r = c.post(f"/api/v1/objects/{video}/hls", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["hls_status"] == "queued"
    status = c.get(f"/api/v1/objects/{video}/hls/status", headers=headers).json()
    assert status["status"] == "queued"
    job = main.repo.get_media_job(video, "hls")
    assert job and job["status"] == "queued"

    pdf = _object(c, headers, ctype="application/pdf", name="x.pdf")
    assert c.post(f"/api/v1/objects/{pdf}/hls", headers=headers).status_code == 422
    assert c.post(f"/api/v1/objects/{uuid.uuid4()}/hls", headers=headers).status_code == 404


def test_playlist_is_rewritten_for_auth_and_public(monkeypatch):
    c, headers = _admin()
    video = _object(c, headers)
    monkeypatch.setattr(main, "s3ops", PlaylistS3())
    main.repo.set_object_hls(video, "ready", "aura/test/cours.mp4.hls")

    auth = c.get(f"/api/v1/objects/{video}/hls/index.m3u8", headers=headers)
    assert auth.status_code == 200, auth.text
    assert f"/api/v1/objects/{video}/hls/seg_00000.ts" in auth.text
    assert auth.text.startswith("#EXTM3U")

    slug = f"hls-{uuid.uuid4().hex[:8]}"
    assert c.put(f"/api/v1/objects/{video}/publication",
                 json={"slug": slug, "published": True}, headers=headers).status_code == 200
    public = client.get(f"/hls/{slug}.m3u8")
    assert public.status_code == 200, public.text
    assert f"/hls/{slug}/seg_00000.ts" in public.text
    assert client.get(f"/hls/{slug}/../secret").status_code == 404


def test_subtitle_must_be_vtt_and_is_published_with_the_video():
    c, headers = _admin()
    video = _object(c, headers)
    vtt = _object(c, headers, ctype="text/vtt", name="fr.vtt", size=200)
    bad = _object(c, headers, ctype="text/plain", name="notes.txt", size=10)

    assert c.put(f"/api/v1/objects/{video}/subtitle",
                 json={"subtitle_object_id": bad}, headers=headers).status_code == 422
    r = c.put(f"/api/v1/objects/{video}/subtitle",
              json={"subtitle_object_id": vtt}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["subtitle"] is True

    slug = f"sub-{uuid.uuid4().hex[:8]}"
    assert c.put(f"/api/v1/objects/{video}/publication",
                 json={"slug": slug, "published": True}, headers=headers).status_code == 200
    sub = client.get(f"/m/{slug}/subtitles.vtt", follow_redirects=False)
    assert sub.status_code == 302
    assert "X-Amz-Signature=" in sub.headers["location"]
