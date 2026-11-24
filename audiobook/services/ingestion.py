"""Service: staged file ingestion through AURA, without automatic publication."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from ..errors import ConflictError, UnavailableError, ValidationError
from ..ids import utcnow
from ..ingestion import validate_file
from .base import BaseService

_ALLOWED_SOURCES = {"manual", "shelfmark", "partner"}


def retry_due(
    item: dict,
    *,
    now: datetime,
    delay_seconds: int,
    max_attempts: int,
) -> bool:
    """Pure helper used by the reconciliation sweep and its unit tests."""
    if item.get("state") != "retryable_failed":
        return False
    try:
        attempts = int(item.get("attempts") or 0)
    except (TypeError, ValueError):
        return False
    if attempts >= max_attempts:
        return False
    updated = item.get("updated_at")
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(updated, datetime):
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated <= now - timedelta(seconds=delay_seconds)


class IngestService(BaseService):
    def _staging_root(self) -> Path:
        raw = str(self.settings.ingest_staging_dir or "").strip()
        if not raw:
            raise UnavailableError(
                "ingest staging directory is not configured",
                code="INGEST_STAGING_NOT_CONFIGURED",
            )
        return Path(raw).resolve()

    def _staged_path(self, relative: str) -> Path:
        candidate = Path(relative).resolve()
        root = self._staging_root()
        if candidate == root or root not in candidate.parents:
            raise ValidationError(
                "staged file must be inside the configured directory",
                code="INGEST_PATH_OUTSIDE_STAGING",
            )
        return candidate

    def start_ingestion(
        self,
        *,
        source: str,
        source_ref: str,
        filename: str,
        staged_path: str,
        declared_content_type: str = "",
        batch_id: UUID | None = None,
        target_edition_id: UUID | None = None,
        track_position: int | None = None,
        track_title: str = "",
        duration_ms: int | None = None,
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        if source not in _ALLOWED_SOURCES:
            raise ValidationError("unsupported ingest source", code="INGEST_SOURCE_INVALID")
        path = self._staged_path(staged_path)
        validated = validate_file(
            path,
            filename,
            max_bytes=self.settings.ingest_max_bytes,
            av_command=self.settings.ingest_av_command,
            ffprobe_command=self.settings.ingest_ffprobe_command,
            duration_ms=duration_ms,
        )
        kind = (
            "audiobook"
            if validated.detected_content_type.startswith("audio/")
            else "ebook"
        )
        key_material = f"{source}|{source_ref}|{validated.sha256}".encode("utf-8")
        idempotency_key = "audiobook_" + hashlib.sha256(key_material).hexdigest()
        item, created = self.repo.create_ingest_item(
            source=source,
            source_ref=source_ref,
            original_filename=validated.original_filename,
            staging_path=str(path),
            declared_content_type=declared_content_type,
            detected_content_type=validated.detected_content_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            kind=kind,
            idempotency_key=idempotency_key,
            batch_id=batch_id,
            target_edition_id=target_edition_id,
            track_position=track_position,
            track_title=track_title,
            duration_ms=validated.duration_ms,
            request_id=request_id,
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="ingest.started" if created else "ingest.duplicate",
            target_type="ingest_item",
            target_id=str(item["id"]),
            outcome="success",
            reason=validated.sha256,
            request_id=request_id,
        )
        return {**item, "duplicate": not created}

    def import_item(
        self,
        item_id: UUID,
        *,
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        item = self.repo.get_ingest_item(item_id)
        staged_path = self.repo.internal_path(item_id)
        if not Path(staged_path).is_file():
            self._fail(item_id, "INGEST_FILE_MISSING", actor_id, request_id)
            raise UnavailableError("staged file is missing", code="INGEST_FILE_MISSING")
        self.repo.transition_ingest_item(
            item_id,
            to_state="importing",
            from_states=("validating", "retryable_failed"),
            increment_attempts=True,
        )
        try:
            intent = self.storage.create_upload_intent(
                display_name=str(item["original_filename"]),
                content_type=str(item["detected_content_type"]),
                size_bytes=int(item["size_bytes"]),
                idempotency_key=str(item["idempotency_key"]),
            )
            self.storage.upload_bytes(intent, Path(staged_path))
            committed = self.storage.commit_upload(
                intent.object_id, idempotency_key=str(item["idempotency_key"])
            )
        except (UnavailableError, ValidationError) as exc:
            self._fail(item_id, exc.code, actor_id, request_id)
            raise
        if (
            committed.size_bytes != int(item["size_bytes"])
            or committed.checksum_sha256.lower() != str(item["sha256"]).lower()
        ):
            self._fail(item_id, "INGEST_VERIFICATION_FAILED", actor_id, request_id)
            raise UnavailableError(
                "AURA verification differs from the staged file",
                code="INGEST_VERIFICATION_FAILED",
            )
        try:
            asset_id = self._attach_catalogue(item, committed, actor_id, request_id)
        except (UnavailableError, ValidationError) as exc:
            self._fail(item_id, exc.code, actor_id, request_id)
            raise
        updated = self.repo.transition_ingest_item(
            item_id,
            to_state="completed",
            from_states=("importing",),
            storage_object_id=committed.object_id,
            asset_id=asset_id,
            duration_ms=item.get("duration_ms"),
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="ingest.imported",
            target_type="ingest_item",
            target_id=str(item_id),
            outcome="success",
            reason=committed.object_id,
            request_id=request_id,
        )
        return updated

    def _attach_catalogue(
        self, item: dict, committed: Any, actor_id: str, request_id: str
    ) -> UUID | None:
        edition_id = item.get("target_edition_id")
        if edition_id is None:
            return None
        bundle = self.repo.get_edition_bundle(UUID(str(edition_id)))
        if bundle is None:
            raise ValidationError("target edition not found", code="INGEST_TARGET_NOT_FOUND")
        publication_kind = str(bundle["edition"].get("publication_kind") or "audiobook")
        content_type = str(item["detected_content_type"])
        is_audio = content_type.startswith("audio/")
        expected_kind = "audiobook" if is_audio else "ebook"
        if publication_kind != expected_kind:
            raise ValidationError(
                "file kind does not match the edition",
                code="INGEST_EDITION_KIND_MISMATCH",
            )
        duration_ms = item.get("duration_ms")
        if is_audio and (not duration_ms or int(duration_ms) <= 0):
            raise ValidationError(
                "audio duration is required to create a track",
                code="INGEST_DURATION_REQUIRED",
            )
        existing = self.repo.find_asset_by_storage_object_id(committed.object_id)
        if existing is not None:
            asset_id = UUID(str(existing["id"]))
        else:
            asset = self.repo.create_asset(
                storage_object_id=committed.object_id,
                kind="source" if is_audio else "ebook",
                content_type=content_type,
                size_bytes=committed.size_bytes,
                checksum_sha256=committed.checksum_sha256,
                duration_ms=int(duration_ms) if is_audio else None,
                status="ready",
            )
            asset_id = UUID(str(asset["id"]))
        if not is_audio:
            ebook_format = "epub" if content_type == "application/epub+zip" else "pdf"
            self.repo.link_ebook_asset(
                UUID(str(edition_id)), asset_id=asset_id, format=ebook_format
            )
            return asset_id
        duration = int(duration_ms)
        position = int(item.get("track_position") or len(bundle["tracks"]) + 1)
        title = str(item.get("track_title") or "") or str(item["original_filename"])
        has_track = any(
            str(track["asset_id"]) == str(asset_id) for track in bundle["tracks"]
        )
        has_chapter = any(
            int(chapter["position"]) == position for chapter in bundle["chapters"]
        )
        if not has_track:
            self.repo.create_track(
                UUID(str(edition_id)),
                position=position,
                title=title,
                start_ms=0,
                end_ms=duration,
                asset_id=asset_id,
                status="ready",
            )
        if not has_chapter:
            self.repo.create_chapter(
                UUID(str(edition_id)),
                position=position,
                title=title,
                start_ms=0,
                end_ms=duration,
            )
        return asset_id

    def _fail(
        self, item_id: UUID, error_code: str, actor_id: str, request_id: str
    ) -> None:
        try:
            self.repo.transition_ingest_item(
                item_id,
                to_state="retryable_failed",
                from_states=("importing",),
                error_code=error_code,
            )
        except ConflictError:
            return
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="ingest.failed",
            target_type="ingest_item",
            target_id=str(item_id),
            outcome="failed",
            reason=error_code,
            request_id=request_id,
        )

    def retry_item(
        self, item_id: UUID, *, actor_id: str = "admin", request_id: str = ""
    ) -> dict:
        item = self.repo.get_ingest_item(item_id)
        if item["state"] != "retryable_failed":
            raise ConflictError(
                "only retryable failed ingest items can be retried",
                code="INGEST_NOT_RETRYABLE",
            )
        return self.import_item(item_id, actor_id=actor_id, request_id=request_id)

    def reject_item(
        self,
        item_id: UUID,
        *,
        reason: str,
        actor_id: str = "admin",
        request_id: str = "",
    ) -> dict:
        updated = self.repo.transition_ingest_item(
            item_id,
            to_state="rejected",
            from_states=("received", "validating", "retryable_failed", "awaiting_rights"),
            error_code="REJECTED",
        )
        self.repo.record_audit(
            actor_type="admin",
            actor_id=actor_id,
            action="ingest.rejected",
            target_type="ingest_item",
            target_id=str(item_id),
            outcome="success",
            reason=reason[:500],
            request_id=request_id,
        )
        return updated

    def list_ingest_items(self, *, limit: int = 50, state: str = "") -> dict:
        return {"items": self.repo.list_ingest_items(limit=limit, state=state)}

    def reconcile_ingestions(
        self, *, actor_id: str = "reconciler", request_id: str = ""
    ) -> dict:
        """Bounded sweep: mark stale imports, retry due failures, never publish."""
        now = utcnow()
        stale = self.repo.list_stale_importing_items(
            older_than=now - timedelta(seconds=self.settings.ingest_stale_import_seconds),
            limit=50,
        )
        stale_marked: list[str] = []
        for item in stale:
            try:
                self.repo.transition_ingest_item(
                    item["id"],
                    to_state="retryable_failed",
                    from_states=("importing",),
                    error_code="INGEST_STALE_IMPORT",
                )
            except (ConflictError, UnavailableError):
                continue
            stale_marked.append(str(item["id"]))
            self.repo.record_audit(
                actor_type="system",
                actor_id=actor_id,
                action="ingest.stale",
                target_type="ingest_item",
                target_id=str(item["id"]),
                outcome="success",
                reason="INGEST_STALE_IMPORT",
                request_id=request_id,
            )
        candidates = self.repo.list_retryable_ingest_items(
            not_updated_since=now
            - timedelta(seconds=self.settings.ingest_retry_delay_seconds),
            max_attempts=self.settings.ingest_retry_max_attempts,
            limit=50,
        )
        retried: list[str] = []
        failed: list[dict] = []
        for item in candidates:
            if not retry_due(
                item,
                now=now,
                delay_seconds=self.settings.ingest_retry_delay_seconds,
                max_attempts=self.settings.ingest_retry_max_attempts,
            ):
                continue
            try:
                self.retry_item(
                    item["id"], actor_id=actor_id, request_id=request_id
                )
            except Exception as exc:  # one bad item must not stop the sweep
                failed.append(
                    {
                        "id": str(item["id"]),
                        "error": getattr(exc, "code", "RECONCILE_FAILED"),
                    }
                )
                continue
            retried.append(str(item["id"]))
        summary = {
            "stale_marked": stale_marked,
            "retried": retried,
            "failed": failed,
        }
        self.repo.record_audit(
            actor_type="system",
            actor_id=actor_id,
            action="ingest.reconciled",
            target_type="ingest_sweep",
            outcome="success",
            reason=(
                f"stale={len(stale_marked)} retried={len(retried)} "
                f"failed={len(failed)}"
            ),
            request_id=request_id,
        )
        return summary
