#!/usr/bin/env bash
# Postflight of the PUBLIC portal (PUBLIC_DOMAIN), run at the end of deploy.sh.
#
# deploy.sh already proves that the app domain serves the right CSP and bundle.
# It said nothing about the portal, so a stale API container or a missing
# Traefik route (2026-11-23: the CSP fix never reached production) went unseen.
# Every check below fails the deploy with a message naming what is wrong.
#
#   1. GET /             200 + a strict Content-Security-Policy      (API is the new code)
#   2. GET /portal-assets/portal.css  byte-identical to this checkout (container runs THIS code)
#   3. GET /sw.js        200, JavaScript, Service-Worker-Allowed: /  (route + header)
#   4. GET /hors-ligne   200                                          (route)
#   5. GET /profil       302 to /  when signed out                    (route exists on this host)
#   6. GET /robots.txt   200                                          (route)
#
# Requests go to the local Traefik with TLS SNI of the real domain (--resolve),
# like the app postflight. Overrides, mainly for tests:
#   PORTAL_CHECK_BASE        full base URL instead of https://$PUBLIC_DOMAIN
#   PORTAL_CHECK_CURL_ARGS   extra curl arguments (e.g. "-H Host:portail.test")
#   PORTAL_CHECK_ASSET_DIR   directory holding the reference portal.css
#   PORTAL_CHECK_TIMEOUT     seconds to wait for the router (default 120)
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"
BASE="${PORTAL_CHECK_BASE:-}"
if [[ -z "$BASE" ]]; then
  if [[ -z "$PUBLIC_DOMAIN" ]]; then
    echo "ERROR: PUBLIC_DOMAIN is not set; cannot verify the public portal." >&2
    exit 1
  fi
  BASE="https://${PUBLIC_DOMAIN}"
fi
ASSET_DIR="${PORTAL_CHECK_ASSET_DIR:-${ROOT_DIR}/api/portal_assets}"
TIMEOUT="${PORTAL_CHECK_TIMEOUT:-120}"
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || { echo "ERROR: PORTAL_CHECK_TIMEOUT must be an integer." >&2; exit 1; }

CURL=(curl -sS --max-time 15)
if [[ -z "${PORTAL_CHECK_BASE:-}" ]]; then
  CURL+=(--resolve "${PUBLIC_DOMAIN}:443:127.0.0.1")
fi
if [[ -n "${PORTAL_CHECK_CURL_ARGS:-}" ]]; then
  # shellcheck disable=SC2206  # intentional word splitting of the override
  CURL+=(${PORTAL_CHECK_CURL_ARGS})
fi

fail() { echo "ERROR: portal postflight: $*" >&2; exit 1; }

# --- 1. front page, retried: the Traefik router needs tens of seconds after a restart
HEADERS=""
deadline=$((SECONDS + TIMEOUT))
while :; do
  HEADERS="$("${CURL[@]}" -o /dev/null -D - "${BASE}/" 2>/dev/null || true)"
  if grep -qi '^content-security-policy:' <<<"$HEADERS" && head -1 <<<"$HEADERS" | grep -q ' 200'; then
    break
  fi
  (( SECONDS < deadline )) || break
  sleep 2
done
head -1 <<<"$HEADERS" | grep -q ' 200' \
  || fail "GET ${BASE}/ did not answer 200 within ${TIMEOUT}s (got: $(head -1 <<<"$HEADERS" | tr -d '\r'))"
CSP="$(grep -i '^content-security-policy:' <<<"$HEADERS" | head -1 | tr -d '\r')"
[[ -n "$CSP" ]] || fail "no Content-Security-Policy on ${BASE}/ (stale API container or missing route?)"
for need in "default-src 'none'" "script-src 'self'" "frame-ancestors 'none'"; do
  grep -qF "$need" <<<"$CSP" || fail "portal CSP lacks ${need}: ${CSP}"
done
if grep -q "unsafe-inline" <<<"${CSP%%style-src-attr*}"; then
  fail "portal CSP allows 'unsafe-inline' for scripts or styles: ${CSP}"
fi

# --- 2. the container serves THIS checkout's stylesheet
CSS_URL="$("${CURL[@]}" "${BASE}/" 2>/dev/null | grep -o '/portal-assets/portal\.css?v=[0-9a-f]*' | head -1 || true)"
[[ -n "$CSS_URL" ]] || fail "no /portal-assets/portal.css link in the portal page"
[[ -f "${ASSET_DIR}/portal.css" ]] || fail "reference file ${ASSET_DIR}/portal.css is missing"
LOCAL_HASH="$(sha256sum "${ASSET_DIR}/portal.css" | awk '{print $1}')"
SERVED_HASH="$("${CURL[@]}" "${BASE}${CSS_URL}" 2>/dev/null | sha256sum | awk '{print $1}')"
[[ "$LOCAL_HASH" == "$SERVED_HASH" ]] \
  || fail "served portal.css differs from the checkout (local ${LOCAL_HASH}, served ${SERVED_HASH}): the API container is stale"

# --- 3..6. routes and headers
SW_HEADERS="$("${CURL[@]}" -o /dev/null -D - "${BASE}/sw.js" 2>/dev/null || true)"
head -1 <<<"$SW_HEADERS" | grep -q ' 200' || fail "GET /sw.js is not 200 (route missing in Traefik?)"
grep -qi '^content-type: *text/javascript' <<<"$SW_HEADERS" || fail "/sw.js is not served as JavaScript"
grep -qi '^service-worker-allowed: */' <<<"$SW_HEADERS" || fail "/sw.js lacks Service-Worker-Allowed: /"

code() { "${CURL[@]}" -o /dev/null -w '%{http_code}' "$@" 2>/dev/null || echo 000; }
[[ "$(code "${BASE}/hors-ligne")" == "200" ]] || fail "GET /hors-ligne is not 200"
[[ "$(code "${BASE}/profil")" == "302" ]] || fail "GET /profil (signed out) is not a 302 to / (route missing in Traefik?)"
[[ "$(code "${BASE}/robots.txt")" == "200" ]] || fail "GET /robots.txt is not 200"

echo "Portal verified on ${BASE}/ (CSP, stylesheet ${LOCAL_HASH:0:12}, /sw.js, /hors-ligne, /profil, /robots.txt)"
