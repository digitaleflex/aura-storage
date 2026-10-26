"""PostgreSQL parity — opt-in, runs only against a real PostgreSQL.

The default test suite is offline and SQLite-only (`AURA_API_DB=:memory:`); the
PostgreSQL repository (`api/db_pg.py`) is therefore *not* exercised by default. This
module closes that gap: point ``AURA_TEST_PG_DSN`` at a **disposable** database and
it creates its own rows, checks schema bootstrap + folder listing + the folder filter
+ the object->folder move, then removes exactly the rows it created.

    AURA_TEST_PG_DSN=postgresql://aura:secret@127.0.0.1:5432/aura_ci \\
        python -m pytest tests/test_pg_parity.py

Without the variable the module is skipped, so CI and local runs stay green and
hermetic. It is a parity check of the catalogue layer, not a deployment test.
"""
import os
import uuid

import pytest

DSN = os.environ.get("AURA_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set AURA_TEST_PG_DSN to a disposable PostgreSQL to run the parity suite",
)


def test_postgres_repository_parity():
    pytest.importorskip("psycopg")
    from api.db_pg import Repository  # imported lazily: needs psycopg

    repo = Repository(DSN)
    application_id, space_id = repo.default_scope()
    assert space_id, "migrations must seed the default space"

    username = f"pg-{uuid.uuid4().hex[:12]}"
    uid = repo.create_user(username, "not-a-real-hash", role="user", space_id=space_id)
    try:
        tag = uuid.uuid4().hex[:8]
        root = repo.create_folder(uid, f"root-{tag}")
        child = repo.create_folder(uid, f"child-{tag}", parent_id=root)

        # Flat listing returns the whole tree; per-level listing is unchanged.
        by_id = {f["id"]: f for f in repo.list_all_folders(owner_id=uid)}
        assert by_id[root]["parent_id"] is None
        assert by_id[child]["parent_id"] == root
        assert {f["id"] for f in repo.list_folders(owner_id=uid)} == {root}
        assert {f["id"] for f in repo.list_folders(owner_id=uid, parent_id=root)} == {child}

        # A pending object filed into the folder is returned by that folder's filter
        # and excluded from the "unfiled" (empty-string) filter.
        bucket = repo.get_default_bucket(space_id)["name"]
        oid = repo.create_pending_object(
            space_id=space_id, application_id=application_id, environment="prod",
            bucket=bucket, object_key=f"aura/{space_id}/{uid}/{uuid.uuid4().hex}",
            display_name="pg.txt", content_type="text/plain",
            owner_id=uid, actor_id=uid, actor_kind="user",
            intent_expires_at=None, folder_id=root,
        )
        filed = {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, folder_id=root)}
        unfiled = {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, folder_id="")}
        assert oid in filed and oid not in unfiled

        # The object->folder move (#62 follow-up) round-trips on PostgreSQL.
        repo.set_object_folder(oid, folder_id=None)
        row = repo.get_object(oid, space_id=space_id, owner_id=uid)
        assert row is not None and row["folder_id"] is None

        # M02: the search/filter/sort grammar behaves identically on PostgreSQL.
        second = repo.create_pending_object(
            space_id=space_id, application_id=application_id, environment="prod",
            bucket=bucket, object_key=f"aura/{space_id}/{uid}/{uuid.uuid4().hex}",
            display_name="Report.PDF", content_type="application/pdf",
            owner_id=uid, actor_id=uid, actor_kind="user",
            intent_expires_at=None, folder_id=None,
        )
        repo.mark_available(second, 2048, uuid.uuid4().hex)

        assert [o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, q="report")] == [second]
        # "%" is a literal, not a LIKE wildcard.
        assert repo.list_objects(space_id=space_id, owner_id=uid, q="%") == []
        assert {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, content_type="APPLICATION/PDF")} == {second}
        assert second in {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, status="available")}
        assert oid in {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, status="pending")}
        assert second in {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, min_size=1000)}
        assert second not in {o["id"] for o in repo.list_objects(
            space_id=space_id, owner_id=uid, max_size=100)}
        asc = repo.list_objects(
            space_id=space_id, owner_id=uid, sort="display_name", order="asc")
        assert [o["display_name"] for o in asc] == ["pg.txt", "Report.PDF"]

        # Counts the folder-delete guard relies on.
        assert repo.folder_child_count(root, owner_id=uid) == 1
        assert repo.folder_object_count(root, owner_id=uid) == 0

        # Content revisions (docs/CONTENT-REVISIONS.md, phase 1): the PostgreSQL
        # twin must behave exactly like SQLite. Nothing in the API uses these yet.
        rid = repo.create_revision(
            object_id=second, revision_number=1, bucket=bucket,
            storage_key=f"aura/{space_id}/{uid}/rev/1", size_bytes=2048,
            checksum_sha256="b" * 64, content_type="application/pdf",
            created_by_id=uid, created_by_kind="human",
        )
        rev = repo.get_revision(second, rid)
        assert rev["object_id"] == second and rev["revision_number"] == 1
        assert rev["keep_forever"] == 0 and rev["purged_at"] is None
        assert [r["revision_number"] for r in repo.list_revisions(second)] == [1]
        assert repo.get_revision(oid, rid) is None  # scoped to its own object
        assert repo.count_keep_forever(uid) == 0
        assert repo.set_revision_keep_forever(rid, True) == 1
        assert repo.count_keep_forever(uid) == 1
        assert repo.set_revision_keep_forever(rid, False) == 1
        assert repo.count_keep_forever(uid) == 0
        # The generation is unique per object: the replace flow depends on it.
        with pytest.raises(Exception):
            repo.create_revision(
                object_id=second, revision_number=1, bucket=bucket,
                storage_key=f"aura/{space_id}/{uid}/rev/dup", size_bytes=1,
                checksum_sha256="", content_type="application/pdf",
            )
        assert repo.delete_revision(rid) == 1
        assert repo.get_revision(second, rid) is None
    finally:
        # Remove only what this test created; the database is disposable.
        with repo.conn.cursor() as cur:
            # Revisions first: object_id is ON DELETE RESTRICT by design, so the
            # object cleanup below would otherwise be refused.
            cur.execute(
                "DELETE FROM object_revisions WHERE object_id IN "
                "(SELECT id FROM objects WHERE owner_id = %s)", (uid,)
            )
            cur.execute("DELETE FROM objects WHERE owner_id = %s", (uid,))
            cur.execute("DELETE FROM folders WHERE owner_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
