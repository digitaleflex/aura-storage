"""Lifecycle: reconcile stale pending uploads, soft-delete, purge (#19 follow-up)."""
import time

from .s3 import is_no_such_upload
from .transfer import PURGING


def _delete_thumbnail(s3ops, row: dict) -> None:
    """Best-effort thumbnail cleanup; the object delete must not depend on it."""
    key = row.get("thumbnail_key")
    if not key:
        return
    try:
        s3ops.delete_object(Bucket=row["bucket"], Key=key)
    except Exception:
        pass


def _delete_hls(s3ops, row: dict) -> None:
    """Best-effort removal of a packaged HLS prefix (playlist + segments)."""
    prefix = row.get("hls_prefix")
    if not prefix:
        return
    try:
        listing = s3ops.list_objects_v2(Bucket=row["bucket"], Prefix=f"{prefix}/")
        for obj in listing.get("Contents", []) or []:
            s3ops.delete_object(Bucket=row["bucket"], Key=obj["Key"])
    except Exception:
        pass


class StorageDeleteError(RuntimeError):
    """Raised when the storage backend refuses a delete (M06).

    The catalogue row is left untouched so a transient S3 outage never causes
    reference loss: the caller must surface a 5xx and let the next sweep retry.
    """


class PurgeBlockedError(RuntimeError):
    """Raised when an object cannot be purged because policy blocks it (e.g.
    keep-forever revisions exist). The catalogue row is left untouched.
    """


def reconcile_pending(repo, s3ops, expire_after_s: int = 3600,
                      limit: int = 500,
                      multipart_expired_before: int | None = None) -> dict:
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
    if multipart_expired_before is None:
        multipart_expired_before = int(time.time())
    for r in repo.list_pending_before(
        cutoff, limit=max(1, limit), multipart_expired_before=multipart_expired_before,
    ):
        row = dict(r) if not isinstance(r, dict) else r
        try:
            if row.get("multipart_upload_id"):
                # Free the parts of an abandoned multipart upload (#72).
                try:
                    s3ops.abort_multipart_upload(
                        Bucket=row["bucket"], Key=row["object_key"],
                        UploadId=row["multipart_upload_id"],
                    )
                except Exception as exc:
                    if not is_no_such_upload(exc):
                        raise
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
            _delete_thumbnail(s3ops, row)
            _delete_hls(s3ops, row)
        except Exception:
            # Keep the pending reference so the next sweep retries; never
            # declare a failed cleanup as expired.
            storage_failures += 1
            continue
        storage_deletes += 1
        repo.set_status(
            row["id"], "expired",
            failure_kind="expired",
            error_message="upload intent expired before commit",
        )
        expired += 1
    return {
        "expired": expired,
        "storage_deletes_attempted": storage_deletes,
        "storage_failures": storage_failures,
    }


def reconcile_terminal(repo, s3ops, *, statuses=("failed", "aborted", "deleted"),
                      retention_s: int = 7 * 24 * 3600, limit: int = 500) -> dict:
    """Clean up bytes for terminal rows older than ``retention_s``.

    Administrative sweep across every space. A row is removed (row deleted) only
    after its bytes were actually deleted: a storage failure keeps the row for a
    later sweep and is reported in ``storage_failures``.
    """
    now_ts = int(time.time())
    cutoff = now_ts - retention_s
    cleaned = 0
    storage_deletes = 0
    storage_failures = 0
    for status in statuses:
        for r in repo.list_status_before(status, cutoff, limit=max(1, limit)):
            row = dict(r) if not isinstance(r, dict) else r
            ts = row.get("terminal_since") or row.get("updated_at") or 0
            if int(ts) > cutoff:
                continue
            try:
                s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
                _delete_thumbnail(s3ops, row)
                _delete_hls(s3ops, row)
            except Exception:
                storage_failures += 1
                continue
            storage_deletes += 1
            repo.delete_object_row(row["id"])
            cleaned += 1
    return {
        "cleaned": cleaned,
        "storage_deletes_attempted": storage_deletes,
        "storage_failures": storage_failures,
    }


def purge_transfer_history(repo, *, retention_days: int | None = None,
                           limit: int = 500, now=time.time) -> dict:
    """Drop transfer-journal rows older than the configured retention window.

    The journal is append-only while retained, but it is not the source of
    truth: `objects` stays authoritative, so old rows can be purged safely.
    A missing/zero retention falls back to the configured default (90 days).
    """
    if retention_days is None:
        from .config import settings
        retention_days = settings.transfer_history_retention_days
    retention_days = max(1, int(retention_days))
    cutoff = int(now()) - retention_days * 86400
    purged = repo.purge_transfer_records_before(cutoff, limit=max(1, limit))
    return {"transfer_records_purged": purged, "transfer_history_cutoff": cutoff}


def reconcile_reverse(repo, s3ops, *, dry_run: bool = True,
                     limit: int = 500) -> dict:
    """Storage -> catalogue reverse sweep (G2).

    Lists objects under the ``aura/`` prefix in every known bucket and reports
    (optionally deletes) those with no catalogue row. Dry-run by default.
    Revision storage keys are excluded: they are accounted for in
    ``object_revisions`` and must never be treated as orphans.
    """
    orphans = []
    deleted = 0
    failures = 0
    seen = 0
    try:
        buckets = [b["name"] for b in repo.list_all_buckets()]
    except Exception:
        buckets = []
    for bucket in buckets:
        try:
            resp = s3ops.list_objects_v2(Bucket=bucket, Prefix="aura/", MaxKeys=limit)
        except Exception:
            failures += 1
            continue
        for obj in (resp.get("Contents") or []):
            seen += 1
            key = obj["Key"]
            try:
                exists = repo.has_object(bucket, key)
            except Exception:
                exists = True
            if exists:
                continue
            try:
                is_rev = hasattr(repo, "has_revision_key") and repo.has_revision_key(bucket, key)
            except Exception:
                is_rev = True
            if is_rev:
                continue
            orphans.append({"bucket": bucket, "key": key, "size": obj.get("Size")})
            if dry_run:
                continue
            try:
                s3ops.delete_object(Bucket=bucket, Key=key)
                deleted += 1
            except Exception:
                failures += 1
    return {
        "scanned": seen,
        "orphans": len(orphans),
        "orphan_keys": orphans[:50],
        "deleted": deleted,
        "failures": failures,
        "dry_run": dry_run,
    }


def purge_object(repo, s3ops, oid: str, *, space_id: str,
                 owner_id: str | None = None) -> bool:
    """Permanently delete bytes then the catalogue row. Returns True if done.

    Scoped to the caller's space (#35); ``owner_id`` further restricts to a
    single human owner. The route requires the ``objects:purge`` capability.
    A storage failure raises :class:`StorageDeleteError` and the catalogue row
    is kept, so the reference is never lost (M06); the route maps this to 502.

    Policy (Lot 3): purge is blocked while any revision is pinned keep-forever.
    When allowed, revision bytes/rows are removed before the object row to
    satisfy the FK and avoid orphaning accounted revision storage.

    Two phases, so a crash never leaves the catalogue lying: the row is first
    marked ``purging`` (hidden, not downloadable), then the bytes are deleted,
    then the row. A failed delete puts the row back as it was; a process that
    dies between the steps leaves a ``purging`` row that
    :func:`resume_purges` finishes.
    """
    row = repo.get_object(oid, space_id=space_id, owner_id=owner_id)
    if row is None:
        return False
    row = dict(row) if not isinstance(row, dict) else row

    if hasattr(repo, "count_object_keep_forever_revisions"):
        try:
            if repo.count_object_keep_forever_revisions(oid) > 0:
                raise PurgeBlockedError("cannot purge object with keep-forever revisions")
        except PurgeBlockedError:
            raise
        except Exception:
            # Fail closed: if we cannot verify, do not risk deleting pinned history.
            raise PurgeBlockedError("cannot verify revision retention state")

    previous = row["status"]
    if previous != PURGING:
        repo.set_status(oid, PURGING)
    try:
        # An in-flight multipart upload has no assembled object: abort the
        # session first, otherwise its parts linger until the session TTL and
        # no sweep can see them (the catalogue row is about to disappear).
        if row.get("multipart_upload_id"):
            try:
                s3ops.abort_multipart_upload(
                    Bucket=row["bucket"], Key=row["object_key"],
                    UploadId=row["multipart_upload_id"],
                )
            except Exception as exc:
                if not is_no_such_upload(exc):
                    raise
            repo.set_multipart(oid, None, row.get("multipart_part_bytes"))
        s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
        _delete_thumbnail(s3ops, row)
        _delete_hls(s3ops, row)
        # Remove revision bytes first (best-effort per key) then rows.
        if hasattr(repo, "list_revisions") and hasattr(repo, "delete_revisions_for_object"):
            try:
                # Re-check keep-forever just before deletion.
                if hasattr(repo, "count_object_keep_forever_revisions") and repo.count_object_keep_forever_revisions(oid) > 0:
                    raise PurgeBlockedError("cannot purge object with keep-forever revisions")
                revs = repo.list_revisions(oid)
            except PurgeBlockedError:
                raise
            except Exception:
                revs = []
            for rev in revs:
                if rev.get("keep_forever"):
                    raise PurgeBlockedError("cannot purge object with keep-forever revisions")
                try:
                    s3ops.delete_object(Bucket=rev["bucket"], Key=rev["storage_key"])
                except Exception:
                    # Best-effort: leave row/bytes consistent enough for retry/cleanup.
                    pass
            try:
                repo.delete_revisions_for_object(oid)
            except Exception:
                # Keep purging state; resume_purges can retry.
                raise
    except PurgeBlockedError:
        if previous != PURGING:
            try:
                repo.set_status(oid, previous)
            except Exception:
                pass
        raise
    except Exception as exc:
        if previous != PURGING:
            try:
                repo.set_status(oid, previous)
            except Exception:
                pass
        raise StorageDeleteError(f"storage delete failed for {oid}") from exc
    # Share links die with the object: they are dropped first so no dangling row
    # can ever be redeemed, and so no constraint blocks the object deletion.
    repo.delete_shares_for_object(oid)
    repo.delete_object_row(oid)
    return True


def resume_purges(repo, s3ops, *, older_than_s: int = 300, limit: int = 500,
                  now=time.time) -> dict:
    """Finish purges interrupted between their steps (process crash).

    A ``purging`` row older than ``older_than_s`` belongs to no live request:
    delete its bytes (deleting a key that is already gone succeeds on S3), clean
    up revision bytes/rows if unpinned, then delete the row. A storage failure or
    keep-forever block keeps the row for a later pass.
    """
    cutoff = int(now()) - older_than_s
    done = failures = 0
    for r in repo.list_status_before(PURGING, cutoff, limit=max(1, limit)):
        row = dict(r) if not isinstance(r, dict) else r
        oid = row["id"]
        try:
            if hasattr(repo, "count_object_keep_forever_revisions") and repo.count_object_keep_forever_revisions(oid) > 0:
                failures += 1
                continue
            s3ops.delete_object(Bucket=row["bucket"], Key=row["object_key"])
            _delete_thumbnail(s3ops, row)
            _delete_hls(s3ops, row)
            if hasattr(repo, "list_revisions"):
                try:
                    revs = repo.list_revisions(oid)
                except Exception:
                    revs = []
                for rev in revs:
                    if rev.get("keep_forever"):
                        raise PurgeBlockedError("keep-forever revision present")
                    try:
                        s3ops.delete_object(Bucket=rev["bucket"], Key=rev["storage_key"])
                    except Exception:
                        pass
                if hasattr(repo, "delete_revisions_for_object"):
                    try:
                        repo.delete_revisions_for_object(oid)
                    except Exception:
                        pass
        except Exception:
            failures += 1
            continue
        try:
            repo.delete_shares_for_object(oid)
            repo.delete_object_row(oid)
        except Exception:
            failures += 1
            continue
        done += 1
    return {"purges_completed": done, "purge_failures": failures}


def reconcile_revisions(repo, s3ops, *, retention_days: int = 30,
                        max_per_object: int = 100, limit: int = 200,
                        now=time.time) -> dict:
    """Prune old/excess content revisions (Lot 3, best-effort).

    Policy (pragmatic defaults): keep revisions younger than ``retention_days``
    and at most ``max_per_object`` newest per object; never delete revisions
    marked keep-forever. Bytes are deleted best-effort before the row.
    """
    cutoff = int(now()) - retention_days * 86400
    pruned = 0
    failures = 0
    # 1) Age-based candidates.
    try:
        if hasattr(repo, "_run"):
            rows = repo._all(
                "SELECT id, object_id, bucket, storage_key FROM object_revisions "
                "WHERE purged_at IS NULL AND keep_forever = 0 AND created_at < %s "
                "ORDER BY created_at ASC LIMIT %s",
                (cutoff, limit),
            )
        else:
            rows = [dict(r) for r in repo.conn.execute(
                "SELECT id, object_id, bucket, storage_key FROM object_revisions "
                "WHERE purged_at IS NULL AND keep_forever = 0 AND created_at < ? "
                "ORDER BY created_at ASC LIMIT ?",
                (cutoff, limit),
            ).fetchall()]
    except Exception:
        rows = []
    seen_ids = set()
    for row in rows:
        rid = row["id"]
        seen_ids.add(rid)
        try:
            s3ops.delete_object(Bucket=row["bucket"], Key=row["storage_key"])
        except Exception:
            pass
        try:
            repo.delete_revision(rid)
            pruned += 1
        except Exception:
            failures += 1
    # 2) Count-based per-object pruning (oldest first beyond cap).
    try:
        if hasattr(repo, "_run"):
            obj_rows = repo._all(
                "SELECT object_id FROM object_revisions WHERE purged_at IS NULL "
                "GROUP BY object_id HAVING COUNT(*) > %s LIMIT %s",
                (max_per_object, 50),
            )
        else:
            obj_rows = [dict(r) for r in repo.conn.execute(
                "SELECT object_id FROM object_revisions WHERE purged_at IS NULL "
                "GROUP BY object_id HAVING COUNT(*) > ? LIMIT ?",
                (max_per_object, 50),
            ).fetchall()]
    except Exception:
        obj_rows = []
    for o in obj_rows:
        try:
            revs = [r for r in repo.list_revisions(o["object_id"]) if not r.get("purged_at")]
        except Exception:
            continue
        # newest-first list -> keep first max_per_object
        for rev in revs[max_per_object:]:
            if rev.get("keep_forever") or rev["id"] in seen_ids:
                continue
            try:
                s3ops.delete_object(Bucket=rev["bucket"], Key=rev["storage_key"])
            except Exception:
                pass
            try:
                repo.delete_revision(rev["id"])
                pruned += 1
            except Exception:
                failures += 1
    return {"revisions_pruned": pruned, "revision_prune_failures": failures}
