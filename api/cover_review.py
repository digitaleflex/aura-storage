"""Shared helpers for the operator-facing cover review.

The canonical review file stays outside the repository (``AURA_COVER_REVIEW_FILE``).
Only explicitly selected candidates can be published, and every write is atomic.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_HOSTS = (
    "covers.openlibrary.org", ".mzstatic.com",
    "books.google.com", ".googleusercontent.com", ".gstatic.com",
)
AUTHOR_STOPWORDS = {"and", "de", "du", "et", "la", "le", "les", "the"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def review_lock(path: Path):
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        # The API and the host-side scripts run as different UIDs on the same
        # bind mount: keep the lock writable by both.
        os.chmod(lock_path, 0o666)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def review_path() -> Path:
    default = Path(os.environ.get("AURA_DATA_DIR", "/srv/aura-storage")) / "cover-candidates.json"
    return Path(os.environ.get("AURA_COVER_REVIEW_FILE", str(default)))


def host_matches(host: str, rule: str) -> bool:
    host = host.lower().rstrip(".")
    rule = rule.lower().rstrip(".")
    return host == rule or (rule.startswith(".") and host.endswith(rule))


def allowed_cover_url(url: object) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return parsed.scheme == "https" and any(host_matches(host, rule) for rule in ALLOWED_HOSTS)


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    import re

    text = text.casefold().split(":", 1)[0]
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def author_key(value: object) -> str:
    return " ".join(word for word in normalize(value).split() if word not in AUTHOR_STOPWORDS)


def match_class(book: dict, candidate: dict) -> str:
    if normalize(book.get("title")) != normalize(candidate.get("title")):
        return "approx"
    expected = author_key(book.get("author"))
    actual = author_key(candidate.get("author"))
    return "exact" if not expected or expected == actual else "title"


def read_review(path: Path | None = None, *, strict: bool = False) -> dict:
    path = path or review_path()
    if not path.exists():
        if strict:
            raise FileNotFoundError(path)
        return {"generated_at": None, "books": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError(f"revue de couvertures illisible: {path}") from exc
        return {"generated_at": None, "books": []}
    if not isinstance(data, dict) or not isinstance(data.get("books"), list):
        if strict:
            raise ValueError("la revue doit contenir une liste 'books'")
        return {"generated_at": None, "books": []}
    return data


def write_review(review: dict, path: Path | None = None) -> Path:
    """Atomically replace the review so an interruption cannot truncate it."""
    path = path or review_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        # Written by the API UID, read/written later by the operator's scripts.
        tmp.chmod(0o666)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def public_review(review: dict) -> dict:
    """Filter unsafe URLs and add the match badge expected by the admin UI."""
    books = []
    for book in review.get("books", []):
        candidates = [
            {
                "provider": str(candidate.get("provider") or ""),
                "title": str(candidate.get("title") or ""),
                "author": str(candidate.get("author") or ""),
                "url": str(candidate.get("url") or ""),
                "size": str(candidate.get("size") or ""),
                "match": match_class(book, candidate),
            }
            for candidate in (book.get("candidates") or [])
            if isinstance(candidate, dict) and allowed_cover_url(candidate.get("url"))
        ]
        status = str(book.get("status") or "pending")
        cover_key = book.get("cover_key")
        chosen_visible = status in {"selected", "applied", "already_applied"}
        books.append({
            "object_id": str(book.get("object_id") or ""),
            "title": str(book.get("title") or ""),
            "author": str(book.get("author") or ""),
            "display_name": str(book.get("display_name") or ""),
            "status": status,
            "chosen_url": book.get("chosen_url") if chosen_visible else None,
            "cover_url": f"/covers/{book.get('object_id')}.jpg" if cover_key else None,
            "candidates": candidates,
        })
    return {
        "generated_at": review.get("generated_at"),
        "counts": {
            "books": len(books),
            "with_candidates": sum(bool(book["candidates"]) for book in books),
            "candidates": sum(len(book["candidates"]) for book in books),
        },
        "books": books,
    }


def find_book(review: dict, object_id: str) -> dict | None:
    return next((book for book in review.get("books", [])
                 if str(book.get("object_id")) == object_id), None)


def select_cover(review: dict, object_id: str, candidate_url: str | None) -> dict:
    """Record one operator decision without publishing anything."""
    book = find_book(review, object_id)
    if book is None:
        raise LookupError("livre introuvable dans la revue")
    if book.get("status") in {"applied", "already_applied"}:
        raise ValueError("couverture déjà publiée pour ce livre")
    if candidate_url is None:
        if book.get("status") in {"selected", "error"}:
            book["status"] = "pending"
            book["chosen_url"] = None
            book["chosen_candidate"] = None
            book.pop("error", None)
    else:
        candidates = book.get("candidates") or []
        index = next((i for i, candidate in enumerate(candidates)
                      if candidate.get("url") == candidate_url), None)
        if index is None or not allowed_cover_url(candidate_url):
            raise ValueError("candidat invalide ou non autorisé")
        book["status"] = "selected"
        book["chosen_url"] = candidate_url
        book["chosen_candidate"] = index
        book["chosen_provider"] = candidates[index].get("provider")
        book["chosen_size"] = candidates[index].get("size")
        book["chosen_source_url"] = candidates[index].get("source_url")
        book["chosen_license"] = candidates[index].get("license")
        book["chosen_isbn"] = candidates[index].get("isbn")
        book["chosen_query"] = candidates[index].get("query")
        book["chosen_at"] = int(time.time())
        book.pop("error", None)
    review["selection_updated_at"] = int(time.time())
    return book


def fetch_image(url: str) -> bytes | None:
    if not allowed_cover_url(url):
        return None
    from . import cover_enrichment as ce

    try:
        with build_opener(NoRedirect).open(
            Request(url, headers={"User-Agent": "aura-cover-review/1.0"}),
            timeout=ce.TIMEOUT_S,
        ) as response:
            data = response.read(ce.MAX_SOURCE_BYTES + 1)
    except (OSError, ValueError):
        return None
    return data if data and len(data) <= ce.MAX_SOURCE_BYTES else None


def apply_selected(review: dict, *, dry_run: bool = True, limit: int = 50) -> dict:
    """Publish selected candidates, one bounded batch, with resumable progress."""
    from . import cover_enrichment as ce

    selected = [book for book in review.get("books", [])
                if book.get("status") == "selected"][: max(1, min(limit, 500))]
    applied = failed = skipped = 0
    client = None if dry_run else ce.s3_client()
    for book in selected:
        oid = str(book.get("object_id") or "")
        candidate = None
        for entry in book.get("candidates") or []:
            if entry.get("url") == book.get("chosen_url"):
                candidate = entry
                break
        obj = ce.find_object(oid) if oid else None
        if candidate is None or not allowed_cover_url(book.get("chosen_url")) or not obj:
            failed += 1
            if not dry_run:
                book["status"] = "error"
                book["error"] = "candidat périmé ou objet introuvable"
                write_review(review)
            continue
        if obj.get("cover_key"):
            skipped += 1
            if not dry_run:
                book["status"] = "already_applied"
                write_review(review)
            continue
        if dry_run:
            applied += 1
            continue
        try:
            jpeg = ce.resize_image(fetch_image(candidate["url"]) or b"")
            if not jpeg:
                raise ValueError("image illisible")
            key = ce.publish_cover(obj, jpeg, client, apply=True)
        except Exception:
            failed += 1
            book["status"] = "error"
            book["error"] = "téléchargement ou publication impossible"
            write_review(review)
            continue
        applied += 1
        book["status"] = "applied"
        book["cover_key"] = key
        book["chosen_provider"] = candidate.get("provider")
        book["chosen_size"] = candidate.get("size")
        book["chosen_source_url"] = candidate.get("source_url")
        book["chosen_license"] = candidate.get("license")
        book["applied_at"] = int(time.time())
        book.pop("error", None)
        write_review(review)
    return {"applied": applied, "failed": failed, "skipped": skipped, "dry_run": dry_run}
