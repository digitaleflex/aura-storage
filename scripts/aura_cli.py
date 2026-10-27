#!/usr/bin/env python3
"""Small operator CLI for AURA (M2M token, no browser).

Usage:
  export AURA_BASE_URL=https://app.example.com
  export AURA_TOKEN=aura_<id>_<secret>
  scripts/aura_cli.py list [--tag maths]
  scripts/aura_cli.py upload ./cours.mp4 --publish maths-l1-intro
  scripts/aura_cli.py publish <object_id> maths-l1-intro
  scripts/aura_cli.py pack-create maths-l1 "Maths L1"
  scripts/aura_cli.py pack-items maths-l1 <oid> <oid> ...
  scripts/aura_cli.py pack-publish maths-l1
  scripts/aura_cli.py manifest maths-l1
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("AURA_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("AURA_TOKEN", "")


def call(method: str, path: str, payload=None, *, auth=True, raw=None, headers=None):
    if not BASE:
        sys.exit("AURA_BASE_URL is required")
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode()
        hdrs["content-type"] = "application/json"
    elif raw is not None:
        data = raw
    if auth:
        if not TOKEN:
            sys.exit("AURA_TOKEN is required")
        hdrs["authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            body = res.read()
            return res.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"HTTP {exc.code} on {method} {path}: {body[:400]}")


def cmd_list(args):
    query = "?limit=100"
    if args.tag:
        query += f"&tag={urllib.parse.quote(args.tag)}"
    _, data = call("GET", "/api/v1/objects" + query)
    for item in data["items"]:
        print(f"{item['id']}  {item['status']:10} {item['size_bytes']:>12}  "
              f"{item['content_type']:24} {item['display_name']}")


def cmd_upload(args):
    path = Path(args.file)
    size = path.stat().st_size
    ctype = args.type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    _, intent = call("POST", "/api/v1/objects/upload-intents", {
        "display_name": args.name or path.name,
        "content_type": ctype,
        "size_bytes": size,
    })
    headers = dict(intent["headers"])
    with urllib.request.urlopen(
        urllib.request.Request(
            intent["upload_url"], data=path.read_bytes(), headers=headers, method="PUT"
        ),
        timeout=3600,
    ) as res:
        if res.status not in (200, 201):
            sys.exit(f"upload failed: HTTP {res.status}")
    status, committed = call("POST", f"/api/v1/objects/{intent['id']}/commit")
    print(f"uploaded {intent['id']} ({status})")
    if args.publish:
        call("PUT", f"/api/v1/objects/{intent['id']}/publication",
             {"slug": args.publish, "published": True})
        print(f"published {BASE}/m/{args.publish}")


def cmd_publish(args):
    call("PUT", f"/api/v1/objects/{args.object_id}/publication",
         {"slug": args.slug, "published": True})
    print(f"{BASE}/m/{args.slug}")


def _collections():
    _, data = call("GET", "/api/v1/collections")
    return {c["slug"]: c for c in data["items"]}


def cmd_pack_create(args):
    _, created = call("POST", "/api/v1/collections",
                      {"slug": args.slug, "title": args.title})
    print(created["id"])


def cmd_pack_items(args):
    packs = _collections()
    if args.slug not in packs:
        sys.exit(f"unknown pack: {args.slug}")
    call("PUT", f"/api/v1/collections/{packs[args.slug]['id']}/items",
         {"object_ids": args.object_ids})
    print(f"{len(args.object_ids)} item(s) in {args.slug}")


def cmd_pack_publish(args):
    packs = _collections()
    if args.slug not in packs:
        sys.exit(f"unknown pack: {args.slug}")
    call("PATCH", f"/api/v1/collections/{packs[args.slug]['id']}", {"published": True})
    print(f"{BASE}/p/{args.slug}.json")


def cmd_manifest(args):
    _, data = call("GET", f"/p/{args.slug}.json", auth=False)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list")
    p.add_argument("--tag")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("upload")
    p.add_argument("file")
    p.add_argument("--name")
    p.add_argument("--type")
    p.add_argument("--publish", metavar="SLUG")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("publish")
    p.add_argument("object_id")
    p.add_argument("slug")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("pack-create")
    p.add_argument("slug")
    p.add_argument("title")
    p.set_defaults(func=cmd_pack_create)

    p = sub.add_parser("pack-items")
    p.add_argument("slug")
    p.add_argument("object_ids", nargs="+")
    p.set_defaults(func=cmd_pack_items)

    p = sub.add_parser("pack-publish")
    p.add_argument("slug")
    p.set_defaults(func=cmd_pack_publish)

    p = sub.add_parser("manifest")
    p.add_argument("slug")
    p.set_defaults(func=cmd_manifest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
