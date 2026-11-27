"""Serialize catalogue access on the single shared SQLite connection.

SQLite (``api/db.py``) keeps one connection for the whole process. FastAPI runs
sync endpoints in a worker threadpool, so that connection is used from several
threads at once and ``sqlite3`` can raise ``InterfaceError: bad parameter or
other API misuse``. ``@synchronized`` wraps every public method in a re-entrant,
per-instance lock so a logical operation runs as a unit.

The PostgreSQL backend no longer uses this decorator (#325): it checks out one
connection per operation from ``psycopg_pool`` (see ``api/db_pg.py``). Keeping
the lock there would serialize all catalogue access and cancel the pool's
concurrency benefit.
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
