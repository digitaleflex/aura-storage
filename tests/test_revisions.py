"""Content revisions — phase 1: schema and persistence only.

`docs/CONTENT-REVISIONS.md` phase 1 adds the table, the three additive columns on
`objects` and the repository methods. Nothing in the API creates, reads or purges a
revision yet, so these tests pin exactly that: the shape and the storage behaviour the
replace flow will build on, and no more.

Runs on a disposable SQLite file; no PostgreSQL, no S3.
"""
import sqlite3

import pytest

from api.db import Repository


def _repo(tmp_path):
    repo = Repository(str(tmp_path / "revisions.db"))
    now = repo.now()
    # Minimal rows: a revision needs an object (FK RESTRICT) which needs an owner.
    repo.conn.execute(
        "INSERT INTO users (id, username, pass_hash, created_at) VALUES (?, ?, ?, ?)",
        ("u1", "revision-owner", "not-a-real-hash", now),
    )
    repo.conn.execute(
        "INSERT INTO objects (id, bucket, object_key, display_name, content_type, "
        "owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("o1", "aura", "live-key", "live.pdf", "application/pdf", "u1", now, now),
    )
    repo.conn.commit()
    return repo


def test_roundtrip_persists_every_field(tmp_path):
    repo = _repo(tmp_path)
    rid = repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=1234, checksum_sha256="a" * 64, content_type="application/pdf",
        created_by_id="u1", created_by_kind="human", keep_forever=True,
    )
    row = repo.get_revision("o1", rid)
    assert row["object_id"] == "o1"
    assert row["revision_number"] == 1
    assert row["bucket"] == "aura"
    assert row["storage_key"] == "rev/1"
    assert row["size_bytes"] == 1234
    assert row["checksum_sha256"] == "a" * 64
    assert row["content_type"] == "application/pdf"
    assert row["created_by_id"] == "u1"
    assert row["created_by_kind"] == "human"
    assert row["keep_forever"] == 1
    assert row["purged_at"] is None


def test_listing_is_newest_generation_first(tmp_path):
    repo = _repo(tmp_path)
    for number in (1, 2, 3):
        repo.create_revision(
            object_id="o1", revision_number=number, bucket="aura",
            storage_key=f"rev/{number}", size_bytes=number, checksum_sha256="",
            content_type="application/pdf",
        )
    assert [r["revision_number"] for r in repo.list_revisions("o1")] == [3, 2, 1]
    assert repo.list_revisions("another-object") == []


def test_get_revision_is_scoped_to_its_object(tmp_path):
    repo = _repo(tmp_path)
    rid = repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    assert repo.get_revision("o1", rid) is not None
    # A revision id from another object must not be readable through this object.
    assert repo.get_revision("some-other-object", rid) is None


def test_generation_is_unique_per_object(tmp_path):
    """The replace flow derives the next generation from this constraint."""
    repo = _repo(tmp_path)
    repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/a",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_revision(
            object_id="o1", revision_number=1, bucket="aura", storage_key="rev/b",
            size_bytes=1, checksum_sha256="", content_type="application/pdf",
        )


def test_keep_forever_toggles_and_is_counted_per_owner(tmp_path):
    repo = _repo(tmp_path)
    first = repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    second = repo.create_revision(
        object_id="o1", revision_number=2, bucket="aura", storage_key="rev/2",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    assert repo.count_keep_forever("u1") == 0
    assert repo.set_revision_keep_forever(first, True) == 1
    assert repo.count_keep_forever("u1") == 1
    assert repo.set_revision_keep_forever(second, True) == 1
    assert repo.count_keep_forever("u1") == 2
    assert repo.set_revision_keep_forever(first, False) == 1
    assert repo.count_keep_forever("u1") == 1
    # Unknown owners and unknown revisions are not errors.
    assert repo.count_keep_forever("nobody") == 0
    assert repo.set_revision_keep_forever("no-such-revision", True) == 0


def test_deleting_a_revision_leaves_the_object_alone(tmp_path):
    repo = _repo(tmp_path)
    rid = repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    assert repo.delete_revision(rid) == 1
    assert repo.get_revision("o1", rid) is None
    assert repo.delete_revision(rid) == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM objects WHERE id = 'o1'").fetchone()[0] == 1


def test_deleting_an_object_with_revisions_is_refused(tmp_path):
    """ON DELETE RESTRICT is the guard phase 2 must work with, not around.

    SQLite only enforces foreign keys when the pragma is on, so the test turns it on
    explicitly: in production PostgreSQL enforces it unconditionally, and the purge
    path must therefore order its work instead of relying on a cascade.
    """
    repo = _repo(tmp_path)
    repo.create_revision(
        object_id="o1", revision_number=1, bucket="aura", storage_key="rev/1",
        size_bytes=1, checksum_sha256="", content_type="application/pdf",
    )
    repo.conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute("DELETE FROM objects WHERE id = 'o1'")
