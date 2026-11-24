#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
bash ./scripts/bootstrap.sh
# bootstrap.sh validated .env above; load it here for release paths and Compose
# interpolation. It is operator-owned and never printed.
set -a
# shellcheck disable=SC1091
source .env
set +a
# Build the static frontend that each deploy publishes as an immutable release.
# web/dist is git-ignored, so without this step a deploy unknowingly serves a
# stale bundle (this is how a frontend/API contract drift reached the pilot).
( cd web && npm ci --no-audit --no-fund && npm run build )
# Under sudo, the build artifacts would stay root-owned and break the next
# deploy run as the operator. Hand them back explicitly.
if [[ -n "${SUDO_USER:-}" ]]; then
  chown -R "${SUDO_USER}:${SUDO_USER}" "${ROOT_DIR}/web/dist" "${ROOT_DIR}/web/node_modules" 2>/dev/null || true
fi

# Publish the built frontend as an immutable release outside the worktree. The
# app and s3-landing services mount ${AURA_WEB_DIST_DIR} (Compose defaults to
# ./web/dist for local development), so a later checkout or build cannot mutate
# the bundle that a running release serves.
AURA_RELEASES_DIR="${AURA_RELEASES_DIR:-${AURA_DATA_DIR}/releases}"
AURA_KEEP_RELEASES="${AURA_KEEP_RELEASES:-5}"
mkdir -p "${AURA_RELEASES_DIR}"
RESOLVED_RELEASES_DIR="$(cd "${AURA_RELEASES_DIR}" && pwd)" || {
  echo "ERROR: cannot resolve release directory ${AURA_RELEASES_DIR} to an absolute path." >&2
  exit 1
}
AURA_RELEASES_DIR="${RESOLVED_RELEASES_DIR}"
case "${AURA_RELEASES_DIR}" in
  "${ROOT_DIR}"|"${ROOT_DIR}"/*)
    echo "ERROR: release directory ${AURA_RELEASES_DIR} is inside the worktree ${ROOT_DIR}; refusing to publish mutable code." >&2
    exit 1
    ;;
esac
if [[ ! "${AURA_KEEP_RELEASES}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: AURA_KEEP_RELEASES must be a non-negative integer (got '${AURA_KEEP_RELEASES}')." >&2
  exit 1
fi
KEEP_RELEASES=$((10#${AURA_KEEP_RELEASES}))
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || true)"
RELEASE_STAMP="$(date -u +%Y%m%dT%H%M%S%NZ)"
RELEASE_DIR="${AURA_RELEASES_DIR%/}/web-${RELEASE_STAMP}-${GIT_SHA:-nogit}"
mkdir -p "${RELEASE_DIR}"
cp -a "${ROOT_DIR}/web/dist/." "${RELEASE_DIR}/"
# Swap the `current` symlink atomically so no container sees a half-built path.
ln -sfn "${RELEASE_DIR}" "${AURA_RELEASES_DIR%/}/current.tmp"
mv -Tf "${AURA_RELEASES_DIR%/}/current.tmp" "${AURA_RELEASES_DIR%/}/current"
AURA_WEB_DIST_DIR="$(readlink -f "${AURA_RELEASES_DIR%/}/current")"
case "${AURA_WEB_DIST_DIR}" in
  "${ROOT_DIR}"|"${ROOT_DIR}"/*)
    echo "ERROR: AURA_WEB_DIST_DIR resolves inside the worktree (${AURA_WEB_DIST_DIR}); refusing to serve the mutable checkout." >&2
    exit 1
    ;;
esac
export AURA_WEB_DIST_DIR
echo "Published frontend release: ${AURA_WEB_DIST_DIR}"
# Keep the release tree operator-owned under sudo, matching web/dist handling.
if [[ -n "${SUDO_USER:-}" ]]; then
  chown "${SUDO_USER}:${SUDO_USER}" "${AURA_RELEASES_DIR}" 2>/dev/null || true
  chown -R "${SUDO_USER}:${SUDO_USER}" "${RELEASE_DIR}" 2>/dev/null || true
fi
# Retain only the newest KEEP_RELEASES releases. Release names start with the
# UTC timestamp, so a plain reverse name sort is chronological; mtime is not
# reliable because `cp -a` propagates web/dist's timestamps. Never delete
# `current`.
if (( KEEP_RELEASES > 0 )); then
  mapfile -t RELEASE_NAMES < <(
    find "${AURA_RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'web-*' \
      -printf '%f\n' | sort -r
  )
  if (( ${#RELEASE_NAMES[@]} > KEEP_RELEASES )); then
    CURRENT_RELEASE_NAME="$(basename "$(readlink -f "${AURA_RELEASES_DIR%/}/current")")"
    for stale_name in "${RELEASE_NAMES[@]:KEEP_RELEASES}"; do
      [[ "$stale_name" == "$CURRENT_RELEASE_NAME" ]] && continue
      rm -rf -- "${AURA_RELEASES_DIR%/}/${stale_name}"
    done
  fi
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
if [[ ! -f "${ROOT_DIR}/config/seaweedfs/s3.json" ]]; then
  echo "ERROR: config/seaweedfs/s3.json is missing; run scripts/bootstrap.sh before deploying." >&2
  exit 1
fi
S3_CONFIG_HASH_FILE="${ROOT_DIR}/.deploy-s3-config-hash"
CURRENT_S3_CONFIG_HASH="$(sha256sum "${ROOT_DIR}/config/seaweedfs/s3.json" | awk '{print $1}')"
if [[ -f "${NGINX_HASH_FILE}" ]] && [[ "$(cat "${NGINX_HASH_FILE}")" != "${CURRENT_NGINX_HASH}" ]]; then
  echo "nginx/landing config changed: recreating app and s3-landing services"
  docker compose up -d --wait --wait-timeout 180 --remove-orphans --force-recreate app s3-landing
else
  docker compose up -d --wait --wait-timeout 180 --remove-orphans
fi
# SeaweedFS reads -s3.config only at startup and reloads identities on SIGHUP;
# on 4.48 a removed identity requires a restart. Restart the S3 gateway whenever
# the generated config changed, before Traefik resumes routing. Never print the
# config or its credentials.
if [[ ! -f "${S3_CONFIG_HASH_FILE}" ]] || [[ "$(cat "${S3_CONFIG_HASH_FILE}")" != "${CURRENT_S3_CONFIG_HASH}" ]]; then
  echo "S3 config changed: restarting seaweed-filer to reload identities"
  docker compose restart seaweed-filer
  echo "${CURRENT_S3_CONFIG_HASH}" > "${S3_CONFIG_HASH_FILE}"
fi
# Traefik v3.7 filters containers whose health is still "starting": if it comes
# up before app/s3-landing are healthy, their routers (and the middlewares
# defined on app) are missing until the next Docker event. Restarting it after
# the stack is healthy makes the routing configuration deterministic.
docker compose restart traefik
# Traefik reloads its routers asynchronously, and its container healthcheck
# (30 s interval) is not a readiness signal for the router: it can be "healthy"
# while the app router still answers the fallback. The CSP probe below therefore
# retries on the real URL. Two deploys failed here on 2026-10-26 because the
# probe raced the reload; do not shorten that window without re-testing.
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
  SERVED_CSP=""
  # The router needs tens of seconds after a Traefik restart (observed >20 s on
  # 2026-10-26). Poll the real URL for up to 2 minutes instead of trusting
  # container health, which does not track router readiness.
  for _ in $(seq 1 60); do
    SERVED_CSP="$(curl -sI --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" "https://${APP_DOMAIN_VALUE}/" 2>/dev/null | grep -i 'content-security-policy' || true)"
    [[ -n "${SERVED_CSP}" ]] && break
    sleep 2
  done
  if [[ -z "${SERVED_CSP}" ]]; then
    echo "ERROR: no Content-Security-Policy header served after deploy (${APP_DOMAIN_VALUE})" >&2
    exit 1
  fi
  echo "CSP verified on https://${APP_DOMAIN_VALUE}/"
fi

# Postflight: the served bundle must be byte-identical to the immutable release
# just published. A stale or hand-edited directory would silently ship code that
# is not in this checkout.
ASSET_PATH="$(curl -sS --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" \
  "https://${APP_DOMAIN_VALUE}/" 2>/dev/null \
  | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1 || true)"
if [[ -z "${ASSET_PATH}" ]]; then
  echo "ERROR: could not find the hashed bundle URL on ${APP_DOMAIN_VALUE}" >&2
  exit 1
fi
if [[ ! -f "${AURA_WEB_DIST_DIR}${ASSET_PATH}" ]]; then
  echo "ERROR: served bundle ${ASSET_PATH} is absent from ${AURA_WEB_DIST_DIR} (stale production mount?)" >&2
  exit 1
fi
LOCAL_ASSET_HASH="$(sha256sum "${AURA_WEB_DIST_DIR}${ASSET_PATH}" | awk '{print $1}')"
SERVED_ASSET_HASH="$(curl -sS --resolve "${APP_DOMAIN_VALUE}:443:127.0.0.1" \
  "https://${APP_DOMAIN_VALUE}${ASSET_PATH}" 2>/dev/null | sha256sum | awk '{print $1}')"
if [[ "${LOCAL_ASSET_HASH}" != "${SERVED_ASSET_HASH}" ]]; then
  echo "ERROR: served bundle hash differs from ${AURA_WEB_DIST_DIR} (local ${LOCAL_ASSET_HASH}, served ${SERVED_ASSET_HASH})" >&2
  exit 1
fi
echo "Bundle verified: ${ASSET_PATH}"

# Postflight: the PUBLIC portal. The app checks above say nothing about
# PUBLIC_DOMAIN, so a stale API container or a missing Traefik route would
# pass. scripts/portal-postflight.sh proves the portal serves this checkout.
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}" bash "${ROOT_DIR}/scripts/portal-postflight.sh"
