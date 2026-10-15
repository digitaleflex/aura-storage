#!/usr/bin/env bash
# Regression test for the landing page answering the S3 root (issue: raw XML on `GET /`).
#
# No network, no Docker, no real endpoint. Static checks on the Compose routing,
# the nginx server block, the template and the entrypoint guards.
#
# The contract under test:
#   * an UNSIGNED `GET /` on S3_DOMAIN is served the HTML page;
#   * signed requests and every non-root path keep reaching SeaweedFS;
#   * no domain is hardcoded: .env remains the single source of truth.
set -Euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

pass=0
fail=0
check() { # $1=description, $2=condition result (0 = pass)
  if [[ "$2" == "0" ]]; then
    echo "PASS: $1"
    pass=$((pass + 1))
  else
    echo "FAIL: $1"
    fail=$((fail + 1))
  fi
}

COMPOSE="docker-compose.yml"
TEMPLATE="landing/index.template.html"
ENTRYPOINT="landing/entrypoint.sh"

# --- Compose routing -------------------------------------------------------
rule="$(grep -o 'traefik.http.routers.aura-s3-landing.rule=.*' "$COMPOSE")"
check "landing router rule exists" "$([[ -n "$rule" ]] && echo 0 || echo 1)"
check "landing rule is scoped to the S3 host" "$([[ "$rule" == *'Host(`${S3_DOMAIN:?Set S3_DOMAIN in .env}`)'* ]] && echo 0 || echo 1)"
check "landing rule matches the root path only" "$([[ "$rule" == *'Path(`/`)'* ]] && echo 0 || echo 1)"
check "landing rule matches GET only" "$([[ "$rule" == *'Method(`GET`)'* ]] && echo 0 || echo 1)"
check "landing rule excludes signed requests" "$([[ "$rule" == *'!HeaderRegexp(`Authorization`, `.+`)'* ]] && echo 0 || echo 1)"
check "landing rule does not use a path prefix" "$([[ "$rule" != *PathPrefix* ]] && echo 0 || echo 1)"
check "landing priority is explicit" "$(grep -q 'traefik.http.routers.aura-s3-landing.priority=1000' "$COMPOSE" && echo 0 || echo 1)"

# The S3 router itself must stay a plain host match: adding a path/predicate there
# would silently narrow the API surface for clients.
s3_rule="$(grep -o 'traefik.http.routers.aura-s3.rule=.*' "$COMPOSE")"
check "S3 router rule is unchanged host-only" "$([[ "$s3_rule" == 'traefik.http.routers.aura-s3.rule=Host(`${S3_DOMAIN:?Set S3_DOMAIN in .env}`)' ]] && echo 0 || echo 1)"

# --- nginx server block ----------------------------------------------------
check "landing server listens on 80" "$(grep -q 'listen 80;' landing/nginx.conf && echo 0 || echo 1)"
check "landing server serves the rendered html root" "$(grep -q 'root /usr/share/nginx/html;' landing/nginx.conf && echo 0 || echo 1)"
check "landing server answers the root path" "$(grep -q 'location = / {' landing/nginx.conf && echo 0 || echo 1)"
check "landing server does not proxy anything" "$(! grep -q 'proxy_pass' landing/nginx.conf && echo 0 || echo 1)"

# --- Template rendering ----------------------------------------------------
check "template carries no hardcoded domain" "$(! grep -qE 'eurinhash|https://[a-z0-9.-]+\.(com|net|org)/' "$TEMPLATE" && echo 0 || echo 1)"

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
S3_DOMAIN=s3.example.test APP_DOMAIN=app.example.test \
  envsubst '${S3_DOMAIN} ${APP_DOMAIN}' <"$TEMPLATE" >"$rendered"
check "placeholder S3_DOMAIN is substituted" "$(grep -q 's3.example.test' "$rendered" && echo 0 || echo 1)"
check "placeholder APP_DOMAIN is substituted" "$(grep -q 'app.example.test' "$rendered" && echo 0 || echo 1)"
check "no placeholder left after substitution" "$(! grep -q '\${' "$rendered" && echo 0 || echo 1)"
check "primary action targets the app root" "$(grep -q 'href="https://app.example.test/"' "$rendered" && echo 0 || echo 1)"

check "rendered page is parseable HTML" \
  "$(python3 - "$rendered" <<'PY' && echo 0 || echo 1
import html.parser, sys

class P(html.parser.HTMLParser):
    pass

with open(sys.argv[1], encoding="utf-8") as fh:
    P().feed(fh.read())
PY
)"
check "rendered page is declared as French" "$(grep -q '<html lang="fr">' "$rendered" && echo 0 || echo 1)"
check "rendered page carries a title" "$(grep -q '<title>' "$rendered" && echo 0 || echo 1)"
check "rendered page is not indexable" "$(grep -q 'name="robots" content="noindex"' "$rendered" && echo 0 || echo 1)"

# --- Entrypoint guards (fail fast, before touching the filesystem) ---------
out="$(env -u S3_DOMAIN APP_DOMAIN=app.example.test sh "$ENTRYPOINT" 2>&1)" && rc=0 || rc=$?
check "entrypoint refuses a missing S3_DOMAIN" "$([[ $rc -ne 0 && "$out" == *S3_DOMAIN* ]] && echo 0 || echo 1)"

out="$(env -u APP_DOMAIN S3_DOMAIN=s3.example.test sh "$ENTRYPOINT" 2>&1)" && rc=0 || rc=$?
check "entrypoint refuses a missing APP_DOMAIN" "$([[ $rc -ne 0 && "$out" == *APP_DOMAIN* ]] && echo 0 || echo 1)"

# --- Optional webfont dependency ------------------------------------------
# Fonts come from the built frontend (web/dist is git-ignored); check them when present.
if [[ -d web/dist/fonts ]]; then
  missing=0
  while read -r font; do
    [[ -f "web/dist/fonts/$font" ]] || missing=1
  done < <(grep -o '/fonts/[^")]*\.woff2' "$TEMPLATE" | sed 's|/fonts/||' | sort -u)
  check "every referenced webfont exists in web/dist/fonts" "$missing"
else
  echo "SKIP: web/dist/fonts absent (frontend not built), webfonts unchecked"
fi

echo "== $pass passed, $fail failed =="
[[ $fail -eq 0 ]]
