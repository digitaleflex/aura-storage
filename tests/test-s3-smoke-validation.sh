#!/usr/bin/env bash
# Regression test for tests/s3-smoke-test.sh variable validation.
#
# Covers the Mission 2 P0 bug: the required-variable expansions must NOT be
# backslash-escaped, otherwise missing variables go undetected.
# No network, no Docker, no real endpoint: S3 calls go to a stub `aws`.
set -Euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

TARGET="tests/s3-smoke-test.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# Stub aws: emulate `s3 cp` upload/download via a stage file, accept `s3 rm`.
mkdir -p "$workdir/bin"
export STUB_STAGE_FILE="$workdir/staged.txt"
cat > "$workdir/bin/aws" <<'STUB'
#!/usr/bin/env bash
set -Euo pipefail
args=("$@")
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == "cp" ]]; then
    src="${args[$((i + 1))]}"
    dst="${args[$((i + 2))]}"
    if [[ "$dst" == s3://* && -f "$src" ]]; then
      cp -- "$src" "$STUB_STAGE_FILE"
      exit 0
    fi
    if [[ "$src" == s3://* ]]; then
      cp -- "$STUB_STAGE_FILE" "$dst"
      exit 0
    fi
  fi
done
exit 0
STUB
chmod +x "$workdir/bin/aws"

pass=0
fail=0
expect_fail_with() { # $1=description $2=expected message fragment, rest=env assignments
  local desc="$1" needle="$2"
  shift 2
  local out rc
  out="$(env -u S3_ENDPOINT -u S3_BUCKET -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY "$@" bash "$TARGET" 2>&1)" && rc=0 || rc=$?
  if [[ $rc -ne 0 && "$out" == *"$needle"* ]]; then
    echo "PASS: $desc"
    pass=$((pass + 1))
  else
    echo "FAIL: $desc (rc=$rc, out=$out)"
    fail=$((fail + 1))
  fi
}

expect_fail_with "missing S3_ENDPOINT fails fast" "S3_ENDPOINT"
expect_fail_with "missing S3_BUCKET fails fast" "S3_BUCKET" "S3_ENDPOINT=https://example.invalid"
expect_fail_with "missing AWS_ACCESS_KEY_ID fails fast" "AWS_ACCESS_KEY_ID" "S3_ENDPOINT=https://example.invalid" "S3_BUCKET=b"
expect_fail_with "missing AWS_SECRET_ACCESS_KEY fails fast" "AWS_SECRET_ACCESS_KEY" "S3_ENDPOINT=https://example.invalid" "S3_BUCKET=b" "AWS_ACCESS_KEY_ID=k"

echo "--- full run against stub aws ---"
if PATH="$workdir/bin:$PATH" \
  S3_ENDPOINT=https://example.invalid S3_BUCKET=b AWS_ACCESS_KEY_ID=k AWS_SECRET_ACCESS_KEY=s \
  bash "$TARGET" 2>&1; then
  echo "PASS: validation passes and stubbed upload/download round-trip succeeds"
  pass=$((pass + 1))
else
  echo "FAIL: stubbed round-trip did not succeed"
  fail=$((fail + 1))
fi

echo "== $pass passed, $fail failed =="
[[ $fail -eq 0 ]]
