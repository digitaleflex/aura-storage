"""Lifecycle: reconcile stale pending uploads, soft-delete, purge (#19 follow-up)."""
import time


class StorageDeleteError(RuntimeError):
    """Raised when the storage backend refuses a delete (M06).

    The catalogue row is left untouched so a transient S3 outage never causes
    reference loss: the caller must surface a 5xx and let the next sweep retry.
    """


def reconcile_pending(repo, s3ops, expire_after_s: int = 3600) -> dict:
    """Expire pending objects older than the grace period.

    Administrative sweep across every space; the route that calls it requires
    the ``admin:write`` capability (#36). A catalogue row is marked ``expired``
    only after its storage bytes were actually removed: a storage failure keeps
    the intent ``pending`` for a later sweep and is reported in
    ``storage_failures`` instead of being counted as cleaned (M06). Returns
    counts for observability.
    """
    cutoff = int(time.time()) - expire_after_s
    expired = 0
    storage_deletes = 0
    storage_failures = 0
    for r in repo.list_pending_before(cutoff):
        row = dict(r) if not isinstance(r, dict) else r
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except Exception:
            # Keep the pending reference so the next sweep retries; never
            # declare a failed cleanup as expired.
            storage_failures += 1
            continue
        storage_deletes += 1
        repo.set_status(row["id"], "expired")
        expired += 1
    return {
        "expired": expired,
        "storage_deletes_attempted": storage_deletes,
        "storage_failures": storage_failures,
    }


def purge_object(repo, s3ops, oid: str, *, space_id: str,
                 owner_id: str | None = None) -> bool:
    """Permanently delete bytes then the catalogue row. Returns True if done.

    Scoped to the caller's space (#35); ``owner_id`` further restricts to a
    single human owner. The route requires the ``objects:purge`` capability.
    A storage failure raises :class:`StorageDeleteError` and the catalogue row
    is kept, so the reference is never lost (M06); the route maps this to 502.
    """
    row = repo.get_object(oid, space_id=space_id, owner_id=owner_id)
    if row is None:
        return False
    row = dict(row) if not isinstance(row, dict) else row
    try:
        s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception as exc:
        raise StorageDeleteError(f"storage delete failed for {oid}") from exc
    repo.delete_object_row(oid)
    return True
