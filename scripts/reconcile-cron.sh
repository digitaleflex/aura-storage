#!/usr/bin/env bash
# Scheduler entry point for periodic reconciliation (A7).
# Invoked by cron or systemd timer. Requires AURA_API_BASE and AURA_ADMIN_TOKEN.
set -euo pipefail
: "${AURA_API_BASE:?AURA_API_BASE required}"
curl -fsS -X POST "${AURA_API_BASE}/api/v1/admin/reconcile" -H "Authorization: Bearer ${AURA_ADMIN_TOKEN:-}" >/dev/null
curl -fsS -X POST "${AURA_API_BASE}/api/v1/admin/reconcile-terminal" -H "Authorization: Bearer ${AURA_ADMIN_TOKEN:-}" >/dev/null
echo "reconciliation done $(date -u +%FT%TZ)"
EOF