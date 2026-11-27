#!/usr/bin/env python3
"""Select cover candidates automatically using conservative, auditable rules.

This script NEVER publishes by itself. It writes a selections JSON compatible
with scripts/apply_cover_candidates.sh. Default mode is dry-run/report only.

Rules (all required for auto-selection):
- book is not already applied/already_applied
- candidate URL is HTTPS and host is allowed (Open Library Covers, iTunes/Apple)
- normalized title matches exactly
- normalized author matches exactly when book author is known
- exactly one candidate matches these rules for the book
- no ambiguous exact-title candidate by a different author
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

APPLIED_STATES = {"applied", "already_applied"}
AUTHOR_STOPWORDS = {"and", "de", "du", "et", "la", "le", "les", "the"}
# Keep in sync with api/cover_review.ALLOWED_HOSTS: Google Books candidates
# are reviewable and publishable, so they must be auto-selectable too.
ALLOWED_HOSTS = (
    "covers.openlibrary.org", ".mzstatic.com",
    "books.google.com", ".googleusercontent.com", ".gstatic.com",
)


def reject_constant(value: str):
    raise ValueError(f"valeur JSON non autorisee: {value}")


def load_review(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict) or not isinstance(data.get("books"), list):
        raise ValueError(f"{path}: liste 'books' absente")
    return data


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().split(":", 1)[0]
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def author_key(value: object) -> str:
    return " ".join(w for w in normalize(value).split() if w not in AUTHOR_STOPWORDS)


def allowed_cover_url(url: object) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    return any(host == rule or (rule.startswith(".") and host.endswith(rule)) for rule in ALLOWED_HOSTS)


def exact_title(book: dict, candidate: dict) -> bool:
    return normalize(book.get("title")) == normalize(candidate.get("title"))


def author_ok(book: dict, candidate: dict) -> bool:
    expected = author_key(book.get("author"))
    if not expected:
        return True
    actual = author_key(candidate.get("author"))
    return bool(actual) and expected == actual


def decide(book: dict) -> tuple[dict | None, str]:
    if book.get("status") in APPLIED_STATES:
        return None, "already_applied"
    candidates = [c for c in (book.get("candidates") or []) if isinstance(c, dict)]
    candidates = [c for c in candidates if allowed_cover_url(c.get("url"))]
    if not candidates:
        return None, "no_allowed_candidate"

    title_matches = [c for c in candidates if exact_title(book, c)]
    if not title_matches:
        return None, "no_exact_title"

    strong = [c for c in title_matches if author_ok(book, c)]
    if len(strong) != 1:
        return None, "ambiguous_or_author_mismatch"

    # Reject when another exact-title candidate exists for a different author;
    # this catches wrong editions/collections with same title.
    expected = author_key(book.get("author"))
    if expected:
        conflicting = [
            c for c in title_matches
            if c is not strong[0] and author_key(c.get("author")) and author_key(c.get("author")) != expected
        ]
        if conflicting:
            return None, "conflicting_exact_title_authors"

    pick = strong[0]
    return pick, "exact_title_author"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path, help="canonical cover-candidates.json")
    parser.add_argument("--output", type=Path, required=True, help="selections JSON to write")
    parser.add_argument("--report", type=Path, help="optional JSON audit report")
    parser.add_argument("--limit", type=int, default=0, help="max auto-selections (0 = no limit)")
    args = parser.parse_args()

    review = load_review(args.review)
    now = int(time.time())
    selected_books = []
    report_items = []
    selected_count = 0

    for book in review.get("books", []):
        if not isinstance(book, dict):
            continue
        pick, reason = decide(book)
        item = {
            "object_id": book.get("object_id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "status": book.get("status"),
            "decision": "selected" if pick else "skipped",
            "reason": reason,
        }
        if pick:
            if args.limit and selected_count >= args.limit:
                item["decision"] = "skipped"
                item["reason"] = "limit_reached"
            else:
                item["chosen_url"] = pick.get("url")
                item["provider"] = pick.get("provider")
                item["candidate_title"] = pick.get("title")
                item["candidate_author"] = pick.get("author")
                selected_books.append({
                    "object_id": book.get("object_id"),
                    "status": "selected",
                    "chosen_url": pick.get("url"),
                })
                selected_count += 1
        report_items.append(item)

    selections = {
        "exported_at": now,
        "generated_at": review.get("generated_at"),
        "selection_updated_at": review.get("selection_updated_at"),
        "auto_selected": True,
        "rules": "exact_title_author_single_match_allowed_host",
        "books": selected_books,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selections, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    report = {
        "generated_at": now,
        "review": str(args.review),
        "selected": selected_count,
        "skipped": len(report_items) - selected_count,
        "items": report_items,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"selected={selected_count} skipped={report['skipped']} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
