#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
bash ./scripts/bootstrap.sh
# Rebuild images built from source (the api service, `build: ./api`) so the
# running stack matches this checkout instead of reusing a stale local image.
docker compose build
# Pull only registry images. A plain `docker compose pull` also tries to pull
# `aura-api:local`, which is built locally and does not exist in a registry, so
# it fails (and, with `set -e`, aborts the deploy before `up -d`).
docker compose pull --ignore-buildable
docker compose up -d
docker compose ps
