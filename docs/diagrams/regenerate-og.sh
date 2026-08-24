#!/usr/bin/env bash
set -euo pipefail
# Regenerate the Open Graph / social card image from its SVG source.
#
#   ./docs/diagrams/regenerate-og.sh
#
# Source of truth : docs/diagrams/og-image.svg
# Output          : docs/public/og-runic.png  (1200x630, referenced from
#                   docs/.vitepress/config.mts as og:image / twitter:image)
#
# The logo is inlined as a base64 data URI at render time, so the source SVG
# carries a __RUNIC_LOGO_B64__ placeholder instead of a 40 KB blob.
#
# Requires: rsvg-convert (brew install librsvg).

cd "$(git rev-parse --show-toplevel)"

SRC="docs/diagrams/og-image.svg"
LOGO="docs/public/runic.svg"
OUT="docs/public/og-runic.png"
TMP="$(mktemp -t runic-og-XXXXXX).svg"
trap 'rm -f "$TMP"' EXIT

echo "==> Inlining $LOGO"
LOGO_B64="$(base64 -i "$LOGO" | tr -d '\n')" \
  python3 -c 'import os,pathlib,sys; p=pathlib.Path(sys.argv[1]); pathlib.Path(sys.argv[2]).write_text(p.read_text().replace("__RUNIC_LOGO_B64__", os.environ["LOGO_B64"]))' \
  "$SRC" "$TMP"

echo "==> Rendering 1200x630 PNG"
rsvg-convert -w 1200 -h 630 "$TMP" -o "$OUT"

echo "==> Done"
ls -la "$OUT" | awk '{printf "    %-40s %7.1f KB\n", $9, $5/1024}'
