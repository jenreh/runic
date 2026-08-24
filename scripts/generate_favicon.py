"""Generate the docs favicon set from the rune glyph in ``docs/public/runic.svg``.

The favicon is an *inverted* mark: the rune knocked out in white on a solid,
full-bleed tile. Dark-on-transparent logos collapse into a grey smudge at the
16-24px sizes search engines render, so the tile carries the contrast instead.

Usage:
    uv run python scripts/generate_favicon.py
    uv run python scripts/generate_favicon.py --color "#0E7490"

Requires ``rsvg-convert`` (``brew install librsvg``) for rasterisation.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, NamedTuple

import typer
from PIL import Image

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGO = REPO_ROOT / "docs" / "public" / "runic.svg"
PUBLIC = REPO_ROOT / "docs" / "public"

#: The logo's main colour — the rune's own fill in ``runic.svg``, which is 69% of
#: the mark's ink and the theme's ``--vp-c-brand-1``. Keeping the tile on-brand
#: matters more than raw loudness; the inversion is what buys the legibility.
BRAND = "#354853"

#: Tile edge length in user units. Any square viewBox works; 512 keeps the
#: numbers readable and matches the largest raster we emit.
TILE = 512

#: Glyph height as a fraction of the tile. At 0.74 the rune's counter stays open
#: down to 16px while still filling the circular crop search engines apply.
GLYPH_SCALE = 0.74

#: Corner radius as a fraction of the tile. Visible in browser tabs, where the
#: icon is drawn square; search engines circle-crop it away. The corners are cut
#: to *transparent* rather than filled, so the rounding survives on a dark tab
#: strip instead of showing up as pale notches.
CORNER_RADIUS = 0.16

#: ``favicon.ico`` frames. 48px is what Google's favicon fetcher prefers.
ICO_SIZES = ((16, 16), (32, 32), (48, 48))

#: Size of the standalone PNG fallback that keeps the rounded, transparent tile.
FAVICON_PNG = 96

#: iOS home-screen icon. Deliberately square and opaque: iOS applies its own
#: mask, and any transparency it finds gets composited onto black.
APPLE_TOUCH_PNG = 180


class Box(NamedTuple):
    """Ink bounding box of a glyph in SVG user units."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _require_rsvg() -> str:
    """Return the ``rsvg-convert`` path, or exit with an actionable message."""
    binary = shutil.which("rsvg-convert")
    if binary is None:
        raise typer.BadParameter(
            "rsvg-convert not found. Install it with: brew install librsvg"
        )
    return binary


def rasterise(svg: str, width: int, height: int, binary: str) -> Image.Image:
    """Render ``svg`` markup to an RGBA image of the given pixel dimensions."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.svg"
        dst = Path(tmp) / "out.png"
        src.write_text(svg, encoding="utf-8")
        # Fixed argv: a which()-resolved binary plus paths built here. No shell,
        # and nothing user-supplied reaches the argument list.
        subprocess.run(  # noqa: S603
            [binary, "-w", str(width), "-h", str(height), str(src), "-o", str(dst)],
            check=True,
            capture_output=True,
        )
        return Image.open(dst).convert("RGBA").copy()


def extract_rune(logo: Path) -> str:
    """Return the ``d`` attribute of the rune glyph (the first path in the logo)."""
    match = re.search(r'<path d="([^"]+)"', logo.read_text(encoding="utf-8"))
    if match is None:
        raise typer.BadParameter(f"No <path> found in {logo}")
    return match.group(1)


def ink_box(path_d: str, binary: str, supersample: int = 4) -> Box:
    """Measure the rune's true ink bounds, which Bezier control points overstate."""
    viewbox_w, viewbox_h = 455, 350  # the logo artboard
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {viewbox_w} {viewbox_h}">'
        f'<path d="{path_d}" fill="#000"/></svg>'
    )
    rendered = rasterise(svg, viewbox_w * supersample, viewbox_h * supersample, binary)
    bbox = rendered.split()[3].getbbox()
    if bbox is None:
        raise typer.BadParameter("Rune path rendered empty")
    return Box(*(value / supersample for value in bbox))


def build_svg(path_d: str, box: Box, color: str, *, rounded: bool = True) -> str:
    """Compose the favicon: rune centred and knocked out of a solid tile.

    Pass ``rounded=False`` for the square, full-bleed variant iOS expects.
    """
    scale = TILE * GLYPH_SCALE / box.height
    offset_x = TILE / 2 - (box.x0 + box.x1) / 2 * scale
    offset_y = TILE / 2 - (box.y0 + box.y1) / 2 * scale
    radius = f' rx="{TILE * CORNER_RADIUS:g}"' if rounded else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {TILE} {TILE}" width="{TILE}" height="{TILE}">\n'
        "  <title>runic</title>\n"
        f'  <rect width="{TILE}" height="{TILE}"{radius} fill="{color}"/>\n'
        f'  <g transform="translate({offset_x:.3f} {offset_y:.3f}) '
        f'scale({scale:.6f})">\n'
        f'    <path d="{path_d}" fill="#ffffff"/>\n'
        "  </g>\n"
        "</svg>\n"
    )


def _flatten(image: Image.Image, color: str) -> Image.Image:
    """Composite onto an opaque tile; iOS home-screen icons must not be transparent."""
    background = Image.new("RGBA", image.size, color)
    return Image.alpha_composite(background, image).convert("RGB")


app = typer.Typer(add_completion=False)


@app.command()
def main(
    color: Annotated[str, typer.Option(help="Tile colour as a hex string.")] = BRAND,
) -> None:
    """Write favicon.svg, favicon.ico and the PNG fallbacks into docs/public."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    binary = _require_rsvg()

    path_d = extract_rune(LOGO)
    box = ink_box(path_d, binary)
    log.debug("Rune ink box: %s", box)

    svg = build_svg(path_d, box, color)
    svg_path = PUBLIC / "favicon.svg"
    svg_path.write_text(svg, encoding="utf-8")
    log.info("Wrote %s", svg_path.relative_to(REPO_ROOT))

    # Rounded variants keep their alpha: flattening would fill the cut corners
    # back in and the rounding would vanish.
    master = rasterise(svg, TILE, TILE, binary)

    ico_path = PUBLIC / "favicon.ico"
    master.save(ico_path, sizes=ICO_SIZES)
    log.info("Wrote %s (%s)", ico_path.relative_to(REPO_ROOT), ICO_SIZES)

    png_path = PUBLIC / f"favicon-{FAVICON_PNG}.png"
    master.resize((FAVICON_PNG, FAVICON_PNG), Image.Resampling.LANCZOS).save(
        png_path, optimize=True
    )
    log.info("Wrote %s (%dpx)", png_path.relative_to(REPO_ROOT), FAVICON_PNG)

    # iOS rounds the icon itself, so this one stays square and fully opaque.
    square = rasterise(build_svg(path_d, box, color, rounded=False), TILE, TILE, binary)
    apple_path = PUBLIC / "apple-touch-icon.png"
    _flatten(
        square.resize((APPLE_TOUCH_PNG, APPLE_TOUCH_PNG), Image.Resampling.LANCZOS),
        color,
    ).save(apple_path, optimize=True)
    log.info("Wrote %s (%dpx)", apple_path.relative_to(REPO_ROOT), APPLE_TOUCH_PNG)

    typer.echo(f"Favicon set regenerated in {color}.")


if __name__ == "__main__":
    app()
