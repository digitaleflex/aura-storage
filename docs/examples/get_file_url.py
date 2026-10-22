#!/usr/bin/env python3
"""Ask the AURA API for a short-lived URL to a file, then (optionally) fetch it.

Standard library only. Configuration comes from the environment, never from the
command line (a token in argv is visible to every user of the machine):

    export AURA_API=https://app.example.org     # the app host, not the S3 host
    export AURA_TOKEN=aura_...                   # service-identity token (objects:read)

    python3 get_file_url.py --id 7600a54d-595e-4070-a286-010c34d0cba2
    python3 get_file_url.py --search rapport --kind preview
    python3 get_file_url.py --id ... --save out.bin --range 0-1048575
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def api(method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        os.environ["AURA_API"].rstrip("/") + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["AURA_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:200]
        hint = {
            401: "token missing, wrong or expired",
            403: "the identity lacks the objects:read scope",
            404: "no such object in this identity's space",
            409: "the object is not 'available' yet (still uploading or verifying)",
            415: "this content type has no inline preview: use --kind download",
            429: "too many failed authentications from this IP; wait Retry-After seconds",
        }.get(err.code, "")
        sys.exit(f"HTTP {err.code} {hint} {detail}".strip())


def find_id(text: str) -> str:
    """The newest available object whose display name contains `text`."""
    query = urllib.parse.urlencode({"q": text, "status": "available", "limit": 1})
    items = api("GET", "/api/v1/objects?" + query)["items"]
    if not items:
        sys.exit(f"no available object matches {text!r}")
    return items[0]["id"]


def get_url(object_id: str, kind: str) -> dict:
    """kind='download' (attachment) or 'preview' (inline, allow-listed types)."""
    return api("POST", f"/api/v1/objects/{object_id}/{kind}-intent")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", help="object id (UUID)")
    target.add_argument("--search", help="part of the file name")
    parser.add_argument("--kind", choices=["download", "preview"], default="download")
    parser.add_argument("--save", help="write the bytes to this file")
    parser.add_argument("--range", help="bytes to fetch, e.g. 0-1048575")
    args = parser.parse_args()

    intent = get_url(args.id or find_id(args.search), args.kind)
    url = intent.get("download_url") or intent["preview_url"]
    print(f"{intent['display_name']}  {intent['content_type']}  {intent['size_bytes']} bytes")
    ranges = f" (range_supported={intent['range_supported']})" if "range_supported" in intent else ""
    print(f"expires in {intent['expires_in']} s{ranges}")
    if not args.save:
        print(url)  # treat it like a password: it grants read access until it expires
        return

    headers = {"Range": "bytes=" + args.range} if args.range else {}
    # The URL carries its own signature: no Authorization header here.
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response, \
            open(args.save, "wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    print(f"saved to {args.save} (HTTP {response.status})")


if __name__ == "__main__":
    main()
