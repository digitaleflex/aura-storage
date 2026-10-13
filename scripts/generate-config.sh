#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

[[ -f .env ]] || { echo "ERROR: .env is missing. Copy .env.example first." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required to generate local configuration." >&2; exit 1; }

# .env is a trusted, local operator-owned shell-style file. Never source an untrusted .env.
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY in .env}"
: "${S3_SECRET_KEY:?Set S3_SECRET_KEY in .env}"

if [[ "$S3_ACCESS_KEY" == *REPLACE* || "$S3_SECRET_KEY" == *REPLACE* ]]; then
  echo "ERROR: Replace S3 credential placeholders in .env before generating config." >&2
  exit 1
fi

python3 - <<'PY'
import json
import os
from pathlib import Path

source = Path("config/seaweedfs/s3.json.example")
target = Path("config/seaweedfs/s3.json")
data = json.loads(source.read_text(encoding="utf-8"))
access_key = os.environ["S3_ACCESS_KEY"]
secret_key = os.environ["S3_SECRET_KEY"]

for identity in data.get("identities", []):
    for credential in identity.get("credentials", []):
        if credential.get("accessKey", "").startswith("REPLACE_"):
            credential["accessKey"] = access_key
        if credential.get("secretKey", "").startswith("REPLACE_"):
            credential["secretKey"] = secret_key

if not data.get("identities"):
    raise SystemExit("ERROR: s3.json.example contains no identities.")
if any(
    credential.get("accessKey", "").startswith("REPLACE_")
    or credential.get("secretKey", "").startswith("REPLACE_")
    for identity in data["identities"]
    for credential in identity.get("credentials", [])
):
    raise SystemExit("ERROR: unresolved S3 credential placeholder remains in template.")

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
target.chmod(0o600)
print("Generated config/seaweedfs/s3.json with permissions 0600.")
print("Review the SeaweedFS policy/actions against the exact image release before production.")
PY
