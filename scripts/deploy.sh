#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
./scripts/bootstrap.sh
docker compose pull
docker compose up -d
docker compose ps
