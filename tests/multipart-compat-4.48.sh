#!/usr/bin/env bash
# Ephemeral SeaweedFS 4.48 multipart compatibility harness (issue #84 / [ENG-03]).
#
# Starts an ISOLATED, throwaway SeaweedFS stack (master + volume + filer/S3) from
# the pinned image chrislusf/seaweedfs:4.48 in its own docker network and data dir
# under /tmp/opencode, generates THROWAWAY S3 credentials for it, runs
# tests/multipart_compat_client.py against it, then tears EVERYTHING down.
#
# It NEVER creates, inspects or touches the pilot stack (aura-001-* / compose
# project "aura-storage") and never reads the pilot's .env credentials.
#
# Usage:  sg docker -c 'bash tests/multipart-compat-4.48.sh'
# Exit 0 iff all asserted compatibility points passed.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

IMAGE="chrislusf/seaweedfs:4.48"
PREFIX="compat-4-48"
NET="${PREFIX}-net"
origin="https://compat.example.test"
RUN_ID="$(date -u +%s)-$$"
WORK="/tmp/opencode/${PREFIX}-${RUN_ID}"
MASTER="${PREFIX}-master"
VOLUME="${PREFIX}-volume"
FILER="${PREFIX}-filer"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 1; }
python="$ROOT_DIR/.venv/bin/python"
[[ -x "$python" ]] || python="$(command -v python3)"
command -v "$python" >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }

# Refuse to run if any of our fixed names already exist from a crashed run,
# rather than silently reusing another instance's containers.
for c in "$MASTER" "$VOLUME" "$FILER"; do
  if sg docker -c "docker inspect '$c'" >/dev/null 2>&1; then
    echo "ERROR: container '$c' already exists; remove it manually first." >&2
    exit 1
  fi
done
if sg docker -c "docker network inspect '$NET'" >/dev/null 2>&1; then
  echo "ERROR: network '$NET' already exists; remove it manually first." >&2
  exit 1
fi

mkdir -p "$WORK/master" "$WORK/volume" "$WORK/filer"
chmod 700 "$WORK"

# Throwaway credentials + SSE-S3 KEK, generated for THIS ephemeral instance only.
read -r ACCESS_KEY SECRET_KEY KEK BUCKET < <("$python" - <<'PY'
import secrets
print(secrets.token_urlsafe(15)[:20],
      secrets.token_urlsafe(30)[:40],
      secrets.token_hex(32),
      "compat-" + secrets.token_hex(6))
PY
)
cat > "$WORK/s3.json" <<JSON
{
  "identities": [
    {
      "name": "compat-harness",
      "credentials": [{"accessKey": "$ACCESS_KEY", "secretKey": "$SECRET_KEY"}],
      "actions": ["Admin", "Read", "Write", "List"]
    }
  ]
}
JSON
chmod 600 "$WORK/s3.json"

teardown() {
  echo
  echo "=== TEARDOWN ==="
  sg docker -c "docker rm -f '$FILER' '$VOLUME' '$MASTER'" >/dev/null 2>&1 || true
  sg docker -c "docker network rm '$NET'" >/dev/null 2>&1 || true
  rm -rf "$WORK"
  echo "removed containers/network/workdir ($WORK)"
  leftover="$(sg docker -c "docker ps -a --filter 'name=${PREFIX}' --format '{{.Names}}'" 2>/dev/null || true)"
  if [[ -n "$leftover" ]]; then
    echo "WARNING: leftover containers: $leftover" >&2
  else
    echo "confirmed: no ${PREFIX}-* containers remain"
  fi
}
trap teardown EXIT

echo "=== EPHEMERAL STACK (image $IMAGE) ==="
sg docker -c "docker image inspect $IMAGE --format 'image id: {{.Id}}  digest: {{range .RepoDigests}}{{.}}{{end}}  created: {{.Created}}'"
sg docker -c "docker network create '$NET'" >/dev/null
echo "network: $NET  workdir: $WORK"

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
  -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json -s3.allowedOrigins=$origin" >/dev/null

PORT="$(sg docker -c "docker port '$FILER' 8333/tcp" | awk -F: '{print $NF}')"
ENDPOINT="http://127.0.0.1:${PORT}"
echo "endpoint: $ENDPOINT (ephemeral host port)"

echo "waiting for the S3 gateway ..."
ready=0
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$ENDPOINT/" || true)"
  if [[ -n "$code" && "$code" != "000" ]]; then ready=1; break; fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "ERROR: S3 gateway did not become reachable at $ENDPOINT" >&2
  sg docker -c "docker logs --tail 50 '$FILER'" 2>&1 || true
  exit 1
fi
echo "gateway reachable (HTTP $code on root)"

set +e
S3_ACCESS_KEY="$ACCESS_KEY" S3_SECRET_KEY="$SECRET_KEY" \
  "$python" "$ROOT_DIR/tests/multipart_compat_client.py" \
  --endpoint "$ENDPOINT" --bucket "$BUCKET" --origin "$origin" \
  --volume-container "$VOLUME"
rc=$?
set -e

echo
echo "harness exit code: $rc (0 = every asserted point passed)"
exit "$rc"
