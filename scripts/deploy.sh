#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
bash ./scripts/bootstrap.sh
# Build the static frontend the app container bind-mounts from ./web/dist.
# web/dist is git-ignored, so without this step a deploy unknowingly serves a
# stale bundle (this is how a frontend/API contract drift reached the pilot).
( cd web && npm ci --no-audit --no-fund && npm run build )
# Rebuild images built from source (the api service, `build: ./api`) so the
# running stack matches this checkout instead of reusing a stale local image.
docker compose build
# Pull only registry images. A plain `docker compose pull` also tries to pull
# `aura-api:local`, which is built locally and does not exist in a registry, so
# it fails (and, with `set -e`, aborts the deploy before `up -d`).
docker compose pull --ignore-buildable
# Detect changes to bind-mounted templates that docker compose does not
# notice on its own (e.g. app/nginx.conf mounted as a template): if the hash
# changed since the last deploy, force-recreate the app service.
NGINX_HASH_FILE="${ROOT_DIR}/.deploy-nginx-hash"
CURRENT_NGINX_HASH="$(sha256sum "${ROOT_DIR}/app/nginx.conf" | awk '{print $1}')"
if [[ -f "${NGINX_HASH_FILE}" ]] && [[ "$(cat "${NGINX_HASH_FILE}")" != "${CURRENT_NGINX_HASH}" ]]; then
  echo "app/nginx.conf changed: recreating app service"
  docker compose up -d --force-recreate app
else
  docker compose up -d
fi
echo "${CURRENT_NGINX_HASH}" > "${NGINX_HASH_FILE}"
docker compose ps

# Postflight: verify the expected CSP is actually served.
EXPECTED_CSP="$(grep -o 'Content-Security-Policy[^;]*' "${ROOT_DIR}/app/nginx.conf" | head -1 || true)"
if [[ -n "${EXPECTED_CSP}" ]]; then
  SERVED_CSP="$(curl -sI http://127.0.0.1/ 2>/dev/null | grep -i 'content-security-policy' || true)"
  if [[ -z "${SERVED_CSP}" ]]; then
    echo "ERROR: no Content-Security-Policy header served after deploy" >&2
    exit 1
  fi
fi
