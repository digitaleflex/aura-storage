#!/usr/bin/env bash
# Reconcile SeaweedFS volume files after deletions and abandoned multipart
# uploads. Run off-peak (03:00) via cron/systemd; the operation is idempotent.
#
#   AURA_INSTANCE_ID=aura-001 SEAWEED_VACUUM_GARBAGE_THRESHOLD=0.3 \
#     /srv/aura-storage/scripts/seaweedfs-vacuum.sh
#
# `volume.vacuum` only compacts volumes whose deleted fraction exceeds the
# threshold, so running it nightly is cheap when nothing needs reclaiming.
set -euo pipefail

INSTANCE="${AURA_INSTANCE_ID:-aura-001}"
VOLUME_CONTAINER="${INSTANCE}-volume"
MASTER="${SEAWEED_MASTER_ADDR:-seaweed-master:9333}"
THRESHOLD="${SEAWEED_VACUUM_GARBAGE_THRESHOLD:-0.3}"

stamp() { printf '[%s] ' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; }

if ! command -v docker >/dev/null 2>&1; then
  stamp; echo "docker is not available" >&2
  exit 2
fi
if ! docker inspect "$VOLUME_CONTAINER" >/dev/null 2>&1; then
  stamp; echo "container $VOLUME_CONTAINER not found" >&2
  exit 2
fi

stamp; echo "SeaweedFS vacuum start (master=$MASTER threshold=$THRESHOLD)"

# The cluster-wide lock is required by volume.vacuum on SeaweedFS 4.48.
# Always send `unlock` so a failed vacuum cannot leave the cluster locked.
out=$(printf 'lock\nvolume.vacuum -garbageThreshold=%s\nunlock\n' "$THRESHOLD" \
  | docker exec -i "$VOLUME_CONTAINER" weed shell -master="$MASTER" 2>&1) || {
    stamp; echo "$out" >&2
    exit 1
  }

stamp; echo "$out" | tail -20
stamp; echo "SeaweedFS vacuum done"
