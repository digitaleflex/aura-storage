#!/usr/bin/env bash
# Check public TLS certificates and fail when one expires too soon.
# Intended for cron: a non-zero exit means "send an alert".
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

MIN_DAYS="${TLS_MIN_DAYS:-30}"
PORT="${TLS_CHECK_PORT:-443}"

hosts=("$@")
if ((${#hosts[@]} == 0)); then
  if [[ -f .env ]]; then
    while IFS='=' read -r key value; do
      case "$key" in
        APP_DOMAIN|PUBLIC_DOMAIN|S3_DOMAIN|SWAGGER_DOMAIN|DASHBOARD_DOMAIN)
          value="${value%\"}"
          value="${value#\"}"
          [[ -n "$value" ]] && hosts+=("$value")
          ;;
      esac
    done < <(grep -E '^(APP_DOMAIN|PUBLIC_DOMAIN|S3_DOMAIN|SWAGGER_DOMAIN|DASHBOARD_DOMAIN)=' .env || true)
  fi
fi
if ((${#hosts[@]} == 0)); then
  echo "ERROR: no host to check (pass hostnames or set *_DOMAIN in .env)" >&2
  exit 2
fi

now=$(date +%s)
failed=0
seen=' '
for host in "${hosts[@]}"; do
  [[ "$seen" == *" $host "* ]] && continue
  seen+="$host "

  enddate=$(
    echo | openssl s_client -connect "$host:$PORT" -servername "$host" 2>/dev/null \
      | openssl x509 -noout -enddate 2>/dev/null \
      | cut -d= -f2
  )
  if [[ -z "$enddate" ]]; then
    echo "$host: UNREACHABLE" >&2
    failed=1
    continue
  fi
  if ! expires=$(date -d "$enddate" +%s 2>/dev/null); then
    echo "$host: INVALID_DATE ($enddate)" >&2
    failed=1
    continue
  fi

  days=$(( (expires - now) / 86400 ))
  if (( days < 0 )); then
    status=EXPIRED
  elif (( days < MIN_DAYS )); then
    status=LOW
  else
    status=OK
  fi
  printf '%-45s days=%-4s %s\n' "$host" "$days" "$status"
  [[ "$status" == OK ]] || failed=1
done

exit "$failed"
