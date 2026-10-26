#!/usr/bin/env bash
# Upload health check for the edge proxy (AURA).
#
# WHY: the API never sees an upload cut by Traefik. A part PUT is signed by the
# API but sent by the browser straight to the S3 gateway, so `respondingTimeouts
# .readTimeout` firing on the proxy produces a 499 "Client Closed Request" that
# exists only in the access log. A monitor that pages on 5xx alone is blind to
# it (measured 2026-10-25, see docs/verification-log-2026-10-25-multipart-proxy
# -4.48.md). This script is that missing watcher.
#
# It reads Traefik access logs (stdout of the container, or a saved file), keeps
# only requests routed to the S3 router, and reports four things:
#   499 on an upload   -> the proxy cut the body at readTimeout        (critical)
#   5xx on an upload   -> the request reached the proxy and failed     (critical)
#   2xx slower than readTimeout -> the enforced deadline is not the
#                        configured one (stale log or changed setting) (critical)
#   2xx at >= 80% of readTimeout -> approaching the deadline           (warning)
#
# Exit codes (cron/systemd friendly):
#   0 everything healthy
#   1 warning only (uploads are close to the deadline)
#   2 critical (an upload was cut or failed at the proxy)
#   3 the check itself could not run (docker/log source unavailable)
#
# Usage:
#   scripts/upload-health.sh                    # last 24h from the running stack
#   scripts/upload-health.sh --since 2h
#   scripts/upload-health.sh --file /tmp/traefik.log
#   scripts/upload-health.sh --json
#   READ_TIMEOUT_S=7200 scripts/upload-health.sh
set -Eeuo pipefail

# readTimeout configured on the Traefik entrypoint (docker-compose.yml). The
# warning threshold is derived from it so the two cannot drift silently.
READ_TIMEOUT_S="${READ_TIMEOUT_S:-7200}"
WARN_RATIO_PCT="${WARN_RATIO_PCT:-80}"
TRAEFIK_CONTAINER="${TRAEFIK_CONTAINER:-aura-001-traefik}"
S3_ROUTER_PREFIX="${S3_ROUTER_PREFIX:-aura-s3}"
SINCE="24h"
FILE=""
JSON=0
MAX_EXAMPLES=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --since) SINCE="${2:?--since needs a value}"; shift 2 ;;
    --file)  FILE="${2:?--file needs a path}"; shift 2 ;;
    --json)  JSON=1; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 3 ;;
  esac
done

if [[ -n "$FILE" ]]; then
  [[ -r "$FILE" ]] || { echo "ERROR: cannot read $FILE" >&2; exit 3; }
  LOG_CMD=(cat "$FILE")
else
  command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required (or pass --file)" >&2; exit 3; }
  # `docker logs` needs the group; `sg docker` is how this host exposes it.
  if docker info >/dev/null 2>&1; then
    LOG_CMD=(docker logs --since "$SINCE" "$TRAEFIK_CONTAINER")
  elif command -v sg >/dev/null 2>&1 && sg docker -c true >/dev/null 2>&1; then
    LOG_CMD=(sg docker -c "docker logs --since $(printf '%q' "$SINCE") $(printf '%q' "$TRAEFIK_CONTAINER")")
  else
    echo "ERROR: cannot reach the docker API to read $TRAEFIK_CONTAINER logs" >&2
    exit 3
  fi
fi

# Parse the Traefik common access-log format:
#   IP - - [date] "METHOD path HTTP/1.1" status size "referer" "ua" \
#     requestcount "router" "service" duration
# Split on '"' so quoted fields cannot break the parse.
#
# Only upload requests are considered: methods PUT/POST on the S3 router. The
# internet sends a constant stream of GET /autodiscover.xml and /version probe
# noise to this host; counting it would bury the signal.
"${LOG_CMD[@]}" 2>/dev/null | awk -F'"' -v warn_s="$((READ_TIMEOUT_S * WARN_RATIO_PCT / 100))" \
    -v router_prefix="$S3_ROUTER_PREFIX" -v max_ex="$MAX_EXAMPLES" \
    -v timeout_ms="$((READ_TIMEOUT_S * 1000))" \
    -v exfile="/tmp/aura-upload-health-ex.$$" '
function dur_ms(s,   v, u) {
  v = s; u = "ms"
  if (sub(/ms$/, "", v)) u = "ms"
  else if (sub(/µs$/, "", v)) u = "us"
  else if (sub(/s$/, "", v)) u = "s"
  else return -1
  v = v + 0
  if (u == "us") return v / 1000
  if (u == "s") return v * 1000
  return v
}
BEGIN { total = 0; cut = 0; failed = 0; near = 0; over = 0; slowest = -1; examples = 0 }
NF >= 11 {
  request = $2; statusf = $3; router = $8; durf = $11
  if (index(router, router_prefix) == 0) next
  split(request, rq, " ")
  method = rq[1]; path = rq[2]
  if (method != "PUT" && method != "POST") next
  split(statusf, st, " ")
  status = st[1] + 0
  if (status == 0) next
  total++
  ms = dur_ms(durf)
  if (ms > slowest) slowest = ms
  verdict = ""
  if (status == 499) { cut++; verdict = "CUT" }
  else if (status >= 500) { failed++; verdict = "FAILED" }
  # A success slower than the configured deadline cannot happen while that
  # deadline is enforced: the setting changed underneath this log, or the log
  # is stale. Either way the number the script warns on is wrong, so say so.
  else if (status >= 200 && status < 300 && ms >= timeout_ms) { over++; verdict = "OVER" }
  else if (status >= 200 && status < 300 && ms >= warn_s * 1000) { near++; verdict = "NEAR" }
  if (verdict != "" && examples < max_ex) {
    examples++
    gsub(/[[:cntrl:]]/, "", path)
    printf "  %-6s %s %s (%s) -- %dms\n", verdict, method, substr(path, 1, 90), status, ms > exfile
  }
}
END {
  printf "%d %d %d %d %d %d\n", total, cut, failed, near, over, (slowest < 0 ? 0 : slowest)
}' > /tmp/aura-upload-health.$$ || { echo "ERROR: log parsing failed" >&2; exit 3; }
read -r TOTAL CUT FAILED NEAR OVER SLOWEST_MS < /tmp/aura-upload-health.$$
rm -f "/tmp/aura-upload-health.$$"
EX=/tmp/aura-upload-health-ex.$$

if [[ "$JSON" == "1" ]]; then
  printf '{"uploads":%d,"cut_499":%d,"failed_5xx":%d,"over_deadline":%d,"near_deadline":%d,"slowest_ms":%d,"read_timeout_s":%d,"warn_ratio_pct":%d}\n' \
    "$TOTAL" "$CUT" "$FAILED" "$OVER" "$NEAR" "$SLOWEST_MS" "$READ_TIMEOUT_S" "$WARN_RATIO_PCT"
else
  echo "upload health: $TOTAL upload request(s) seen, slowest ${SLOWEST_MS}ms of ${READ_TIMEOUT_S}s"
  if [[ "$TOTAL" == "0" ]]; then
    echo "  no upload traffic in the window (nothing to judge)"
  fi
  [[ "$CUT" -gt 0 ]] && echo "  CRITICAL: $CUT upload(s) cut by the proxy (HTTP 499) — the body exceeded readTimeout"
  [[ "$FAILED" -gt 0 ]] && echo "  CRITICAL: $FAILED upload(s) failed at the proxy (5xx)"
  [[ "$OVER" -gt 0 ]] && echo "  CRITICAL: $OVER successful upload(s) exceeded readTimeout — the configured deadline is not the one that was enforced"
  [[ "$NEAR" -gt 0 ]] && echo "  WARNING: $NEAR upload(s) used >= ${WARN_RATIO_PCT}% of readTimeout — reduce part size or raise the deadline"
  if [[ "$CUT" -eq 0 && "$FAILED" -eq 0 && "$OVER" -eq 0 && "$NEAR" -eq 0 && "$TOTAL" -gt 0 ]]; then
    echo "  OK: no cut, no proxy failure, no upload near the deadline"
  fi
  if [[ -s "$EX" ]]; then
    echo "  worst requests:"
    cat "$EX"
  fi
fi
rm -f "$EX"

if [[ "$CUT" -gt 0 || "$FAILED" -gt 0 || "$OVER" -gt 0 ]]; then exit 2; fi
if [[ "$NEAR" -gt 0 ]]; then exit 1; fi
exit 0
