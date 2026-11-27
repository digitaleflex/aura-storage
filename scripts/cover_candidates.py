#!/usr/bin/env python3
"""Prepare, review and apply book covers from external metadata.

Three deliberately separated modes:

* ``--candidates`` queries public providers (iTunes Search, Open Library) and
  writes a review file. It never publishes anything: an operator checks the
  suggestions (wrong editions and image rights are real risks).
* ``--apply-selected`` publishes every review entry explicitly marked
  ``selected``. Only HTTPS URLs already present in that entry's candidate list
  are accepted, and only known cover hosts are allowed. ``--dry-run`` validates
  the batch without downloading or publishing an image.
* ``--apply --object-id ID --file PATH`` (or ``--url URL``) publishes one
  operator-chosen image, resizes it with ffmpeg and records ``cover_key`` in the
  catalogue.

Use ``scripts/cover_candidates.sh`` / ``scripts/apply_cover_candidates.sh`` to
run this inside the api container, where ffmpeg and the catalogue connection
live.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from api import cover_enrichment as ce

COVER_HOST_RULES = (
    "covers.openlibrary.org", ".mzstatic.com",
    "books.google.com", ".googleusercontent.com", ".gstatic.com",
)
REVIEW_STATE_FIELDS = (
    "status", "chosen_url", "chosen_candidate", "chosen_provider",
    "cover_key", "applied_at", "error",
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def reject_constant(value: str):
    raise ValueError(f"valeur JSON non autorisee: {value}")


def host_matches(host: str, rule: str) -> bool:
    host = host.lower().rstrip(".")
    rule = rule.lower().rstrip(".")
    return host == rule or (rule.startswith(".") and host.endswith(rule))


def read_review_file(path: Path, *, strict: bool = False) -> dict:
    if not path.exists():
        if strict:
            raise FileNotFoundError(path)
        return {"generated_at": None, "books": []}
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_constant,
        )
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError(f"fichier de revue illisible: {path}") from exc
        return {"generated_at": None, "books": []}
    if not isinstance(data, dict) or not isinstance(data.get("books"), list):
        if strict:
            raise ValueError("le fichier de revue doit contenir une liste 'books'")
        return {"generated_at": None, "books": []}
    for book in data["books"]:
        if not isinstance(book, dict):
            if strict:
                raise ValueError("entree de livre non objet")
            return {"generated_at": None, "books": []}
        candidates = book.get("candidates", [])
        if candidates is not None and (
            not isinstance(candidates, list)
            or any(not isinstance(candidate, dict) for candidate in candidates)
        ):
            if strict:
                raise ValueError("candidat non objet")
            return {"generated_at": None, "books": []}
    return data


def write_review(review: dict) -> Path:
    """Atomically replace the review file so interruption cannot truncate it."""
    path = ce.review_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(review, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def fetch_selected_cover(url: str) -> bytes | None:
    """Fetch only from approved HTTPS hosts, without following redirects."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme != "https" or not any(host_matches(host, rule) for rule in COVER_HOST_RULES):
        return None
    request = Request(url, headers={"User-Agent": ce.USER_AGENT})
    try:
        with build_opener(_NoRedirect).open(request, timeout=ce.TIMEOUT_S) as response:
            data = response.read(ce.MAX_SOURCE_BYTES + 1)
    except (OSError, ValueError):
        return None
    return data if data and len(data) <= ce.MAX_SOURCE_BYTES else None


def split_title_author(display_name: str) -> tuple[str, str]:
    stem = Path(display_name).stem.strip()
    if " - " in stem:
        author, title = stem.split(" - ", 1)
        return title.strip(), author.strip()
    return stem, ""


def collect_candidates(review: dict, limit: int, provider: str) -> int:
    previous_books = review.get("books", [])
    known = {book.get("object_id"): book for book in previous_books}
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
        if (previous.get("status") in {"selected", "error"}
                and previous.get("chosen_url")):
            chosen_url = previous["chosen_url"]
            if not any(candidate.get("url") == chosen_url for candidate in unique):
                old_candidate = next(
                    (candidate for candidate in (previous.get("candidates") or [])
                     if candidate.get("url") == chosen_url),
                    None,
                )
                if old_candidate:
                    unique.append(dict(old_candidate))
        entry = {
            "object_id": obj["id"],
            "title": title,
            "author": author,
            "display_name": obj.get("display_name"),
            "candidates": unique,
            "status": previous.get("status", "pending"),
            "chosen_url": previous.get("chosen_url"),
        }
        for field in REVIEW_STATE_FIELDS:
            if field in previous:
                entry[field] = previous[field]
        if entry.get("status") in {"selected", "error"} and entry.get("chosen_url"):
            chosen_index = next(
                (i for i, candidate in enumerate(unique)
                 if candidate.get("url") == entry["chosen_url"]),
                None,
            )
            if chosen_index is None:
                if entry.get("status") == "selected":
                    entry["status"] = "pending"
                entry["chosen_url"] = None
                entry.pop("chosen_candidate", None)
                entry["error"] = "candidat selectionne introuvable apres actualisation"
            else:
                entry["chosen_candidate"] = chosen_index
        books.append(entry)

    candidate_count = sum(len(book["candidates"]) for book in books)
    # A bounded query must not erase reviewed/applied books or books outside the
    # current limit. Keep their history and append only genuinely new entries.
    seen = {book.get("object_id") for book in books}
    books.extend(book for book in previous_books if book.get("object_id") not in seen)
    review["books"] = books
    review["generated_at"] = int(time.time())
    return candidate_count


def mark_applied(review: dict, object_id: str, source: str) -> None:
    for book in review.get("books", []):
        if book.get("object_id") == object_id:
            book["status"] = "applied"
            book["chosen_url"] = source
            book["applied_at"] = int(time.time())
            book.pop("error", None)
            return
    review.setdefault("books", []).append({
        "object_id": object_id,
        "status": "applied",
        "chosen_url": source,
        "applied_at": int(time.time()),
    })


def selected_candidate(book: dict) -> dict | None:
    """Return the reviewed candidate, or reject an unsafe/stale selection."""
    if book.get("status") != "selected":
        return None
    url = str(book.get("chosen_url") or "")
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    if not any(host_matches(host, rule) for rule in COVER_HOST_RULES):
        return None
    for candidate in book.get("candidates") or []:
        if candidate.get("url") == url:
            return candidate
    return None


def apply_selected(
    review: dict, *, apply: bool = True, limit: int | None = None,
) -> tuple[int, int, int]:
    """Apply explicitly selected candidates; return (done, failed, skipped).

    The review file is saved after every applied book so an interrupted batch
    can be resumed. In dry-run mode nothing is downloaded, written or published.
    """
    selected = [book for book in review.get("books", [])
                if book.get("status") == "selected"]
    if limit is not None:
        selected = selected[:limit]
    client = ce.s3_client() if apply else None
    done = failed = skipped = 0

    for book in selected:
        object_id = str(book.get("object_id") or "")
        candidate = selected_candidate(book)
        obj = ce.find_object(object_id) if object_id else None
        problem = ""
        if not candidate:
            problem = "candidat absent de la liste ou URL non autorisee"
        elif not obj:
            problem = "objet introuvable"

        if problem:
            failed += 1
            if apply:
                book["status"] = "error"
                book["error"] = problem
                write_review(review)
            else:
                print(f"  REFUSE: {book.get('title') or object_id}: {problem}")
            continue

        # A generated AURA jacket is a placeholder that an approved real cover
        # may replace; never overwrite a real cover from a review selection.
        if obj.get("cover_key") and not ce.is_generated_cover(obj["cover_key"]):
            skipped += 1
            if apply:
                book["status"] = "already_applied"
                book.pop("error", None)
                write_review(review)
            else:
                print(f"  DEJA FAIT: {book.get('title') or object_id}")
            continue

        if not apply:
            done += 1
            print(
                f"  PRET: {book.get('title') or object_id} -> "
                f"{candidate.get('provider')} {candidate['url']}"
            )
            continue

        try:
            data = fetch_selected_cover(candidate["url"])
            jpeg = ce.resize_image(data or b"")
        except Exception:
            jpeg = None
        if not jpeg:
            failed += 1
            book["status"] = "error"
            book["error"] = "image introuvable, trop volumineuse ou illisible"
            write_review(review)
            print(f"  ECHEC: {book.get('title') or object_id}: {book['error']}")
            continue

        try:
            key = ce.publish_cover(obj, jpeg, client, apply=True)
        except Exception as exc:  # keep processing the rest of an operator batch
            failed += 1
            book["status"] = "error"
            book["error"] = f"publication impossible: {exc}"
            write_review(review)
            print(f"  ECHEC: {book.get('title') or object_id}: {book['error']}")
            continue

        done += 1
        book["status"] = "applied"
        book["chosen_provider"] = candidate.get("provider")
        book["cover_key"] = key
        book["applied_at"] = int(time.time())
        book.pop("error", None)
        write_review(review)
        print(f"  PUBLIE: {book.get('title') or object_id} -> {key}")

    return done, failed, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidates", action="store_true",
                      help="write a review file, never publish")
    mode.add_argument("--apply-selected", action="store_true",
                      help="publish every review entry marked selected")
    mode.add_argument("--apply", action="store_true", help="publish one chosen image")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --apply-selected, validate without publishing")
    parser.add_argument("--review-input", type=Path,
                        help="selection file to read for --apply-selected")
    parser.add_argument("--object-id", help="object id to publish for --apply")
    parser.add_argument("--file", help="local image path (inside the api container)")
    parser.add_argument("--url", help="image URL to download")
    parser.add_argument("--limit", type=int, default=20,
                        help="maximum books to query with --candidates")
    parser.add_argument("--selected-limit", type=int,
                        help="maximum selected books to process with --apply-selected")
    parser.add_argument("--provider", choices=("itunes", "openlibrary", "all"), default="all")
    args = parser.parse_args()

    if args.dry_run and not args.apply_selected:
        parser.error("--dry-run requires --apply-selected")
    if args.review_input and not args.apply_selected:
        parser.error("--review-input requires --apply-selected")
    if args.selected_limit is not None and args.selected_limit < 1:
        parser.error("--selected-limit must be positive")

    if args.apply_selected:
        review = (read_review_file(args.review_input, strict=True) if args.review_input
                  else read_review_file(ce.review_path(), strict=True))
    else:
        review = read_review_file(ce.review_path(), strict=ce.review_path().exists())
    if args.candidates:
        count = collect_candidates(review, args.limit, args.provider)
        path = write_review(review)
        print(f"{count} candidat(s) pour {len(review['books'])} livre(s) -> {path}")
        print("Aucune image n'a ete publiee. Verifiez le fichier puis utilisez --apply.")
        return 0

    if args.apply_selected:
        done, failed, skipped = apply_selected(
            review, apply=not args.dry_run, limit=args.selected_limit,
        )
        if not args.dry_run:
            # Persist merged clears/selection metadata even when the batch is
            # empty or every selected book was already covered.
            write_review(review)
        action = "a publier" if args.dry_run else "publiees"
        print(
            f"couvertures: {done} {action}, {failed} en echec, "
            f"{skipped} deja couvertes ({'DRY-RUN' if args.dry_run else 'APPLIQUE'})"
        )
        return 1 if failed else 0

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
    write_review(review)
    print(f"couverture publiee pour {obj.get('display_name')}: {key}")
    print(f"/covers/{obj['id']}.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
