"""Raw catalogue statements for tests, on either backend.

Tests occasionally need to reach past the API (backdate a row, read an
internal column). The two repositories expose different connection APIs
(``sqlite3`` vs psycopg), so statements go through the PostgreSQL ``_run`` /
``_one`` helpers there. SQL is written with ``?`` placeholders and translated.
This lets the whole suite run with ``AURA_API_BACKEND=postgres`` (CI job
``api-postgres``), not only on SQLite.
"""
import api.main as main
from api.migrations import _translate_placeholders


def execute(sql: str, params: tuple = ()) -> None:
    repo = main.repo
    if repo.dialect == "sqlite":
        repo.conn.execute(sql, params)
        repo.conn.commit()
    else:
        repo._run(_translate_placeholders(sql), params)


def fetch_one(sql: str, params: tuple = ()):
    repo = main.repo
    if repo.dialect == "sqlite":
        return repo.conn.execute(sql, params).fetchone()
    return repo._one(_translate_placeholders(sql), params)
