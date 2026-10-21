#!/usr/bin/env bash
# Clone the open-source projects AURA wants to study, outside the repository.
#
# Read-only by design: shallow clones, no pull, no delete, no checkout of the
# AURA working tree. See docs/engineering/oss-inventory.md for the rationale.
set -euo pipefail

OSS_DIR="${OSS_DIR:-/tmp/opencode/oss}"
DRY_RUN=0
ALL=0
NAMES=()

usage() {
  cat <<'EOF'
Usage: scripts/oss-clone.sh [--all] [--dry-run] [name ...]

Without arguments, clones the priority (P0) set from
docs/engineering/oss-inventory.md. With --all, clones the full inventory.
Named arguments clone only those entries (see --list).

Environment:
  OSS_DIR   destination directory (default: /tmp/opencode/oss)
EOF
}

list_repos() {
  for name in "${!REPOS[@]}"; do
    printf '%-16s %s\n' "$name" "${REPOS[$name]}"
  done | sort
}

declare -A REPOS=(
  [s3-tests]="ceph/s3-tests"
  [tusd]="tus/tusd"
  [tus-js-client]="tus/tus-js-client"
  [restic]="restic/restic"
  [rclone]="rclone/rclone"
  [clamav]="Cisco-Talos/clamav"
  [authelia]="authelia/authelia"
  [casbin]="apache/casbin"
  [schemathesis]="schemathesis/schemathesis"
  [magika]="google/magika"
  [prom-fastapi]="trallnag/prometheus-fastapi-instrumentator"
  [pgbackrest]="pgbackrest/pgbackrest"
  [opencloud]="opencloud-eu/opencloud"
  [cloudserver]="scality/cloudserver"
  [seaweedfs]="seaweedfs/seaweedfs"
  [kopia]="kopia/kopia"
  [openfga]="openfga/openfga"
  [uppy]="transloadit/uppy"
  [filepond]="pqina/filepond"
  [loki]="grafana/loki"
  [prometheus]="prometheus/prometheus"
  [gitleaks]="gitleaks/gitleaks"
  [trivy]="aquasecurity/trivy"
  [pip-audit]="pypa/pip-audit"
  [semgrep]="semgrep/semgrep"
  [garage]="deuxfleurs-org/garage"
  [sftpgo]="drakkan/sftpgo"
)

# Priority set: what unblocks a gate or replaces code we would otherwise write.
P0=(s3-tests tusd tus-js-client restic rclone clamav authelia casbin schemathesis magika prom-fastapi)

for arg in "$@"; do
  case "$arg" in
    --help|-h) usage; exit 0 ;;
    --list) list_repos; exit 0 ;;
    --all) ALL=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -*) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
    *) NAMES+=("$arg") ;;
  esac
done

if [ "$ALL" -eq 0 ] && [ "${#NAMES[@]}" -eq 0 ]; then
  NAMES=("${P0[@]}")
fi

# Never clone inside the AURA working tree: these repos are study material, not
# dependencies, and some of them are AGPL (ADR-006).
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel 2>/dev/null || true)"
mkdir -p "$OSS_DIR"
OSS_ABS="$(cd "$OSS_DIR" && pwd)"
if [ -n "$REPO_ROOT" ]; then
  case "$OSS_ABS" in
    "$REPO_ROOT"|"$REPO_ROOT"/*)
      echo "refusing to clone inside the AURA repository: $OSS_ABS" >&2
      exit 1
      ;;
  esac
fi

failed=0
for name in "${NAMES[@]}"; do
  if [ -z "${REPOS[$name]:-}" ]; then
    echo "unknown project: $name (see --list)" >&2
    failed=1
    continue
  fi
  dest="$OSS_ABS/$name"
  if [ -e "$dest" ]; then
    echo "skip: $name already present at $dest"
    continue
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "would clone: ${REPOS[$name]} -> $dest"
    continue
  fi
  if git clone --depth 1 --single-branch --quiet "https://github.com/${REPOS[$name]}.git" "$dest"; then
    echo "ok: $name ($(du -sh "$dest" 2>/dev/null | cut -f1))"
  else
    echo "failed: $name (${REPOS[$name]})" >&2
    failed=1
  fi
done

if [ "$DRY_RUN" -eq 0 ]; then
  echo "done. sources in: $OSS_ABS"
fi
exit "$failed"
