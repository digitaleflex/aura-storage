#!/usr/bin/env bash
# Install Playwright Chromium's missing Ubuntu packages without root.
# Libraries and fonts are extracted under /tmp/opencode/pwlibs by default.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/web"
LIBS_DIR="${PLAYWRIGHT_LIBS_DIR:-/tmp/opencode/pwlibs}"
DEBS_DIR="${LIBS_DIR}/debs"
EXTRACT_DIR="${LIBS_DIR}/root"
FONTCONFIG_FILE="${LIBS_DIR}/fonts.conf"

mkdir -p "${DEBS_DIR}" "${EXTRACT_DIR}" "${LIBS_DIR}/font-cache"

cd "${WEB_DIR}"
DRY_OUTPUT="$(npx playwright install-deps chromium --dry-run 2>&1 || true)"
mapfile -t PACKAGES < <(
  printf '%s\n' "${DRY_OUTPUT}" | awk '
    /^Missing system dependencies/ { in_list = 1; next }
    in_list && /^[[:space:]]+[^[:space:]]/ { print $1; next }
    in_list { exit }
  '
)

if [[ ${#PACKAGES[@]} -eq 0 ]]; then
  echo "No missing Playwright system dependencies reported."
  exit 0
else
  echo "Downloading ${#PACKAGES[@]} packages without root..."
  cd "${DEBS_DIR}"
  apt-get download "${PACKAGES[@]}"
  echo "Extracting packages into ${EXTRACT_DIR}..."
  for archive in "${DEBS_DIR}"/*.deb; do
    dpkg-deb -x "${archive}" "${EXTRACT_DIR}"
  done
fi

LIB_DIR="$(find "${EXTRACT_DIR}/usr/lib" -maxdepth 1 -type d -name '*-linux-gnu' | head -1 || true)"
[[ -n "${LIB_DIR}" ]] || LIB_DIR="${EXTRACT_DIR}/usr/lib/x86_64-linux-gnu"

cat >"${FONTCONFIG_FILE}" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>/usr/share/fonts</dir>
  <dir>${EXTRACT_DIR}/usr/share/fonts</dir>
  <cachedir>${LIBS_DIR}/font-cache</cachedir>
  <alias>
    <family>sans-serif</family>
    <prefer><family>DejaVu Sans</family><family>Liberation Sans</family></prefer>
  </alias>
  <alias>
    <family>serif</family>
    <prefer><family>DejaVu Serif</family><family>Liberation Serif</family></prefer>
  </alias>
  <alias>
    <family>monospace</family>
    <prefer><family>DejaVu Sans Mono</family><family>Liberation Mono</family></prefer>
  </alias>
</fontconfig>
EOF

LD_LIBRARY_PATH="${LIB_DIR}" FONTCONFIG_FILE="${FONTCONFIG_FILE}" \
  "${EXTRACT_DIR}/usr/bin/fc-cache" -f

echo "Playwright dependencies installed in ${LIBS_DIR}."
echo "Run browser tests with:"
echo "  export LD_LIBRARY_PATH=${LIB_DIR}"
echo "  export FONTCONFIG_FILE=${FONTCONFIG_FILE}"
