#!/usr/bin/env python3
"""Prepare or apply book covers from external metadata / an operator file.

Two modes, deliberately separated:

* ``--candidates`` queries public providers (iTunes Search, Open Library) and
  writes a review file. It never publishes anything: an operator checks the
  suggestions (wrong editions and image rights are real risks).
* ``--apply --object-id ID --file PATH`` (or ``--url URL``) publishes one
  chosen image, resizes it with ffmpeg and records ``cover_key`` in the
  catalogue.

Use ``scripts/cover_candidates.sh`` / ``scripts/apply_cover.sh`` to run this
inside the api container, where ffmpeg and the catalogue connection live.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from api import cover_enrichment as ce


def split_title_author(display_name: str) -> tuple[str, str]:
    stem = Path(display_name).stem.strip()
    if " - " in stem:
        author, title = stem.split(" - ", 1)
        return title.strip(), author.strip()
    return stem, ""


def collect_candidates(review: dict, limit: int, provider: str) -> int:
    known = {book.get("object_id"): book for book in review.get("books", [])}
    books = []
    for obj in ce.published_without_cover(limit, include_probed=True):
        title, author = split_title_author(str(obj.get("display_name") or ""))
        found = []
        if provider in ("itunes", "all"):
            found += ce.search_itunes(title, author)
        if provider in ("openlibrary", "all"):
            found += ce.search_openlibrary(title, author)
        seen = set()
        unique = []
        for candidate in found:
            if not candidate.get("url") or candidate["url"] in seen:
                continue
            seen.add(candidate["url"])
            unique.append(candidate)
        previous = known.get(obj["id"], {})
        books.append({
            "object_id": obj["id"],
            "title": title,
            "author": author,
            "display_name": obj.get("display_name"),
            "candidates": unique,
            "status": previous.get("status", "pending"),
            "chosen_url": previous.get("chosen_url"),
        })
    review["books"] = books
    review["generated_at"] = int(time.time())
    return sum(len(book["candidates"]) for book in books)


def mark_applied(review: dict, object_id: str, source: str) -> None:
    for book in review.get("books", []):
        if book.get("object_id") == object_id:
            book["status"] = "applied"
            book["chosen_url"] = source
            return
    review.setdefault("books", []).append({
        "object_id": object_id, "status": "applied", "chosen_url": source,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", action="store_true",
                        help="write a review file, never publish")
    parser.add_argument("--apply", action="store_true", help="publish one chosen image")
    parser.add_argument("--object-id", help="object id to publish for --apply")
    parser.add_argument("--file", help="local image path (inside the api container)")
    parser.add_argument("--url", help="image URL to download")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--provider", choices=("itunes", "openlibrary", "all"), default="all")
    args = parser.parse_args()

    if args.apply == args.candidates:
        parser.error("choose exactly one of --candidates or --apply")

    review = ce.read_review()
    if args.candidates:
        count = collect_candidates(review, args.limit, args.provider)
        path = ce.write_review(review)
        print(f"{count} candidat(s) pour {len(review['books'])} livre(s) -> {path}")
        print("Aucune image n'a ete publiee. Verifiez le fichier puis utilisez --apply.")
        return 0

    if not args.object_id or bool(args.file) == bool(args.url):
        parser.error("--apply requires --object-id and exactly one of --file or --url")
    obj = ce.find_object(args.object_id)
    if not obj:
        parser.error(f"objet inconnu: {args.object_id}")
    data = Path(args.file).read_bytes() if args.file else ce.fetch_url(args.url)
    if not data:
        parser.error("image introuvable ou trop volumineuse")
    jpeg = ce.resize_image(data)
    if not jpeg:
        parser.error("image illisible par ffmpeg")
    key = ce.publish_cover(obj, jpeg, ce.s3_client(), apply=True)
    mark_applied(review, args.object_id, args.file or args.url or "")
    ce.write_review(review)
    print(f"couverture publiee pour {obj.get('display_name')}: {key}")
    print(f"/covers/{obj['id']}.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
