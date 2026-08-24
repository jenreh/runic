#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools"]
# ///
"""Regenerate the "runic" wordmark outlines in docs/diagrams/og-image.svg.

    uv run docs/diagrams/wordmark.py

The card is rendered by rsvg-convert, which resolves fonts through CoreText and
therefore only sees system-installed faces — a webfont reference would silently
fall back to Helvetica. So the wordmark is stored as outlines of the docs
site's headline face (Stack Sans Notch, the same font as the site's `h1`), and
this script is what produces them. Everything else on the card stays live text.
"""

import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

from fontTools.misc.transform import Transform
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FAMILY = "Stack Sans Notch"
WEIGHT = 700
TEXT = "runic"
SIZE = 86  # px
ORIGIN = (86, 300)  # baseline start, matching the card's left text column
TRACKING = -0.03  # em; the site's headline face runs loose at this size

SVG = pathlib.Path(__file__).with_name("og-image.svg")
WORDMARK_RE = re.compile(r'<path fill="#ffffff" d="[^"]*"/>')


def font_path() -> pathlib.Path:
    """Download the Google Fonts static TTF for FAMILY/WEIGHT into a temp file."""
    css_url = (
        f"https://fonts.googleapis.com/css2?family={FAMILY.replace(' ', '+')}"
        f":wght@{WEIGHT}&display=swap"
    )
    # A legacy user agent makes Google Fonts serve .ttf instead of .woff2.
    request = urllib.request.Request(css_url, headers={"User-Agent": "Mozilla/4.0"})
    css = urllib.request.urlopen(request).read().decode()
    match = re.search(r"src: url\((\S+?\.ttf)\)", css)
    if not match:
        sys.exit(f"error: no static TTF for {FAMILY} {WEIGHT}")
    target = pathlib.Path(tempfile.mkdtemp()) / f"{FAMILY.replace(' ', '')}.ttf"
    urllib.request.urlretrieve(match.group(1), target)
    return target


def outlines() -> str:
    """Return the SVG path data for TEXT, positioned as it sits on the card."""
    font = TTFont(font_path())
    scale = SIZE / font["head"].unitsPerEm
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    pen = SVGPathPen(glyphs)
    x, y = ORIGIN
    for char in TEXT:
        glyph = glyphs[cmap[ord(char)]]
        glyph.draw(TransformPen(pen, Transform(scale, 0, 0, -scale, x, y)))
        x += glyph.width * scale + TRACKING * SIZE
    return re.sub(r"(\d+\.\d{3})\d+", r"\1", pen.getCommands())


def main() -> None:
    svg = SVG.read_text()
    if not WORDMARK_RE.search(svg):
        sys.exit(f"error: no wordmark path found in {SVG}")
    SVG.write_text(WORDMARK_RE.sub(f'<path fill="#ffffff" d="{outlines()}"/>', svg))
    print(f"==> Wordmark updated in {SVG}")
    subprocess.run([str(SVG.with_name("regenerate-og.sh"))], check=True)


if __name__ == "__main__":
    main()
