#!/usr/bin/env python3
"""Idempotently ensure Cloudflare HTTPS (SVCB) records advertise HTTP/3.

Reads CLOUDFLARE_API_TOKEN from the environment or .env. Never prints secrets.
Dry-run by default: pass --apply to create/update records.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST_KEYS = ("S3_DOMAIN", "APP_DOMAIN", "PUBLIC_DOMAIN", "DASHBOARD_DOMAIN", "SWAGGER_DOMAIN")


def load_dotenv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def cfg(name: str, dotenv: dict[str, str]) -> str:
    return os.environ.get(name) or dotenv.get(name, "")


def cf_request(token: str, method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"Cloudflare API {method} {path}: {exc.code}: {detail[:200]}") from exc
    if not body.get("success"):
        raise SystemExit(f"Cloudflare API {method} {path}: {body.get('errors')}")
    return body


def desired_record(name: str) -> dict:
    return {
        "type": "HTTPS",
        "name": name,
        "data": {"priority": 1, "target": ".", "value": "alpn=\"h3,h2\""},
        "ttl": 1,
    }


def same_record(current: dict, wanted: dict) -> bool:
    cur = current.get("data") or {}
    want = wanted["data"]
    return (
        current.get("type") == "HTTPS"
        and current.get("name") == wanted["name"]
        and int(cur.get("priority", -1)) == int(want["priority"])
        and str(cur.get("target", "")).rstrip(".") == str(want["target"]).rstrip(".")
        and 'alpn="h3,h2"' in str(cur.get("value", "")).replace(" ", "").lower().replace("'", '"')
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="create/update records (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op (default)")
    parser.add_argument("--zone", help="Cloudflare zone name or id")
    parser.add_argument("--hosts", nargs="*", help="hostnames (default: *_DOMAIN from .env)")
    args = parser.parse_args()

    dotenv = load_dotenv(ROOT / ".env")
    token = cfg("CLOUDFLARE_API_TOKEN", dotenv) or cfg("CF_API_TOKEN", dotenv)
    if not token:
        print("CLOUDFLARE_API_TOKEN missing; cannot inspect or update DNS.", file=sys.stderr)
        return 2

    hosts = args.hosts or [cfg(k, dotenv) for k in DEFAULT_HOST_KEYS]
    hosts = [h for i, h in enumerate(hosts) if h and h not in hosts[:i]]
    if not hosts:
        print("No hostnames found.", file=sys.stderr)
        return 2

    zone_arg = args.zone or cfg("CLOUDFLARE_ZONE_ID", dotenv) or cfg("CLOUDFLARE_ZONE", dotenv)
    if not zone_arg:
        # Derive zone from longest matching suffix by listing zones; fallback: last two labels.
        zone_arg = ".".join(hosts[0].split(".")[-2:])
    zones = cf_request(token, "GET", f"/zones?{urllib.parse.urlencode({'name': zone_arg, 'per_page': 50})}")
    results = zones.get("result", [])
    if not results:
        zones = cf_request(token, "GET", f"/zones?{urllib.parse.urlencode({'per_page': 50})}")
        results = [z for z in zones.get("result", []) if any(h == z["name"] or h.endswith("." + z["name"]) for h in hosts)]
    if not results:
        print(f"No Cloudflare zone found for {zone_arg}", file=sys.stderr)
        return 2
    zone = results[0]
    zone_id = zone["id"]
    print(f"zone={zone['name']} id={zone_id}")

    changed = 0
    for host in hosts:
        wanted = desired_record(host)
        existing = cf_request(
            token,
            "GET",
            f"/zones/{zone_id}/dns_records?{urllib.parse.urlencode({'type': 'HTTPS', 'name': host})}",
        ).get("result", [])
        match = next((r for r in existing if same_record(r, wanted)), None)
        if match:
            print(f"OK {host} (id={match['id']})")
            continue
        if existing:
            rec = existing[0]
            action = "UPDATE"
            path = f"/zones/{zone_id}/dns_records/{rec['id']}"
            method = "PUT"
        else:
            action = "CREATE"
            path = f"/zones/{zone_id}/dns_records"
            method = "POST"
        print(f"{action} {host} alpn=h3,h2")
        if args.apply:
            cf_request(token, method, path, wanted)
            changed += 1
        else:
            changed += 1
    if args.apply:
        print(f"applied={changed}")
    else:
        print(f"dry-run changes={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
