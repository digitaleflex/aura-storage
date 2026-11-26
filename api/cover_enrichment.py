"""Cover enrichment helpers for published audiobooks.

Everything that needs ffmpeg/ffprobe or the catalogue lives here so the small
operator scripts can be piped into the api container (see
``scripts/refresh_public_library.sh``) without copying scripts into the image.

Three sources are supported, in increasing order of trust:

* artwork embedded in the audio file (all attached picture streams, not only
  the first video stream);
* an image object stored next to the audio object in the same bucket;
* external metadata providers, used only to produce a review file. An operator
  must explicitly choose a candidate before it is published.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("AURA_REPO_ROOT", str(Path.cwd())))
_env_file = ROOT / ".env"
for _line in (_env_file.read_text(encoding="utf-8").splitlines() if _env_file.exists() else []):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if os.environ.get("S3_API_ACCESS_KEY"):
    os.environ.setdefault("AURA_S3_ACCESS_KEY", os.environ["S3_API_ACCESS_KEY"])
    os.environ.setdefault("AURA_S3_SECRET_KEY", os.environ["S3_API_SECRET_KEY"])
if os.environ.get("S3_DOMAIN"):
    os.environ.setdefault("AURA_S3_ENDPOINT", f"https://{os.environ['S3_DOMAIN']}")
if (not os.environ.get("AURA_API_BACKEND") and not os.environ.get("AURA_API_DB")
        and os.environ.get("POSTGRES_USER")):
    from urllib.parse import quote_plus
    os.environ["AURA_API_BACKEND"] = "postgres"
    os.environ["AURA_API_DSN"] = "postgresql://{u}:{p}@localhost:5432/{db}".format(
        u=quote_plus(os.environ["POSTGRES_USER"]),
        p=quote_plus(os.environ.get("POSTGRES_PASSWORD", "")),
        db=os.environ.get("POSTGRES_DB", "aura"),
    )

import boto3  # noqa: E402

from api.config import settings  # noqa: E402
from api.s3 import SSE_ALGORITHM, presigned_get  # noqa: E402
from api.store import repo  # noqa: E402

AUDIO_TYPES = ("audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/flac", "audio/aac")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif")
COVER_NAMES = {"cover", "folder", "albumart", "album", "front", "artwork", "jacket"}
COVER_WIDTH = 480
TIMEOUT_S = 60
MAX_SOURCE_BYTES = 12 * 1024 * 1024
USER_AGENT = "aura-cover-enrichment/1.0"


def placeholder() -> str:
    return "?" if settings.db_backend == "sqlite" else "%s"


def published_without_cover(limit: int, include_probed: bool = False) -> list[dict]:
    """Published audio objects with no cover, oldest first."""
    marks = ",".join(placeholder() for _ in AUDIO_TYPES)
    sql = (
        "SELECT * FROM objects WHERE status = 'available' AND published_at IS NOT NULL "
        f"AND cover_key IS NULL AND content_type IN ({marks})"
    )
    if not include_probed:
        sql += " AND cover_probe_at IS NULL"
    sql += f" ORDER BY created_at ASC LIMIT {placeholder()}"
    rows = repo.conn.execute(sql, (*AUDIO_TYPES, limit)).fetchall()
    return [dict(row) for row in rows]


def find_object(object_id: str) -> dict | None:
    row = repo.conn.execute(
        f"SELECT * FROM objects WHERE id = {placeholder()}", (object_id,)
    ).fetchone()
    return dict(row) if row else None


def image_objects(bucket: str) -> list[dict]:
    marks = ",".join(placeholder() for _ in IMAGE_TYPES)
    rows = repo.conn.execute(
        f"SELECT bucket, object_key, content_type, size_bytes FROM objects "
        f"WHERE bucket = {placeholder()} AND content_type IN ({marks})",
        (bucket, *IMAGE_TYPES),
    ).fetchall()
    return [dict(row) for row in rows]


def sibling_candidates(obj: dict, images: list[dict]) -> list[dict]:
    """Rank images stored beside the audio object (same directory)."""
    key = str(obj.get("object_key") or "")
    directory = key.rsplit("/", 1)[0] + "/" if "/" in key else ""
    stem = Path(key).stem.lower()
    ranked = []
    for image in images:
        image_key = str(image.get("object_key") or "")
        if not image_key.startswith(directory):
            continue
        name = image_key[len(directory):].lower()
        name_stem = Path(name).stem
        if name_stem == stem or name_stem.startswith(stem + "."):
            score = 100
        elif name_stem in COVER_NAMES:
            score = 50
        elif stem and stem in name_stem:
            score = 20
        else:
            continue
        ranked.append({**image, "_score": score})
    ranked.sort(key=lambda row: (-row["_score"], -(row.get("size_bytes") or 0)))
    return [{k: v for k, v in row.items() if k != "_score"} for row in ranked]


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def fetch_url(url: str, max_bytes: int = MAX_SOURCE_BYTES) -> bytes | None:
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=TIMEOUT_S) as resp:
            data = resp.read(max_bytes + 1)
    except (OSError, ValueError):
        return None
    return data if data and len(data) <= max_bytes else None


def resize_image(data: bytes) -> bytes | None:
    """Downscale any FFmpeg-readable image to a bounded JPEG."""
    if not data:
        return None
    cmd = [
        "ffmpeg", "-v", "error", "-f", "image2pipe", "-i", "pipe:0",
        "-vf", f"scale={COVER_WIDTH}:-2", "-frames:v", "1",
        "-f", "mjpeg", "-q:v", "4", "pipe:1",
    ]
    try:
        result = subprocess.run(cmd, input=data, capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    jpeg = result.stdout or b""
    if result.returncode == 0 and len(jpeg) >= 1024 and jpeg.startswith(b"\xff\xd8"):
        return jpeg
    return None


def embedded_indices(url: str, max_streams: int = 3) -> list[int]:
    """Indexes of the first video/attached-picture streams in an audio file."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v",
        "-show_entries", "stream=index", "-of", "csv=p=0", url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [int(line.strip()) for line in result.stdout.decode().splitlines()
            if line.strip().isdigit()][:max_streams]


def extract_embedded(url: str, max_streams: int = 3) -> bytes | None:
    """Try every early video stream, not just the first one."""
    indexes = embedded_indices(url, max_streams)
    if not indexes:
        indexes = [None]  # older ffprobe output: let ffmpeg pick the first video
    for index in indexes:
        cmd = ["ffmpeg", "-v", "error", "-i", url]
        cmd += ["-map", f"0:{index}"] if index is not None else ["-map", "0:v:0"]
        cmd += [
            "-frames:v", "1", "-vf", f"scale={COVER_WIDTH}:-2",
            "-f", "mjpeg", "-q:v", "4", "pipe:1",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            continue
        jpeg = result.stdout or b""
        if result.returncode == 0 and len(jpeg) >= 1024 and jpeg.startswith(b"\xff\xd8"):
            return jpeg
    return None


def publish_cover(obj: dict, jpeg: bytes, client, apply: bool) -> str:
    """Store the resized JPEG next to the object and record it in the catalogue."""
    key = f"{obj['object_key']}.cover.jpg"
    if apply:
        extra = {"ServerSideEncryption": SSE_ALGORITHM} if settings.require_sse else {}
        client.put_object(
            Bucket=obj["bucket"], Key=key, Body=jpeg,
            ContentType="image/jpeg", **extra,
        )
        repo.set_object_cover(obj["id"], key)
        repo.mark_media_probe(obj["id"], "cover", int(time.time()))
    return key


def mark_miss(obj: dict, apply: bool) -> None:
    if apply:
        repo.mark_media_probe(obj["id"], "cover", int(time.time()))


def search_itunes(title: str, author: str = "", limit: int = 3) -> list[dict]:
    """Public iTunes Search API; no key or account required."""
    payload = fetch_url("https://itunes.apple.com/search?" + urlencode({
        "term": " ".join(part for part in (author, title) if part),
        "entity": "audiobook", "limit": limit, "country": "FR",
    }))
    if not payload:
        return []
    try:
        results = json.loads(payload).get("results", [])
    except (ValueError, AttributeError):
        return []
    return [
        {
            "provider": "itunes",
            "title": str(row.get("collectionName") or row.get("trackName") or ""),
            "author": str(row.get("artistName") or ""),
            "url": str(row.get("artworkUrl100") or "").replace("100x100bb", "600x600bb"),
            "size": "600",
            "source_url": str(row.get("collectionViewUrl") or row.get("trackViewUrl") or ""),
        }
        for row in results if row.get("artworkUrl100")
    ]


def search_openlibrary(title: str, author: str = "", limit: int = 3) -> list[dict]:
    """Open Library search; cover ids are served by covers.openlibrary.org."""
    payload = fetch_url("https://openlibrary.org/search.json?" + urlencode({
        "title": title, "author": author, "limit": limit,
    }))
    if not payload:
        return []
    try:
        results = json.loads(payload).get("docs", [])
    except (ValueError, AttributeError):
        return []
    return [
        {
            "provider": "openlibrary",
            "title": str(row.get("title") or ""),
            "author": ", ".join(str(a) for a in (row.get("author_name") or [])[:2]),
            "url": f"https://covers.openlibrary.org/b/id/{row['cover_i']}-L.jpg",
            "size": "L",
            "source_url": f"https://openlibrary.org{row.get('key') or ''}",
        }
        for row in results if row.get("cover_i")
    ]


def search_google_books(
    title: str, author: str = "", isbn: str = "", limit: int = 5,
) -> list[dict]:
    """Google Books (primary source); optional API key avoids a shared quota.

    Without a key the public endpoint is heavily rate limited: an empty list
    simply lets the caller fall back to the secondary providers.
    """
    if isbn:
        query = f"isbn:{isbn.strip()}"
    else:
        parts = []
        if title.strip():
            parts.append(f'intitle:"{title.strip()}"')
        if author.strip():
            parts.append(f'inauthor:"{author.strip()}"')
        query = " ".join(parts) or title or author
    params = {"q": query, "maxResults": max(1, min(limit, 20))}
    api_key = os.environ.get("AURA_GOOGLE_BOOKS_API_KEY", "").strip()
    if api_key:
        params["key"] = api_key
    payload = fetch_url(
        "https://www.googleapis.com/books/v1/volumes?" + urlencode(params),
    )
    if not payload:
        return []
    try:
        items = json.loads(payload).get("items", [])
    except (ValueError, AttributeError):
        return []
    candidates = []
    for row in items:
        if not isinstance(row, dict):
            continue
        info = row.get("volumeInfo") or {}
        links = info.get("imageLinks") or {}
        url = ""
        size = ""
        for name in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            if links.get(name):
                url, size = str(links[name]), name
                break
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        if not url:
            continue
        isbns = [
            str(entry.get("identifier") or "")
            for entry in (info.get("industryIdentifiers") or [])
            if isinstance(entry, dict)
        ]
        candidates.append({
            "provider": "google_books",
            "title": str(info.get("title") or ""),
            "author": ", ".join(str(a) for a in (info.get("authors") or [])[:2]),
            "url": url,
            "size": size,
            "isbn": isbn.strip() or next((value for value in isbns if value), ""),
            "source_url": f"https://books.google.com/books?id={row.get('id')}",
            "license": str(info.get("copyright") or ""),
            "query": query,
        })
    return candidates


def search_candidates(
    title: str, author: str = "", isbn: str = "", limit: int = 5,
) -> list[dict]:
    """Google Books first, then Open Library, then iTunes as a last resort."""
    found = search_google_books(title, author, isbn, limit)
    found += search_openlibrary(title, author, limit)
    if not isbn and not found:
        found += search_itunes(title, author, limit)
    seen = set()
    unique = []
    for candidate in found:
        if candidate.get("url") in seen:
            continue
        seen.add(candidate.get("url"))
        unique.append(candidate)
    return unique[: max(1, min(limit * 3, 60))]


def review_path() -> Path:
    default = Path(os.environ.get("AURA_DATA_DIR", "/srv/aura-storage")) / "cover-candidates.json"
    return Path(os.environ.get("AURA_COVER_REVIEW_FILE", str(default)))


def read_review() -> dict:
    path = review_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("books"), list):
                return data
        except (OSError, ValueError):
            pass
    return {"generated_at": None, "books": []}


def write_review(review: dict) -> Path:
    path = review_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
