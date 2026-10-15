"""Serialize catalogue access on the single shared connection.

Both backends keep **one** connection for the whole process: SQLite in dev/test
(``api/db.py``) and psycopg on the pilot (``api/db_pg.py``). FastAPI runs sync
endpoints in a worker threadpool, so that connection is used from several threads
at once. Neither ``sqlite3`` nor ``psycopg`` supports concurrent use of a single
connection: it surfaced as ``sqlite3.InterfaceError: bad parameter or other API
misuse`` and, through the auth path, as transient 401/500 responses.

``@synchronized`` wraps every public method of a repository in a re-entrant lock,
so a logical operation — which may issue several statements — runs as a unit.
The lock is per instance (``self._lock``, created in ``Repository.__init__``).

This is the minimal correctness fix for a single-process deployment. A real
connection pool is the scale answer and can replace this decorator without
touching the method bodies.
"""
import functools


def synchronized(cls):
    """Class decorator: run every public method under the instance lock."""
    for name, attr in list(vars(cls).items()):
        if name.startswith("__") or isinstance(attr, (staticmethod, classmethod)):
            continue
        if not callable(attr):
            continue
        setattr(cls, name, _wrap(attr))
    return cls


def _wrap(fn):
    @functools.wraps(fn)
    def inner(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return inner
