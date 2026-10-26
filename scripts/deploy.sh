#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
bash ./scripts/bootstrap.sh
# Build the static frontend the app container bind-mounts from ./web/dist.
# web/dist is git-ignored, so without this step a deploy unknowingly serves a
# stale bundle (this is how a frontend/API contract drift reached the pilot).
( cd web && npm ci --no-audit --no-fund && npm run build )
# Under sudo, the build artifacts would stay root-owned and break the next
# deploy run as the operator. Hand them back explicitly.
if [[ -n "${SUDO_USER:-}" ]]; then
  chown -R "${SUDO_USER}:${SUDO_USER}" "${ROOT_DIR}/web/dist" "${ROOT_DIR}/web/node_modules" 2>/dev/null || true
fi
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
CURRENT_NGINX_HASH="$(
  cat "${ROOT_DIR}/app/nginx.conf" "${ROOT_DIR}/landing/nginx.conf" \
      "${ROOT_DIR}/landing/entrypoint.sh" | sha256sum | awk '{print $1}'
)"
if [[ -f "${NGINX_HASH_FILE}" ]] && [[ "$(cat "${NGINX_HASH_FILE}")" != "${CURRENT_NGINX_HASH}" ]]; then
  echo "nginx/landing config changed: recreating app and s3-landing services"
  docker compose up -d --wait --wait-timeout 180 --remove-orphans --force-recreate app s3-landing
else
  docker compose up -d --wait --wait-timeout 180 --remove-orphans
fi
# Traefik v3.7 filters containers whose health is still "starting": if it comes
# up before app/s3-landing are healthy, their routers (and the middlewares
# defined on app) are missing until the next Docker event. Restarting it after
# the stack is healthy makes the routing configuration deterministic.
docker compose restart traefik
echo "${CURRENT_NGINX_HASH}" > "${NGINX_HASH_FILE}"
docker compose ps

# Postflight: verify the expected CSP is actually served by the app router.
# The loopback :80 request used to hit Traefik's HTTP->HTTPS redirect (a 308
# with no CSP), so a healthy deploy failed here. Resolve the real app domain
# against loopback so TLS SNI and the Traefik router are both correct.
APP_DOMAIN_VALUE="$(grep -E '^APP_DOMAIN=' "${ROOT_DIR}/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
EXPECTED_CSP="$(grep -o 'Content-Security-Policy[^;]*' "${ROOT_DIR}/app/nginx.conf" | head -1 || true)"
if [[ -n "${EXPECTED_CSP}" ]]; then
  if [[ -z "${APP_DOMAIN_VALUE}" ]]; then
    echo "ERROR: APP_DOMAIN is missing from .env; cannot verify the served CSP" >&2
    exit 1
  fi
  SERVED_CSP="$(curl -sI --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" "https://${APP_DOMAIN_VALUE}/" 2>/dev/null | grep -i 'content-security-policy' || true)"
  if [[ -z "${SERVED_CSP}" ]]; then
    echo "ERROR: no Content-Security-Policy header served after deploy (${APP_DOMAIN_VALUE})" >&2
    exit 1
  fi
  echo "CSP verified on https://${APP_DOMAIN_VALUE}/"
fi

# Postflight: the served bundle must be byte-identical to the one just built.
# The app serves ./web/dist through a bind mount, so a stale or hand-edited
# directory would silently ship code that is not in this checkout.
ASSET_PATH="$(curl -sS --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" \
  "https://${APP_DOMAIN_VALUE}/" 2>/dev/null \
  | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1 || true)"
if [[ -z "${ASSET_PATH}" ]]; then
  echo "ERROR: could not find the hashed bundle URL on ${APP_DOMAIN_VALUE}" >&2
  exit 1
fi
if [[ ! -f "${ROOT_DIR}/web/dist${ASSET_PATH}" ]]; then
  echo "ERROR: served bundle ${ASSET_PATH} is absent from web/dist (stale production mount?)" >&2
  exit 1
fi
LOCAL_ASSET_HASH="$(sha256sum "${ROOT_DIR}/web/dist${ASSET_PATH}" | awk '{print $1}')"
SERVED_ASSET_HASH="$(curl -sS --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" \
  "https://${APP_DOMAIN_VALUE}${ASSET_PATH}" 2>/dev/null | sha256sum | awk '{print $1}')"
if [[ "${LOCAL_ASSET_HASH}" != "${SERVED_ASSET_HASH}" ]]; then
  echo "ERROR: served bundle hash differs from web/dist (local ${LOCAL_ASSET_HASH}, served ${SERVED_ASSET_HASH})" >&2
  exit 1
fi
echo "Bundle verified: ${ASSET_PATH}"
