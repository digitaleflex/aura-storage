"""Single catalogue repository instance shared by the API and the auth layer.

Kept in its own module so ``authz`` can reach it without importing ``main``
(which would create an import cycle).
"""
from .config import settings

if settings.db_backend == "postgres":
    if not settings.db_dsn:
        raise RuntimeError("AURA_API_DSN is required with AURA_API_BACKEND=postgres")
    from .db_pg import Repository
else:
    from .db import Repository

repo = Repository(settings.db_dsn if settings.db_backend == "postgres" else settings.db_path)
