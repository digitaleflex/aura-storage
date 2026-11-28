"""Editorial cover policy: real artwork only for curated emblematic books."""
import os
import sqlite3
import uuid

import pytest

os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "testaccess12345678")
os.environ.setdefault("AURA_S3_SECRET_KEY", "testsecret45678901234567890123456789")
os.environ.setdefault("AURA_S3_ENDPOINT", "https://127.0.0.1:9")
os.environ.setdefault("AURA_API_DB", ":memory:")
os.environ.setdefault("AURA_API_BACKEND", "sqlite")
os.environ.setdefault("AURA_COOKIE_SECURE", "0")
os.environ.setdefault("AURA_AUDIT_LOG", "/tmp/opencode/aura-test-emblematic-audit.jsonl")
os.environ.setdefault("AURA_COVER_REVIEW_FILE", "/tmp/opencode/aura-emblematic-review.json")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import migrations, public_book, public_ui  # noqa: E402
from api.auth import hash_password  # noqa: E402
from api.db import SCHEMA  # noqa: E402


def _item(emblematic: bool = False) -> dict:
    return {
        "id": "book-1", "title": "Le Secret", "author": "Rhonda Byrne",
        "cover_url": "/covers/book-1.jpg", "emblematic_cover": emblematic,
        "duration_seconds": 3600, "chapters": [], "categories": [], "themes": [],
    }


def test_real_cover_is_gated_by_the_editorial_flag():
    plain = _item()
    curated = _item(emblematic=True)
    for html in (
        public_ui.hero_cover_html(plain),
        public_ui._track_html(plain),
        public_book._cover(plain),
        public_ui.carousel_shelf(
            {"slug": "series", "label": "Série", "items": [plain]},
            use_covers=True,
        ),
        public_book.book_page(plain, "", [], None, base_url="https://example.test"),
    ):
        assert "<img" not in html
    for html in (
        public_ui.hero_cover_html(curated),
        public_ui._track_html(curated),
        public_book._cover(curated),
        public_ui.carousel_shelf(
            {"slug": "series", "label": "Série", "items": [curated]},
            use_covers=True,
        ),
    ):
        assert "/covers/book-1.jpg" in html
    page = public_book.book_page(curated, "", [], None, base_url="https://example.test")
    assert 'property="og:image" content="https://example.test/covers/book-1.jpg"' in page
    assert 'name="twitter:image"' in page


def test_migration_defaults_the_flag_to_zero(tmp_path):
    apply_migrations = migrations.apply_migrations

    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "status, created_at, updated_at) VALUES ('o1', 'aura', 'a.mp3', 'A.mp3', "
        "'audio/mpeg', 'available', 1, 1)"
    )
    conn.commit()
    apply_migrations(conn, "sqlite")
    assert conn.execute(
        "SELECT emblematic_cover FROM objects WHERE id = 'o1'"
    ).fetchone()[0] == 0
    assert ("emblematic_cover", "INTEGER NOT NULL DEFAULT 0") in \
        migrations.ADDED_COLUMNS["objects"]


def _admin():
    username = f"emblematic-{uuid.uuid4().hex[:10]}"
    password = "emblematic-test-password"
    main.repo.create_user(username, hash_password(password), role="admin")
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/login", json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def test_emblematic_cover_endpoint_requires_admin_write_and_csrf():
    client, csrf = _admin()
    oid = str(uuid.uuid4())
    _application_id, space_id = main.repo.default_scope()
    # The suite also runs against PostgreSQL, whose driver does not accept the
    # SQLite ``?`` placeholder.
    placeholder = "?" if main.repo.dialect == "sqlite" else "%s"
    main.repo.conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "status, space_id, created_at, updated_at) VALUES "
        f"({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder}, 'available', {placeholder}, 1, 1)",
        (oid, "aura", f"{oid}.mp3", "Livre.mp3", "audio/mpeg", space_id),
    )
    main.repo.conn.commit()
    url = f"/api/v1/admin/objects/{oid}/emblematic-cover"

    assert TestClient(main.app).put(url, json={"emblematic": True}).status_code in (401, 403)
    assert client.put(url, json={"emblematic": True}).status_code == 403
    response = client.put(url, json={"emblematic": True, "extra": 1}, headers=csrf)
    assert response.status_code == 422

    enabled = client.put(url, json={"emblematic": True}, headers=csrf)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json() == {"id": oid, "emblematic_cover": True}
    assert main.repo.get_object_unscoped(oid)["emblematic_cover"] == 1

    disabled = client.put(url, json={"emblematic": False}, headers=csrf)
    assert disabled.json()["emblematic_cover"] is False
    assert main.repo.get_object_unscoped(oid)["emblematic_cover"] == 0
