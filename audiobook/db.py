"""PostgreSQL access for the audiobook bounded context.

The service deliberately does not share tables with AURA. It uses a dedicated
schema (or a dedicated database) and applies versioned SQL migrations.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def split_sql(script: str) -> list[str]:
    """Split a migration into statements, respecting single-quoted literals.

    psycopg's extended protocol refuses several commands in one ``execute``.
    The migrations here contain only DDL and simple CHECK constraints, so a
    quote-aware split on ``;`` is sufficient and keeps the migration file
    readable as one versioned artifact.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_quote = False
    index = 0
    while index < len(script):
        char = script[index]
        if char == "'":
            # SQL escapes a quote inside a literal by doubling it.
            if in_quote and index + 1 < len(script) and script[index + 1] == "'":
                buffer.append("''")
                index += 2
                continue
            in_quote = not in_quote
            buffer.append(char)
            index += 1
            continue
        if char == ";" and not in_quote:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


class Database:
    def __init__(self, dsn: str, schema: str = "audiobook") -> None:
        if not dsn:
            raise ValueError("database DSN is required")
        if not _SCHEMA_RE.fullmatch(schema):
            raise ValueError("invalid schema name")
        self.dsn = dsn
        self.schema = schema

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with psycopg.connect(
            self.dsn, row_factory=dict_row, autocommit=True
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self.schema}", public')
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.connect() as conn:
            with conn.transaction():
                yield conn

    def init_schema(self) -> None:
        """Create the schema, its migration table and apply pending migrations."""
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cur.execute(f'SET search_path TO "{self.schema}", public')
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                      version TEXT PRIMARY KEY,
                      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute("SELECT version FROM schema_migrations")
                applied = {row["version"] for row in cur.fetchall()}
                for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    version = path.name
                    if version in applied:
                        continue
                    script = path.read_text(encoding="utf-8")
                    for statement in split_sql(script):
                        cur.execute(statement)
                    cur.execute(
                        "INSERT INTO schema_migrations(version) VALUES (%s)",
                        (version,),
                    )

    def healthcheck(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()

    def drop_schema(self) -> None:
        """Test helper. Refuses to touch a non-test schema."""
        if not self.schema.startswith("audiobook_test_"):
            raise RuntimeError("drop_schema is restricted to audiobook_test_* schemas")
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
