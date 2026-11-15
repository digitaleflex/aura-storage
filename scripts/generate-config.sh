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
: "${S3_API_ACCESS_KEY:?Set S3_API_ACCESS_KEY in .env (run scripts/bootstrap.sh to generate dedicated aura-api credentials)}"
: "${S3_API_SECRET_KEY:?Set S3_API_SECRET_KEY in .env (run scripts/bootstrap.sh to generate dedicated aura-api credentials)}"

if [[ "$S3_ACCESS_KEY" == *REPLACE* || "$S3_SECRET_KEY" == *REPLACE* ]]; then
  echo "ERROR: Replace S3 credential placeholders in .env before generating config." >&2
  exit 1
fi

if [[ "$S3_API_ACCESS_KEY" == *REPLACE* || "$S3_API_SECRET_KEY" == *REPLACE* ]]; then
  echo "ERROR: Replace S3_API_* placeholders in .env (run scripts/bootstrap.sh to generate dedicated aura-api credentials)." >&2
  exit 1
fi

if [[ "$S3_API_ACCESS_KEY" =~ [[:space:]] || "$S3_API_SECRET_KEY" =~ [[:space:]] ]]; then
  echo "ERROR: S3_API_* must not contain whitespace: bash and Python would read different values, causing runtime 403s." >&2
  exit 1
fi

if [[ ${#S3_API_ACCESS_KEY} -lt 16 || ${#S3_API_SECRET_KEY} -lt 32 ]]; then
  echo "ERROR: S3_API_ACCESS_KEY must be at least 16 chars and S3_API_SECRET_KEY at least 32 chars (run scripts/bootstrap.sh to generate dedicated credentials)." >&2
  exit 1
fi

if [[ "$S3_API_ACCESS_KEY" == "$S3_ACCESS_KEY" || "$S3_API_SECRET_KEY" == "$S3_SECRET_KEY" ]]; then
  echo "ERROR: S3_API_* must differ from the bootstrap S3_* keys (run scripts/bootstrap.sh to generate dedicated credentials)." >&2
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

api_access_key = os.environ["S3_API_ACCESS_KEY"].strip()
api_secret_key = os.environ["S3_API_SECRET_KEY"].strip()
if api_access_key == access_key or api_secret_key == secret_key:
    raise SystemExit("ERROR: S3_API_* must differ from the bootstrap S3_* keys.")

for identity in data.get("identities", []):
    is_api = identity.get("name") == "aura-api"
    for credential in identity.get("credentials", []):
        if is_api:
            # The API always runs with its dedicated least-privilege identity.
            # There is no fallback to the bootstrap Admin key.
            credential["accessKey"] = api_access_key
            credential["secretKey"] = api_secret_key
        else:
            if credential.get("accessKey", "").startswith("REPLACE_"):
                credential["accessKey"] = access_key
            if credential.get("secretKey", "").startswith("REPLACE_"):
                credential["secretKey"] = secret_key

# The dedicated identity is mandatory: never emit a config without it, and
# never let it regain administrative rights.
api_identities = [
    identity
    for identity in data.get("identities", [])
    if identity.get("name") == "aura-api"
]
if not api_identities:
    raise SystemExit(
        "ERROR: s3.json.example must define the dedicated aura-api identity."
    )

allowed_actions = {"Read", "Write", "List"}
for identity in api_identities:
    actions = identity.get("actions", [])
    if not isinstance(actions, list):
        raise SystemExit("ERROR: aura-api actions must be a list.")
    if "Admin" in actions:
        raise SystemExit(
            "ERROR: aura-api must not have the Admin action; use Read/Write/List only."
        )
    unexpected = [action for action in actions if action not in allowed_actions]
    if unexpected:
        raise SystemExit(
            "ERROR: aura-api actions must be a subset of Read/Write/List; "
            f"unexpected: {unexpected}"
        )

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
