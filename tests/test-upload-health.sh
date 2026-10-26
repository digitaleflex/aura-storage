#!/usr/bin/env bash
# Offline checks for scripts/upload-health.sh (issue #72 follow-up).
#
# The point of that script is to catch an upload cut by the edge proxy (HTTP
# 499), which exists only in the Traefik access log and never reaches the API.
# These tests feed it synthetic access-log lines, including the internet scanner
# noise this host actually receives, and assert the exit codes a cron job or a
# systemd unit would act on.
#
# No Docker, no network: every case uses `--file`.
set -Euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
pass=0
fail=0
check() { # $1=description $2=0 for pass
  if [[ "$2" == 0 ]]; then echo "PASS: $1"; pass=$((pass + 1)); else echo "FAIL: $1"; fail=$((fail + 1)); fi
}

SCRIPT=scripts/upload-health.sh

# --- fixtures ---------------------------------------------------------------
line() { # $1=method $2=path $3=status $4=router $5=duration
  printf '198.51.100.7 - - [26/Oct/2026:01:00:00 +0000] "%s %s HTTP/1.1" %s 0 "-" "-" 1 "%s" "http://aura-001-filer:8333" %s\n' \
    "$1" "$2" "$3" "$4" "$5"
}

line PUT '/bucket/big.bin?partNumber=3&uploadId=x' 499 'aura-s3@docker' 7200001ms >"$workdir/cut.log"
line PUT '/bucket/big.bin?partNumber=4' 200 'aura-s3@docker' 6900000ms >"$workdir/near.log"
line PUT '/bucket/big.bin?partNumber=5' 502 'aura-s3@docker' 60100ms >"$workdir/fail.log"
line PUT '/bucket/big.bin?partNumber=1' 200 'aura-s3@docker' 950ms >"$workdir/fast.log"
# The host is constantly probed: these must never be counted as uploads.
{
  printf '45.1.2.3 - - [26/Oct/2026:01:30:00 +0000] "GET /autodiscover/autodiscover.xml HTTP/1.1" 404 19 "-" "-" 45 "-" "-" 0ms\n'
  printf '45.1.2.3 - - [26/Oct/2026:01:30:01 +0000] "GET / HTTP/1.1" 404 19 "-" "-" 46 "-" "-" 0ms\n'
} >"$workdir/noise.log"
# A PUT on a non-S3 router (the app) is out of scope for upload health.
line PUT '/api/v1/objects/upload' 502 'aura-app@docker' 200ms >"$workdir/app.log"

run() { # $1=file, sets $out and $rc
  set +e
  out="$("$SCRIPT" --file "$1" 2>&1)"
  rc=$?
  set -e
}

# --- 1. a proxy-cut part is critical ---------------------------------------
run "$workdir/cut.log"
check "a 499 part PUT exits 2 (critical)" "$([[ $rc -eq 2 ]] && echo 0 || echo 1)"
check "the 499 report says the proxy cut the upload" \
  "$(grep -q 'cut by the proxy' <<<"$out" && echo 0 || echo 1)"
check "the offending request is shown" "$(grep -q 'partNumber=3' <<<"$out" && echo 0 || echo 1)"

# --- 2. an upload close to readTimeout warns before it breaks --------------
run "$workdir/near.log"
check "an upload at >=80% of readTimeout exits 1 (warning)" "$([[ $rc -eq 1 ]] && echo 0 || echo 1)"
check "the warning names readTimeout" "$(grep -q 'readTimeout' <<<"$out" && echo 0 || echo 1)"

# --- 3. a 5xx on an upload is critical -------------------------------------
run "$workdir/fail.log"
check "a 502 part PUT exits 2 (critical)" "$([[ $rc -eq 2 ]] && echo 0 || echo 1)"
check "the 5xx report is distinct from the 499 one" \
  "$(grep -q 'failed at the proxy' <<<"$out" && echo 0 || echo 1)"

# --- 4. a healthy upload is silent ----------------------------------------
run "$workdir/fast.log"
check "a fast successful upload exits 0" "$([[ $rc -eq 0 ]] && echo 0 || echo 1)"
check "a healthy window reports OK" "$(grep -q 'OK: no cut' <<<"$out" && echo 0 || echo 1)"

# --- 5. scanner noise and non-S3 routers are not uploads -------------------
run "$workdir/noise.log"
check "probe traffic exits 0" "$([[ $rc -eq 0 ]] && echo 0 || echo 1)"
check "probe traffic is not counted as an upload" \
  "$(grep -q '0 upload request' <<<"$out" && echo 0 || echo 1)"
run "$workdir/app.log"
check "a non-S3 router PUT is out of scope" \
  "$(grep -q '0 upload request' <<<"$out" && echo 0 || echo 1)"

# --- 6. JSON output is machine readable -----------------------------------
set +e
json="$("$SCRIPT" --file "$workdir/cut.log" --json 2>&1)"
set -e
check "json mode emits a single object on stdout" \
  "$([[ "$json" == \{*\} ]] && echo 0 || echo 1)"
check "json mode reports the cut counter" \
  "$(grep -q '"cut_499":1' <<<"$json" && echo 0 || echo 1)"
check "json mode reports the configured readTimeout" \
  "$(grep -q '"read_timeout_s":7200' <<<"$json" && echo 0 || echo 1)"

# --- 7. an unreadable source is a tooling error, not a health verdict ------
set +e
"$SCRIPT" --file "$workdir/does-not-exist.log" >/dev/null 2>&1
rc=$?
set -e
check "a missing log file exits 3 (check could not run)" "$([[ $rc -eq 3 ]] && echo 0 || echo 1)"

# --- 8. the threshold follows READ_TIMEOUT_S, it is not hardcoded ---------
set +e
out="$(READ_TIMEOUT_S=600 "$SCRIPT" --file "$workdir/near.log" 2>&1)"
rc=$?
set -e
check "a shorter readTimeout makes the same upload critical" \
  "$([[ $rc -eq 2 ]] && echo 0 || echo 1)"

echo
echo "upload-health: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
