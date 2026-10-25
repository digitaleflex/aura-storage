#!/usr/bin/env bash
# Edge-proxy (Traefik) multipart part-PUT harness — plan gate item 6.
#
# Starts an ISOLATED throwaway SeaweedFS 4.48 stack (master + volume + filer/S3)
# plus TWO Traefik instances in front of the S3 gateway on their own docker
# network and data dir under /tmp/opencode:
#
#   multipart-proxy-4-48-traefik          readTimeout=7200s  (production value)
#   multipart-proxy-4-48-traefik-default  Traefik default    (60s, negative control)
#
# Both route Host(`s3.test`) to the S3 gateway; tests/multipart_proxy_client.py
# resolves s3.test to 127.0.0.1 and speaks to the published loopback ports, so
# the URL (and the SigV4-signed Host header) keeps the real hostname:port.
#
# Assertions: A slow 5 MiB part SUCCEEDS through the 7200s proxy and its ETag
# equals the local MD5 of the exact bytes sent; B the same upload is CUT OFF by
# the default-60s proxy; C part-size arithmetic against 7200s; D teardown proof.
#
# It NEVER creates, inspects or modifies the pilot stack (aura-001-* / compose
# project "aura-storage") and never reads the pilot's .env credentials.
#
# Usage:  sg docker -c 'bash tests/multipart-proxy-4.48.sh'
# Env:    SLOW_RATE_KBPS (default 64), PART_BYTES (default 5242880),
#         TRAEFIK_IMAGE (default traefik:v3.7.14)
# Exit 0 iff A/B/C pass, no leftover containers/network and the pilot is untouched.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

IMAGE="chrislusf/seaweedfs:4.48"
TRAEFIK_IMAGE="${TRAEFIK_IMAGE:-traefik:v3.7.14}"
PREFIX="multipart-proxy-4-48"
NET="${PREFIX}-net"
MASTER="${PREFIX}-master"
VOLUME="${PREFIX}-volume"
FILER="${PREFIX}-filer"
GOOD="${PREFIX}-traefik"
BAD="${PREFIX}-traefik-default"
RUN_ID="$(date -u +%s)-$$"
WORK="/tmp/opencode/${PREFIX}-${RUN_ID}"
LOG="${WORK}.log"
SLOW_RATE_KBPS="${SLOW_RATE_KBPS:-64}"
PART_BYTES="${PART_BYTES:-5242880}"
ORIGIN="https://proxy.example.test"
PILOT_FILTER="label=com.docker.compose.project=aura-storage"

mkdir -p /tmp/opencode
# Full transcript kept OUTSIDE the workdir (the workdir is deleted at the end).
exec > >(tee "$LOG") 2>&1

echo "=== MULTIPART PART PUT THROUGH TRAEFIK (item 6) ==="
echo "run id: $RUN_ID  workdir: $WORK  log: $LOG"

command -v docker >/dev/null 2>&1 || { echo "[FAIL] docker is required." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "[FAIL] curl is required." >&2; exit 1; }
python="$ROOT_DIR/.venv/bin/python"
[[ -x "$python" ]] || python="$(command -v python3)"
command -v "$python" >/dev/null 2>&1 || { echo "[FAIL] python3 is required." >&2; exit 1; }

# Refuse to run if any of our fixed names already exist from a crashed run,
# rather than silently reusing another instance's containers.
for c in "$MASTER" "$VOLUME" "$FILER" "$GOOD" "$BAD"; do
  if sg docker -c "docker inspect '$c'" >/dev/null 2>&1; then
    echo "[FAIL] container '$c' already exists; remove it manually first." >&2
    exit 1
  fi
done
if sg docker -c "docker network inspect '$NET'" >/dev/null 2>&1; then
  echo "[FAIL] network '$NET' already exists; remove it manually first." >&2
  exit 1
fi

# Snapshot the pilot (read-only) so D can prove we never touched it.
pilot_before="$(sg docker -c "docker ps -a --filter '$PILOT_FILTER' --format '{{.Names}}|{{.ID}}|{{.State}}'" 2>/dev/null | sort || true)"
echo "pilot containers before (compose project aura-storage): ${pilot_before:-<none>}"

mkdir -p "$WORK/master" "$WORK/volume" "$WORK/filer"
chmod 700 "$WORK"

# Throwaway credentials + SSE-S3 KEK, generated for THIS ephemeral instance only.
read -r ACCESS_KEY SECRET_KEY KEK BUCKET < <("$python" - <<'PY'
import secrets
print(secrets.token_urlsafe(15)[:20],
      secrets.token_urlsafe(30)[:40],
      secrets.token_hex(32),
      "proxy-" + secrets.token_hex(6))
PY
)
cat > "$WORK/s3.json" <<JSON
{
  "identities": [
    {
      "name": "proxy-harness",
      "credentials": [{"accessKey": "$ACCESS_KEY", "secretKey": "$SECRET_KEY"}],
      "actions": ["Admin", "Read", "Write", "List"]
    }
  ]
}
JSON
chmod 600 "$WORK/s3.json"

# Traefik file-provider: Host(`s3.test`) -> the ephemeral S3 gateway. Same
# router/service definition is mounted in BOTH proxy instances; only the
# entrypoint readTimeout differs. Production uses the Docker provider+labels
# (docker-compose.yml:163-171); the proxy behaviour under test is the static
# entrypoint timeout, so a file provider keeps the harness independent of the
# docker socket without changing the code path that matters.
cat > "$WORK/traefik-dynamic.yml" <<'YAML'
http:
  routers:
    s3:
      rule: "Host(`s3.test`)"
      entryPoints:
        - websecure
      service: s3
  services:
    s3:
      loadBalancer:
        servers:
          - url: "http://multipart-proxy-4-48-filer:8333"
YAML

teardown() {
  local rc=$?
  trap - EXIT
  echo
  echo "=== D. TEARDOWN / ISOLATION PROOF ==="

  # Proxy access logs are the raw evidence of what each entrypoint did.
  echo "--- good proxy access log (tail) ---"
  sg docker -c "docker logs --tail 20 '$GOOD'" 2>&1 | sed 's/^/[good-proxy] /' || true
  echo "--- default-timeout proxy access log (tail) ---"
  sg docker -c "docker logs --tail 20 '$BAD'" 2>&1 | sed 's/^/[bad-proxy] /' || true
  echo "--- S3 filer log (tail) ---"
  sg docker -c "docker logs --tail 30 '$FILER'" 2>&1 | sed 's/^/[filer] /' || true
  echo "--- volume log (tail) ---"
  sg docker -c "docker logs --tail 30 '$VOLUME'" 2>&1 | sed 's/^/[volume] /' || true
  echo "--- stack container states before removal ---"
  sg docker -c "docker ps -a --filter 'name=${PREFIX}' --format '{{.Names}}|{{.State}}|{{.Status}}'" 2>&1 || true

  sg docker -c "docker rm -f '$BAD' '$GOOD' '$FILER' '$VOLUME' '$MASTER'" >/dev/null 2>&1 || true
  sg docker -c "docker network rm '$NET'" >/dev/null 2>&1 || true
  rm -rf "$WORK"

  local leftover_c leftover_n
  leftover_c="$(sg docker -c "docker ps -a --filter 'name=${PREFIX}' --format '{{.Names}}'" 2>/dev/null || true)"
  leftover_n="$(sg docker -c "docker network ls --filter 'name=${PREFIX}' --format '{{.Name}}'" 2>/dev/null || true)"
  if [[ -z "$leftover_c" ]]; then
    echo "[PASS] D: no ${PREFIX}-* containers remain"
  else
    echo "[FAIL] D: leftover containers: $leftover_c"
    rc=1
  fi
  if [[ -z "$leftover_n" ]]; then
    echo "[PASS] D: no ${PREFIX}-* networks remain"
  else
    echo "[FAIL] D: leftover networks: $leftover_n"
    rc=1
  fi
  if [[ ! -e "$WORK" ]]; then
    echo "[PASS] D: workdir removed ($WORK)"
  else
    echo "[FAIL] D: workdir still present ($WORK)"
    rc=1
  fi

  local pilot_after
  pilot_after="$(sg docker -c "docker ps -a --filter '$PILOT_FILTER' --format '{{.Names}}|{{.ID}}|{{.State}}'" 2>/dev/null | sort || true)"
  if [[ "$pilot_before" == "$pilot_after" ]]; then
    echo "[PASS] D: pilot untouched (compose project aura-storage container set identical)"
    echo "       ${pilot_after:-<none>}"
  else
    echo "[FAIL] D: pilot container set CHANGED"
    echo "       before: ${pilot_before:-<none>}"
    echo "       after:  ${pilot_after:-<none>}"
    rc=1
  fi
  echo "kept transcript: $LOG"
  exit "$rc"
}
trap teardown EXIT

echo
echo "=== EPHEMERAL STACK (seaweedfs $IMAGE, traefik $TRAEFIK_IMAGE) ==="
sg docker -c "docker image inspect $IMAGE --format 'seaweedfs image id: {{.Id}}  digest: {{range .RepoDigests}}{{.}}{{end}}  created: {{.Created}}'"
sg docker -c "docker image inspect $TRAEFIK_IMAGE --format 'traefik image id: {{.Id}}  digest: {{range .RepoDigests}}{{.}}{{end}}  created: {{.Created}}'"

sg docker -c "docker network create '$NET'" >/dev/null
echo "network: $NET  workdir: $WORK"

# --- SeaweedFS stack: copy of the working invocation in
# --- tests/multipart-compat-4.48.sh (pinned 4.48), only names differ.
sg docker -c "docker run -d --name '$MASTER' --network '$NET' \
  -v '$WORK/master:/data' '$IMAGE' master \
  -ip='$MASTER' -ip.bind=0.0.0.0 -mdir=/data" >/dev/null

sg docker -c "docker run -d --name '$VOLUME' --network '$NET' \
  -v '$WORK/volume:/data' '$IMAGE' volume \
  -master='$MASTER:9333' -ip='$VOLUME' -ip.bind=0.0.0.0 -dir=/data -port=8080 -max=0" >/dev/null

sg docker -c "docker run -d --name '$FILER' --network '$NET' -p 127.0.0.1::8333 \
  -e WEED_S3_SSE_KEK='$KEK' \
  -v '$WORK/filer:/data' -v '$WORK/s3.json:/etc/seaweedfs/s3.json:ro' '$IMAGE' filer \
  -master='$MASTER:9333' -ip='$FILER' -ip.bind=0.0.0.0 -port=8888 \
  -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json -s3.allowedOrigins=$ORIGIN" >/dev/null

DIRECT_PORT="$(sg docker -c "docker port '$FILER' 8333/tcp" | awk -F: '{print $NF}')"
DIRECT_ENDPOINT="http://127.0.0.1:${DIRECT_PORT}"
echo "S3 gateway direct endpoint (readiness only): $DIRECT_ENDPOINT"

echo "waiting for the S3 gateway ..."
ready=0
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$DIRECT_ENDPOINT/" || true)"
  if [[ -n "$code" && "$code" != "000" ]]; then ready=1; break; fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "[FAIL] S3 gateway did not become reachable at $DIRECT_ENDPOINT" >&2
  sg docker -c "docker logs --tail 50 '$FILER'" 2>&1 || true
  exit 1
fi
echo "gateway reachable (HTTP $code on root)"

# --- Traefik #1: production readTimeout. ---
sg docker -c "docker run -d --name '$GOOD' --network '$NET' -p 127.0.0.1::443 \
  -v '$WORK/traefik-dynamic.yml:/etc/traefik/dynamic.yml:ro' '$TRAEFIK_IMAGE' \
  --entrypoints.websecure.address=:443 \
  --entrypoints.websecure.transport.respondingTimeouts.readTimeout=7200s \
  --providers.file.filename=/etc/traefik/dynamic.yml \
  --accesslog=true \
  --accesslog.fields.queryparameters.defaultmode=drop \
  --log.level=INFO" >/dev/null

# --- Traefik #2: DEFAULT readTimeout (60s) = negative control. ---
sg docker -c "docker run -d --name '$BAD' --network '$NET' -p 127.0.0.1::443 \
  -v '$WORK/traefik-dynamic.yml:/etc/traefik/dynamic.yml:ro' '$TRAEFIK_IMAGE' \
  --entrypoints.websecure.address=:443 \
  --providers.file.filename=/etc/traefik/dynamic.yml \
  --accesslog=true \
  --accesslog.fields.queryparameters.defaultmode=drop \
  --log.level=INFO" >/dev/null

echo "--- proxy configuration as actually passed to docker ---"
sg docker -c "docker inspect '$GOOD' --format 'good proxy args: {{json .Args}}'"
sg docker -c "docker inspect '$BAD' --format 'default proxy args: {{json .Args}}'"
echo "waiting for both Traefik entrypoints ..."
wait_proxy() {
  local name="$1" port code
  port="$(sg docker -c "docker port '$name' 443/tcp" | awk -F: '{print $NF}')"
  for _ in $(seq 1 60); do
    # A routed request is answered by SeaweedFS (403/200); 404 means the file
    # provider/router is not loaded yet. curl --resolve keeps the Host name.
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
      --resolve "s3.test:${port}:127.0.0.1" "http://s3.test:${port}/" || true)"
    if [[ "$code" == "200" || "$code" == "403" ]]; then
      echo "$port"
      return 0
    fi
    sleep 1
  done
  return 1
}
GOOD_PORT="$(wait_proxy "$GOOD")" || { echo "[FAIL] good Traefik did not route s3.test" >&2; sg docker -c "docker logs --tail 50 '$GOOD'" 2>&1 || true; exit 1; }
BAD_PORT="$(wait_proxy "$BAD")" || { echo "[FAIL] default-timeout Traefik did not route s3.test" >&2; sg docker -c "docker logs --tail 50 '$BAD'" 2>&1 || true; exit 1; }
GOOD_ENDPOINT="http://s3.test:${GOOD_PORT}"
BAD_ENDPOINT="http://s3.test:${BAD_PORT}"
echo "good proxy endpoint: $GOOD_ENDPOINT (readTimeout=7200s)"
echo "default proxy endpoint: $BAD_ENDPOINT (readTimeout=Traefik default 60s)"

# Host rule evidence: a request with another Host must NOT reach the S3 gateway.
other_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
  --resolve "other.test:${GOOD_PORT}:127.0.0.1" "http://other.test:${GOOD_PORT}/" || true)"
echo "[EVIDENCE] Host routing: Host(s3.test) -> routed, Host(other.test) -> HTTP $other_code (expect 404)"
if [[ "$other_code" != "404" ]]; then
  echo "[FAIL] Traefik Host rule is not behaving as expected" >&2
  exit 1
fi

set +e
S3_ACCESS_KEY="$ACCESS_KEY" S3_SECRET_KEY="$SECRET_KEY" \
  "$python" "$ROOT_DIR/tests/multipart_proxy_client.py" \
  --endpoint "$GOOD_ENDPOINT" --bad-endpoint "$BAD_ENDPOINT" \
  --bucket "$BUCKET" --proxy-host s3.test --origin "$ORIGIN" \
  --slow-rate-kbps "$SLOW_RATE_KBPS" --part-bytes "$PART_BYTES" \
  --pilot-part-bytes 5242880 --default-part-bytes 16777216
rc=$?
set -e

echo
echo "client exit code: $rc (0 = A/B/C passed)"
exit "$rc"
