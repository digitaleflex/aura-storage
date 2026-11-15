#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

# `sudo bash scripts/deploy.sh` resets PATH, so a user-managed Node install
# (~/.node, nvm) disappears and the whole deploy aborts on "npm not found".
# Recover the invoking operator's toolchain before checking for it.
if ! command -v npm >/dev/null 2>&1 && [[ -n "${SUDO_USER:-}" ]]; then
  for candidate in "/home/${SUDO_USER}/.node"/*/bin "/home/${SUDO_USER}/.nvm/versions/node"/*/bin; do
    if [[ -x "${candidate}/npm" ]]; then
      export PATH="${candidate}:${PATH}"
      break
    fi
  done
fi

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed. See docs/DEPLOYMENT.md." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose plugin is unavailable." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm (Node.js) is required to build the web frontend. See docs/DEPLOYMENT.md." >&2; exit 1; }

[[ -f .env ]] || { echo "ERROR: .env is missing. Copy .env.example and replace all placeholders." >&2; exit 1; }

# Generate the dedicated aura-api S3 credentials when missing, empty, placeholder
# or too short. The API must never fall back to the bootstrap Admin identity.
# Idempotent: valid keys are left untouched. Secrets are never printed.
ensure_api_credentials() {
  local ak="${S3_API_ACCESS_KEY:-}"
  local sk="${S3_API_SECRET_KEY:-}"
  if [[ -n "$ak" && -n "$sk" \
        && "$ak" != *REPLACE_WITH_* && "$sk" != *REPLACE_WITH_* \
        && ${#ak} -ge 16 && ${#sk} -ge 32 ]]; then
    return 0
  fi

  echo "Generating dedicated aura-api S3 credentials in .env (the API does not use the bootstrap Admin key)." >&2
  python3 - <<'PY'
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from string import ascii_letters, digits

env_path = Path(".env")
try:
    info = env_path.stat()
    original = env_path.read_text(encoding="utf-8")
except OSError as exc:
    sys.exit(f"ERROR: cannot read {env_path}: {exc}")

mode = stat.S_IMODE(info.st_mode)
alphabet = ascii_letters + digits
access_key = "".join(secrets.choice(alphabet) for _ in range(24))
secret_key = secrets.token_urlsafe(48)

wanted = {
    "S3_API_ACCESS_KEY": access_key,
    "S3_API_SECRET_KEY": secret_key,
}
pattern = re.compile(
    r"^\s*(?:#\s*)?(?:export\s+)?(S3_API_ACCESS_KEY|S3_API_SECRET_KEY)\s*="
)
seen = set()
out = []
for line in original.splitlines():
    match = pattern.match(line)
    if match:
        key = match.group(1)
        out.append(f"{key}={wanted[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in wanted.items():
    if key not in seen:
        out.append(f"{key}={value}")
new_text = "\n".join(out) + "\n"

# Never widen permissions; keep the existing uid/gid where possible.
tmp_path = None
try:
    fd, tmp_name = tempfile.mkstemp(
        dir=str(env_path.parent), prefix=".env.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(new_text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp_path, min(mode, 0o600))
    try:
        os.chown(tmp_path, info.st_uid, info.st_gid)
    except PermissionError:
        pass
    os.replace(tmp_path, env_path)
except OSError as exc:
    if tmp_path is not None:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    sys.exit(
        "ERROR: cannot update .env atomically "
        f"({exc}). Ensure {env_path.resolve()} is writable by the deployment user."
    )
PY

  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
}

# Load only the operator-owned local .env for validation. Never source an untrusted file.
set -a
# shellcheck disable=SC1091
source .env
set +a

# Runs after the first source so existing valid credentials are reused, and
# before the placeholder check so a freshly copied .env is completed in place.
ensure_api_credentials

: "${AURA_INSTANCE_ID:?Set AURA_INSTANCE_ID in .env}"
: "${TRAEFIK_IMAGE:?Set TRAEFIK_IMAGE in .env}"
: "${SEAWEEDFS_IMAGE:?Set SEAWEEDFS_IMAGE in .env}"
: "${S3_DOMAIN:?Set S3_DOMAIN in .env}"
: "${ACME_EMAIL:?Set ACME_EMAIL in .env}"
: "${AURA_DATA_DIR:?Set AURA_DATA_DIR in .env}"
: "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY in .env}"
: "${S3_SECRET_KEY:?Set S3_SECRET_KEY in .env}"
: "${WEED_S3_SSE_KEK:?Set WEED_S3_SSE_KEK in .env}"

# Ignore commented example lines: .env.example documents optional settings such
# as `# AURA_SHARE_BASE_URL=https://app.example.invalid`. Only active values can
# break a deployment.
if grep -Ev '^[[:space:]]*#' .env | grep -Eq 'REPLACE_WITH_|example\.com|example\.invalid|replace-with-'; then
  echo "ERROR: Placeholder values remain in .env. Replace them before deployment." >&2
  exit 1
fi

if [[ ! "$WEED_S3_SSE_KEK" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "ERROR: WEED_S3_SSE_KEK must be exactly 64 hexadecimal characters (32 bytes)." >&2
  exit 1
fi

if [[ ${#S3_ACCESS_KEY} -lt 16 || ${#S3_SECRET_KEY} -lt 32 ]]; then
  echo "ERROR: S3_ACCESS_KEY must be at least 16 chars and S3_SECRET_KEY at least 32 chars." >&2
  exit 1
fi

if [[ "$S3_API_ACCESS_KEY" == "$S3_ACCESS_KEY" || "$S3_API_SECRET_KEY" == "$S3_SECRET_KEY" ]]; then
  echo "ERROR: S3_API_* must differ from the bootstrap S3_* keys. Remove them from .env and re-run bootstrap to generate dedicated credentials." >&2
  exit 1
fi

mkdir -p config/seaweedfs
bash ./scripts/generate-config.sh

# Make sure the storage root exists on the configured filesystem.
mkdir -p "$AURA_DATA_DIR"/{master,volume,filer}
chmod 700 "$AURA_DATA_DIR" "$AURA_DATA_DIR"/{master,volume,filer}

docker compose config --quiet
echo "Compose configuration syntax validated; verify SSE-S3 with tests/sse-s3-smoke-test.sh before importing valuable data."
