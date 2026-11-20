#!/usr/bin/env python3
"""One-off admin tool: expose S3-backed audiobooks on the public portal.

The AURA catalogue stores the metadata (display name, content type, S3 key);
S3 object keys are server-generated UUIDs, so a bucket prefix cannot tell which
objects are audiobooks. This tool works from the catalogue, checks the bytes in
S3, finalizes abandoned upload intents, normalizes playable content types,
assigns stable public slugs and publishes one ordered pack.

Safety:
- dry-run by default; pass --apply to write anything.
- never prints credentials, object keys or presigned URLs.
- skips objects without bytes in S3, objects without SSE-S3 when required,
  and objects that are soft-deleted.
- audio/x-m4a is rewritten to audio/mp4: /m/<slug> only serves inline types
  from the allow-list, and x-m4a would be downloaded instead of played.

Usage (from the repository root):
    .venv/bin/python scripts/publish_audiobooks.py --dry-run
    .venv/bin/python scripts/publish_audiobooks.py --apply --limit 50
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("AURA_REPO_ROOT", str(Path(__file__).resolve().parents[1])))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load the local .env without echoing any value (secrets stay in the file).
# Inside the API container the environment is already complete and .env absent.
_env_file = ROOT / ".env"
for _line in (_env_file.read_text(encoding="utf-8").splitlines() if _env_file.exists() else []):
    _line = _line.strip()
    if not _line or _line.startswith("#") or "=" not in _line:
        continue
    _key, _value = _line.split("=", 1)
    os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

# Compose maps .env names to the AURA_* names the API reads. Repeat the mapping
# here so a host-run script sees the same configuration without echoing secrets.
os.environ.setdefault("AURA_API_ADMIN_PASSWORD", os.environ.get("AURA_API_ADMIN_PASSWORD", ""))
if os.environ.get("S3_API_ACCESS_KEY"):
    os.environ.setdefault("AURA_S3_ACCESS_KEY", os.environ["S3_API_ACCESS_KEY"])
    os.environ.setdefault("AURA_S3_SECRET_KEY", os.environ["S3_API_SECRET_KEY"])
if os.environ.get("S3_DOMAIN"):
    os.environ.setdefault("AURA_S3_ENDPOINT", f"https://{os.environ['S3_DOMAIN']}")

# Compose sets these for the container, but a host-run script only has .env.
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

import boto3  # noqa: E402

from api.config import settings  # noqa: E402
from api.store import repo  # noqa: E402

AUDIO_TYPES = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/flac", "audio/aac")
PLAYABLE = {
    "audio/mpeg": "audio/mpeg", "audio/mp3": "audio/mpeg",
    "audio/ogg": "audio/ogg", "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav", "audio/mp4": "audio/mp4",
    "audio/x-m4a": "audio/mp4", "audio/aac": "audio/aac",
    "audio/flac": "audio/flac",
}
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
ACTIVE = ("available", "pending", "verifying", "expired", "failed")


def slugify(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    value = value.strip("-")[:63].strip("-")
    return value if SLUG_RE.fullmatch(value) else ""


def unique_slug(base: str, oid: str) -> str:
    candidate = base or "audio"
    if repo.get_object_by_slug(candidate) not in (None,):
        candidate = f"{candidate[:52]}-{oid[:8]}"
    if repo.get_object_by_slug(candidate) is not None:
        candidate = f"audio-{oid[:16]}"
    return candidate


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def head(s3, bucket: str, key: str):
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None


def sha256_and_size(s3, bucket: str, key: str) -> tuple[int, str] | None:
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    digest = hashlib.sha256()
    total = 0
    with response["Body"] as body:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()


def admin_owner_id() -> str | None:
    row = repo.conn.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", default="Espace_init", help="catalogue space name")
    parser.add_argument("--limit", type=int, default=50, help="max books to publish")
    parser.add_argument("--pack-slug", default="livres-audio")
    parser.add_argument("--pack-title", default="Bibliothèque audio")
    parser.add_argument("--pack-description", default="Livres audio disponibles à l'écoute.")
    parser.add_argument("--revive-pending", action="store_true",
                        help="finalize pending/failed/expired intents whose bytes exist in S3")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()

    space = next((s for s in repo.list_spaces() if s["name"] == args.space), None)
    if space is None:
        print(f"espace introuvable: {args.space}", file=sys.stderr)
        return 2
    sid = space["id"]
    ph = "?" if settings.db_backend == "sqlite" else "%s"
    placeholders = ",".join(ph for _ in AUDIO_TYPES)
    rows = repo.conn.execute(
        f"SELECT * FROM objects WHERE space_id = {ph} AND content_type IN ({placeholders}) "
        "AND status IN ('available','pending','verifying','expired','failed') "
        "ORDER BY created_at DESC",
        (sid, *AUDIO_TYPES),
    ).fetchall()
    s3 = s3_client()
    ready: list[dict] = []
    skipped = {"no_bytes": 0, "no_sse": 0, "terminal": 0, "too_large": 0}
    for row in rows:
        obj = dict(row)
        if len(ready) >= args.limit:
            break
        info = head(s3, obj["bucket"], obj["object_key"])
        if info is None:
            skipped["no_bytes"] += 1
            continue
        if settings.require_sse and info.get("ServerSideEncryption") != "AES256":
            skipped["no_sse"] += 1
            continue
        size = int(info.get("ContentLength", 0))
        if size <= 0:
            skipped["no_bytes"] += 1
            continue
        if obj["status"] != "available":
            if not args.revive_pending:
                skipped["terminal"] += 1
                continue
            if size > settings.max_object_bytes:
                skipped["too_large"] += 1
                continue
        ready.append((obj, size))

    print(f"espace={args.space} candidats={len(rows)} retenus={len(ready)} ignored={skipped}")
    for obj, size in ready:
        playable = PLAYABLE.get(obj["content_type"], obj["content_type"])
        print(f"  - {obj['display_name']} | {obj['status']} | {size} octets | {playable}")
    if not args.apply:
        print("DRY-RUN : aucune ecriture. Relancer avec --apply pour publier.")
        return 0

    owner = admin_owner_id()
    published_ids: list[str] = []
    for obj, size in ready:
        oid = obj["id"]
        if obj["status"] != "available":
            result = sha256_and_size(s3, obj["bucket"], obj["object_key"])
            if result is None or result[0] != size:
                print(f"  ! checksum impossible: {obj['display_name']}", file=sys.stderr)
                continue
            mark = "?" if settings.db_backend == "sqlite" else "%s"
            repo.conn.execute(
                f"UPDATE objects SET status='available', size_bytes={mark}, "
                f"checksum_sha256={mark}, version=version+1, updated_at={mark} "
                f"WHERE id={mark} AND status IN ('pending','verifying','expired','failed')",
                (size, result[1], int(time.time()), oid),
            )
            repo.conn.commit()
        content_type = PLAYABLE.get(obj["content_type"], obj["content_type"])
        if content_type != obj["content_type"]:
            mark = "?" if settings.db_backend == "sqlite" else "%s"
            repo.conn.execute(
                f"UPDATE objects SET content_type={mark}, version=version+1 WHERE id={mark}",
                (content_type, oid),
            )
            repo.conn.commit()
        slug = obj.get("public_slug") or unique_slug(
            slugify(Path(obj["display_name"]).stem), oid
        )
        if not obj.get("published_at"):
            repo.set_object_publication(oid, slug, int(time.time()))
        published_ids.append(oid)
        print(f"  publie: {obj['display_name']} -> /m/{slug}")

    if not published_ids:
        print("rien a publier")
        return 1
    collection = repo.get_collection_by_slug(args.pack_slug)
    if collection is None:
        if owner is None:
            print("aucun administrateur pour posseder le pack", file=sys.stderr)
            return 2
        cid = repo.new_id()
        repo.create_collection(cid, sid, owner, args.pack_slug, args.pack_title, args.pack_description)
    else:
        cid = collection["id"]
    repo.replace_collection_items(cid, published_ids)
    repo.update_collection(cid, args.pack_title, args.pack_description, int(time.time()))
    print(
        f"pack publie: {len(published_ids)} pistes ; "
        f"manifeste sur APP_DOMAIN: /p/{args.pack_slug}.json ; "
        "catalogue du portail: /api/public/library"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
