#!/usr/bin/env python3
"""One-shot ingestion reconciliation sweep for the audiobook service.

Run from the repository root with the same environment as the service:

    AUDIOBOOK_DSN=... AUDIOBOOK_SCHEMA=audiobook \
    AURA_API_BASE_URL=... AURA_SERVICE_TOKEN=... \
    python scripts/audiobook_reconcile.py

The sweep never publishes content and never deletes staged files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audiobook.config import Settings  # noqa: E402
from audiobook.db import Database  # noqa: E402
from audiobook.repository import Repository  # noqa: E402
from audiobook.services import AudiobookService  # noqa: E402
from audiobook.storage import AuraStoragePort  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings.dsn, settings.schema)
    storage = AuraStoragePort(
        settings.aura_api_base_url,
        settings.aura_service_token,
        timeout_seconds=settings.ingest_timeout_seconds,
    )
    service = AudiobookService(
        Repository(db), settings, storage, metadata_providers=()
    )
    summary = service.reconcile_ingestions(
        actor_id="reconcile-cli", request_id="reconcile-cli"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
