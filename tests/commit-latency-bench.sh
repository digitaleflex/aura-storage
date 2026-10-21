#!/usr/bin/env bash
# COMMIT-LATENCY-01 — ephemeral commit-latency benchmark stack.
#
# Symptom under test: "the upload finishes but the file stays pending for ages".
# This wrapper starts an ISOLATED, throwaway SeaweedFS 4.48 stack (own docker
# network, own container names, own data dir under /tmp/opencode, throwaway S3
# credentials and a throwaway SSE-S3 KEK generated per run, ephemeral host port)
# and runs tests/commit_latency_bench.py against it: PUT (SSE-S3 AES256) ->
# HEAD -> commit rehash (get_object + 1 MiB iter_chunks + sha256, exactly
# api/main.py:700-704).
#
# It NEVER creates, inspects or touches the pilot stack (aura-001-* / compose
# project "aura-storage") and never reads the pilot .env.
#
# Usage:
#   sg docker -c 'bash tests/commit-latency-bench.sh' [--sizes 8,64,256] [--concurrency 4]
#   sg docker -c 'bash tests/commit-latency-bench.sh' --sizes 8M,256M,1G --json /tmp/opencode/bench.json
#
# Exit codes: 0 = run completed (per-size failures are reported as UNKNOWN/ERROR
# inside the table), non-zero = hard error (stack never came up, client crashed).
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

IMAGE="chrislusf/seaweedfs:4.48"
PREFIX="bench-commit"
NET="${PREFIX}-net"
MASTER="${PREFIX}-master"
VOLUME="${PREFIX}-volume"
FILER="${PREFIX}-filer"
RUN_ID="$(date -u +%s)-$$"
WORK="/tmp/opencode/${PREFIX}-${RUN_ID}"
ORIGIN="https://bench.example.test"
JSON_OUT=""

usage() {
  echo "usage: sg docker -c 'bash tests/commit-latency-bench.sh' [--sizes 8,64,256] [--concurrency 4] [--json OUT]"
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --json) JSON_OUT="<next-arg>" ;;
    --json=*) JSON_OUT="${arg#--json=}" ;;
  esac
done
# Resolve "--json OUT" (two-token form) without fighting the argument forwarding.
args=("$@")
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == "--json" ]]; then
    if (( i + 1 < ${#args[@]} )); then JSON_OUT="${args[$((i+1))]}"; fi
  fi
done

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 1; }
python="$ROOT_DIR/.venv/bin/python"
[[ -x "$python" ]] || python="$(command -v python3)"
command -v "$python" >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
"$python" -c 'import boto3' >/dev/null 2>&1 || {
  echo "ERROR: boto3 missing for $python; use .venv/bin/python." >&2; exit 1; }

# ---- preflight: isolation -------------------------------------------------
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

# ---- preflight: free space (workdir lives on /tmp, often a small tmpfs) ----
mkdir -p /tmp/opencode
chmod 700 /tmp/opencode 2>/dev/null || true
avail_mib="$(df -Pm /tmp/opencode | awk 'NR==2{print $4}')"
sizes_raw="8,64,256"
conc=1
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    --sizes) if (( i + 1 < ${#args[@]} )); then sizes_raw="${args[$((i+1))]}"; fi ;;
    --sizes=*) sizes_raw="${args[$i]#--sizes=}" ;;
    --concurrency) if (( i + 1 < ${#args[@]} )); then conc="${args[$((i+1))]}"; fi ;;
    --concurrency=*) conc="${args[$i]#--concurrency=}" ;;
  esac
done
[[ "$conc" =~ ^[0-9]+$ ]] && (( conc >= 1 )) || conc=1
read -r total_mib min_mib < <(SIZES_RAW="$sizes_raw" "$python" - <<'PY'
import os
raw = os.environ["SIZES_RAW"]
vals = []
for tok in raw.split(","):
    tok = tok.strip()
    if not tok:
        continue
    num, mult = tok, 1.0
    for suffix, factor in (("GIB", 1024), ("MIB", 1), ("KIB", 1 / 1024),
                           ("GB", 1024), ("MB", 1), ("KB", 1 / 1024),
                           ("G", 1024), ("M", 1), ("K", 1 / 1024), ("B", 1 / 1048576)):
        if tok.upper().endswith(suffix):
            num = tok[: len(tok) - len(suffix)]
            mult = factor
            break
    try:
        vals.append(int(round(float(num) * mult)))
    except ValueError:
        pass
print(sum(vals), min(vals) if vals else 0)
PY
)
required_mib=$(( total_mib * conc * 3 ))
smallest_mib=$(( min_mib * conc * 3 ))
if (( required_mib > avail_mib )); then
  echo "WARNING: sizes need ~${required_mib} MiB with 3x headroom, only ${avail_mib} MiB free on /tmp/opencode." >&2
  echo "         oversized sizes will be SKIPPED by the client (reported as UNKNOWN)." >&2
fi
if (( smallest_mib > avail_mib )); then
  echo "ERROR: not even the smallest size fits (${smallest_mib} MiB needed, ${avail_mib} MiB free)." >&2
  echo "       Free space or pass smaller --sizes." >&2
  exit 1
fi

mkdir -p "$WORK/master" "$WORK/volume" "$WORK/filer"
chmod 700 "$WORK"

# Throwaway credentials + SSE-S3 KEK, valid for THIS ephemeral instance only.
read -r ACCESS_KEY SECRET_KEY KEK BUCKET < <("$python" - <<'PY'
import secrets
print(secrets.token_urlsafe(15)[:20],
      secrets.token_urlsafe(30)[:40],
      secrets.token_hex(32),
      "bench-" + secrets.token_hex(6))
PY
)
cat > "$WORK/s3.json" <<JSON
{
  "identities": [
    {
      "name": "commit-latency-bench",
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
    echo "confirmed: no ${PREFIX}* containers remain"
  fi
}
trap teardown EXIT

echo "=== COMMIT-LATENCY-01 ephemeral stack (image $IMAGE) ==="
sg docker -c "docker image inspect $IMAGE --format 'image id: {{.Id}}  digest: {{range .RepoDigests}}{{.}}{{end}}'"
echo "network: $NET  workdir: $WORK  free: ${avail_mib} MiB  sizes: ${sizes_raw}  concurrency: ${conc}"

sg docker -c "docker network create '$NET'" >/dev/null

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

PORT="$(sg docker -c "docker port '$FILER' 8333/tcp" | awk -F: '{print $NF}')"
ENDPOINT="http://127.0.0.1:${PORT}"
echo "endpoint: $ENDPOINT (ephemeral host port)"

echo "waiting for the S3 gateway (HTTP 403 on / means up) ..."
ready=0
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$ENDPOINT/" || true)"
  # 403 = gateway answered and refused the anonymous request: it is up.
  if [[ "$code" == "403" || "$code" == "200" ]]; then ready=1; break; fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "ERROR: S3 gateway did not become reachable at $ENDPOINT (last HTTP ${code:-000})" >&2
  sg docker -c "docker logs --tail 50 '$FILER'" 2>&1 || true
  exit 1
fi
echo "gateway reachable (HTTP $code on root)"

# Keep the raw JSON outside the workdir unless the caller chose a path.
extra=()
if [[ -z "$JSON_OUT" ]]; then
  extra=(--json "$WORK/results.json")
  JSON_OUT="/tmp/opencode/${PREFIX}-results-${RUN_ID}.json"
fi

set +e
S3_ACCESS_KEY="$ACCESS_KEY" S3_SECRET_KEY="$SECRET_KEY" \
  "$python" "$ROOT_DIR/tests/commit_latency_bench.py" \
  --endpoint "$ENDPOINT" --bucket "$BUCKET" --workdir "$WORK" \
  "${args[@]+"${args[@]}"}" "${extra[@]+"${extra[@]}"}"
rc=$?
set -e

if [[ -f "$WORK/results.json" && "$JSON_OUT" != "$WORK/results.json" ]]; then
  cp "$WORK/results.json" "$JSON_OUT" 2>/dev/null && echo "raw JSON kept at: $JSON_OUT"
fi
if (( rc != 0 )); then
  echo "benchmark client exited $rc — no complete table (see errors above)" >&2
fi
echo
echo "harness exit code: $rc (0 = run completed)"
exit "$rc"
