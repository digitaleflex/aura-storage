"""Lifecycle: reconcile stale pending uploads, soft-delete, purge (#19 follow-up)."""
import time


def reconcile_pending(repo, s3ops, expire_after_s: int = 3600) -> dict:
    """Expire pending objects older than the grace period.

    Best effort: delete any partial bytes at storage, then mark expired.
    Returns counts for observability.
    """
    cutoff = int(time.time()) - expire_after_s
    expired = 0
    storage_deletes = 0
    for r in repo.list_pending_before(cutoff):
        row = dict(r) if not isinstance(r, dict) else r
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
            storage_deletes += 1
        except Exception:
            pass
        repo.set_status(row["id"], "expired")
        expired += 1
    return {"expired": expired, "storage_deletes_attempted": storage_deletes}


def purge_object(repo, s3ops, oid: str, owner_id: str) -> bool:
    """Permanently delete bytes then the catalogue row. Returns True if done."""
    row = repo.get_object(oid, owner_id)
    if row is None:
        return False
    row = dict(row) if not isinstance(row, dict) else row
    try:
        s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
    except Exception:
        pass
    repo.delete_object_row(oid)
    return True
