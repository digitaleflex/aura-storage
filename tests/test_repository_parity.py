"""Offline parity guard for the two catalogue backends.

``tests/test_pg_parity.py`` needs a real PostgreSQL (opt-in via
``AURA_TEST_PG_DSN``) and is therefore skipped in the default, hermetic suite.
This module closes the *interface* half of that gap with **no database at all**:
it imports both repository classes and asserts that every public method exists on
both backends with an identical signature.

That catches the common drift — a column/method added to ``api/db.py`` (SQLite)
but forgotten in ``api/db_pg.py`` (PostgreSQL) or vice-versa, which is exactly
the risk of the M03 transfer-engine columns. It does **not** validate the SQL
dialect; that remains ``test_pg_parity.py`` against a disposable database.
"""
import inspect

import pytest

# If psycopg is unavailable the PostgreSQL module cannot be imported; skip rather
# than fail, so an environment without the driver still runs the rest of the suite.
pytest.importorskip("psycopg")

from api.db import Repository as SqliteRepository  # noqa: E402
from api.db_pg import Repository as PostgresRepository  # noqa: E402


def _public_signatures(cls) -> dict[str, str]:
    """Public method name -> its parameter list (return annotation excluded).

    Backends legitimately differ in the *return type* (SQLite yields
    ``sqlite3.Row``, PostgreSQL yields ``dict``); only the callable contract —
    the parameter names, kinds and defaults — must match.
    """
    signatures: dict[str, str] = {}
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        parameters = inspect.signature(member).parameters
        signatures[name] = ", ".join(
            f"{param.name}:{param.kind.name}={param.default!r}"
            if param.default is not inspect.Parameter.empty
            else f"{param.name}:{param.kind.name}"
            for param in parameters.values()
        )
    return signatures


def test_backends_expose_the_same_public_methods():
    sqlite = _public_signatures(SqliteRepository)
    postgres = _public_signatures(PostgresRepository)

    only_sqlite = sorted(set(sqlite) - set(postgres))
    only_postgres = sorted(set(postgres) - set(sqlite))
    assert not only_sqlite, f"methods missing from api/db_pg.py: {only_sqlite}"
    assert not only_postgres, f"methods missing from api/db.py: {only_postgres}"


def test_backend_method_signatures_match():
    sqlite = _public_signatures(SqliteRepository)
    postgres = _public_signatures(PostgresRepository)
    mismatches = {
        name: (sqlite[name], postgres[name])
        for name in sorted(set(sqlite) & set(postgres))
        if sqlite[name] != postgres[name]
    }
    assert not mismatches, f"signature drift between backends: {mismatches}"


def test_transfer_engine_repository_methods_exist_on_both_backends():
    # The M03 surface the transfer engine depends on. Pinned explicitly so a
    # rename is a deliberate, visible change rather than a silent one-backend edit.
    required = {
        "create_pending_object",
        "get_pending_by_idempotency",
        "get_object",
        "list_objects",
        "count_pending",
        "mark_available",
        "list_pending_before",
        "set_status",
        "delete_object_row",
    }
    for cls in (SqliteRepository, PostgresRepository):
        present = set(_public_signatures(cls))
        missing = sorted(required - present)
        assert not missing, f"{cls.__module__} is missing {missing}"
