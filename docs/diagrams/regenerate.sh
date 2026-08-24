#!/usr/bin/env bash
set -euo pipefail
# Regenerate the runic.ogm architecture diagram assets from the .drawio source.
#
#   ./docs/diagrams/regenerate.sh
#
# Source of truth : docs/diagrams/runic-ogm-architecture.drawio
# Output          : docs/public/diagrams/runic-ogm-architecture.svg  (served by VitePress)
#
# Requires: draw.io desktop CLI (brew install --cask drawio) and the drawio-skill scripts.

cd "$(git rev-parse --show-toplevel)"

SRC="docs/diagrams/runic-ogm-architecture.drawio"
OUT="docs/public/diagrams"
SKILL="${DRAWIO_SKILL_DIR:-$HOME/.claude/plugins/cache/365-skills/drawio/2.1.0/skills/drawio-skill}"

mkdir -p "$OUT"

echo "==> Validating source"
python3 "$SKILL/scripts/validate.py" "$SRC" --score

echo "==> Exporting SVG (fonts unembedded: ~31 KB vs ~390 KB embedded)"
drawio -x -f svg --embed-svg-fonts false -o "$OUT/runic-ogm-architecture.svg" "$SRC" 2>/dev/null | tail -1

echo "==> Done"
ls -la "$OUT/runic-ogm-architecture.svg" | awk '{printf "    %-52s %7.1f KB\n", $9, $5/1024}'
