#!/bin/sh
# Renders the landing template with the deployment's own domains, then starts nginx.
# Runs inside the pinned nginx:alpine image (docker-compose.yml, service `s3-landing`).
# The domains are never hardcoded: .env stays the single source of truth.
set -eu

: "${S3_DOMAIN:?S3_DOMAIN is required}"
: "${APP_DOMAIN:?APP_DOMAIN is required}"

template=/opt/aura-landing/index.template.html
fonts_src=/opt/aura-landing-fonts
out=/usr/share/nginx/html

[ -f "$template" ] || {
  echo "s3-landing: missing $template" >&2
  exit 1
}

mkdir -p "$out/fonts"
envsubst '${S3_DOMAIN} ${APP_DOMAIN}' <"$template" >"$out/index.html"

# Optional: webfonts are a progressive enhancement, a missing build must not
# take the page down (the CSS falls back to system-ui).
if ls "$fonts_src"/*.woff2 >/dev/null 2>&1; then
  cp -f "$fonts_src"/*.woff2 "$out/fonts/"
else
  echo "s3-landing: no webfonts in $fonts_src, using system fonts" >&2
fi

if grep -q '\${' "$out/index.html"; then
  echo "s3-landing: unsubstituted placeholder left in index.html" >&2
  exit 1
fi

# The security headers and the HEAD/list-type behaviour live in nginx.conf.
# It was mounted but never installed, so the image's default server answered
# without CSP/X-Frame-Options/nosniff.
if [ -f /opt/aura-landing/nginx.conf ]; then
  cp -f /opt/aura-landing/nginx.conf /etc/nginx/conf.d/default.conf
fi

exec nginx -g 'daemon off;'
