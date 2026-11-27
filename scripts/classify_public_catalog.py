#!/usr/bin/env python3
"""Classify published audio with public category/theme/language tags.

Dry-run by default. Private tags are preserved. Existing public facets are kept
unless ``--replace-public-tags`` is explicitly passed.

Usage (inside the API container):
    docker compose exec -T api python - < scripts/classify_public_catalog.py
    docker compose exec -T api python - --apply --replace-public-tags \
        < scripts/classify_public_catalog.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("AURA_REPO_ROOT", str(Path(__file__).resolve().parents[1])))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_env_file = ROOT / ".env"
for _line in (_env_file.read_text(encoding="utf-8").splitlines() if _env_file.exists() else []):
    _line = _line.strip()
    if not _line or _line.startswith("#") or "=" not in _line:
        continue
    _key, _value = _line.split("=", 1)
    os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

if os.environ.get("S3_API_ACCESS_KEY"):
    os.environ.setdefault("AURA_S3_ACCESS_KEY", os.environ["S3_API_ACCESS_KEY"])
    os.environ.setdefault("AURA_S3_SECRET_KEY", os.environ["S3_API_SECRET_KEY"])
if os.environ.get("S3_DOMAIN"):
    os.environ.setdefault("AURA_S3_ENDPOINT", f"https://{os.environ['S3_DOMAIN']}")
if not os.environ.get("AURA_API_BACKEND") and os.environ.get("POSTGRES_USER"):
    from urllib.parse import quote_plus
    os.environ["AURA_API_BACKEND"] = "postgres"
    os.environ["AURA_API_DSN"] = (
        "postgresql://{u}:{p}@localhost:5432/{db}".format(
            u=quote_plus(os.environ["POSTGRES_USER"]),
            p=quote_plus(os.environ.get("POSTGRES_PASSWORD", "")),
            db=os.environ.get("POSTGRES_DB", "aura"),
        )
    )

from api.config import settings  # noqa: E402
from api.public_classification import (  # noqa: E402
    CATEGORY_LABELS, classify_public_item, merge_public_tags,
)
from api.store import repo  # noqa: E402

AUDIO_TYPES = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/flac", "audio/aac")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", default="Espace_init")
    parser.add_argument("--include-unpublished", action="store_true")
    parser.add_argument("--replace-public-tags", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    space = next((s for s in repo.list_spaces() if s["name"] == args.space), None)
    if space is None:
        print(f"espace introuvable: {args.space}", file=sys.stderr)
        return 2
    ph = "?" if settings.db_backend == "sqlite" else "%s"
    placeholders = ",".join(ph for _ in AUDIO_TYPES)
    published_clause = "" if args.include_unpublished else "AND o.published_at IS NOT NULL"
    rows = repo.conn.execute(
        f"SELECT o.id, o.display_name, COALESCE(f.name, '') AS folder_name "
        f"FROM objects o LEFT JOIN folders f ON f.id = o.folder_id "
        f"WHERE o.space_id = {ph} AND o.content_type IN ({placeholders}) "
        f"AND o.status = 'available' {published_clause} ORDER BY o.display_name",
        (space["id"], *AUDIO_TYPES),
    ).fetchall()
    if args.limit > 0:
        rows = rows[:args.limit]
    if not rows:
        print("aucun livre audio disponible")
        return 0

    ids = [row["id"] for row in rows]
    tags_by_object = repo.list_tags_for_objects(ids)
    changes: list[tuple[dict, list[str]]] = []
    categories: Counter = Counter()
    for row in rows:
        item = dict(row)
        classification = classify_public_item(item["display_name"], item["folder_name"])
        existing = tags_by_object.get(item["id"], [])
        merged = merge_public_tags(
            existing, classification, replace=args.replace_public_tags,
        )
        categories[classification["category"]] += 1
        if set(merged) != set(existing):
            changes.append((item, merged))

    print(
        f"espace={args.space} livres={len(rows)} modifications={len(changes)} "
        f"mode={'remplacement' if args.replace_public_tags else 'preservation'}"
    )
    for slug, count in categories.most_common():
        print(f"  {CATEGORY_LABELS[slug]} : {count}")
    if args.verbose:
        for item, tags in changes:
            public = [tag for tag in tags if tag.startswith(("categorie-", "theme-", "langue-"))]
            print(f"  - {item['display_name']} | {', '.join(public)}")
    if not args.apply:
        print("DRY-RUN : aucune ecriture. Relancer avec --apply pour classer.")
        return 0

    for item, tags in changes:
        repo.set_object_tags(item["id"], tags)
    print(f"classification appliquee : {len(changes)} livres")
    return 0


if __name__ == "__main__":
    try:
        _exit_code = main()
    finally:
        repo.close_pool()
    raise SystemExit(_exit_code)
