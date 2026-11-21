"""Vazirmatn with a hollow Persian zero (۰ as a small ring instead of a dot), for the app, web, panel and covers.

A dot-like zero was hard to read next to other digits (e.g. «۰ دقیقه»); the ring stays smaller than ۵, so ۵۰ and ۵۵
do not mix. Only the glyphs of ۰ (U+06F0) and ٠ (U+0660) change; the font keeps its names, so nothing else changes.
Vazirmatn is under the SIL Open Font License 1.1 (no reserved font name), which allows modified versions.

Run from app/:  python scripts/font-zero.py   (needs fonttools; writes assets/fonts/ and the backend copies)
"""
import math
import shutil
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

SRC = Path("node_modules/@expo-google-fonts/vazirmatn")
OUT = Path("assets/fonts")
BACKEND = [Path("../backend/apps/catalog/static/catalog/fonts"), Path("../backend/apps/website/static/website/fonts")]
WEIGHTS = {"400Regular": 114, "700Bold": 170, "800ExtraBold": 188, "900Black": 206}  # ring thickness, font units
SEGMENTS = 16


def circle(pen, cx, cy, r, clockwise):
    """A circle as quadratic curves: on-curve points on the circle, off-curve points at the tangent crossings."""
    step = 2 * math.pi / SEGMENTS * (-1 if clockwise else 1)
    k = r / math.cos(abs(step) / 2)
    pen.moveTo((round(cx + r), round(cy)))
    for i in range(SEGMENTS):
        a0, a1 = i * step, (i + 1) * step
        mid = (a0 + a1) / 2
        pen.qCurveTo((round(cx + k * math.cos(mid)), round(cy + k * math.sin(mid))),
                     (round(cx + r * math.cos(a1)), round(cy + r * math.sin(a1))))
    pen.closePath()


def ring(font, name, thickness):
    from fontTools.pens.boundsPen import BoundsPen

    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    x0, y0, x1, y1 = bp.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = (x1 - x0) / 2 * 0.95  # about the old diamond's size, smaller than ۵
    pen = TTGlyphPen(gs)
    circle(pen, cx, cy, r, clockwise=True)
    circle(pen, cx, cy, r - thickness, clockwise=False)
    font["glyf"][name] = pen.glyph()
    glyph = font["glyf"][name]
    glyph.recalcBounds(font["glyf"])
    width, _ = font["hmtx"][name]
    font["hmtx"][name] = (width, glyph.xMin)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for weight, thickness in WEIGHTS.items():
        font = TTFont(SRC / weight / f"Vazirmatn_{weight}.ttf")
        cmap = font.getBestCmap()
        for code in (0x06F0, 0x0660):
            ring(font, cmap[code], thickness)
        if "hdmx" in font:
            del font["hdmx"]
        target = OUT / f"Vazirmatn_{weight}.ttf"
        font.save(target)
        for folder in BACKEND:
            if (folder / target.name).exists():
                shutil.copy(target, folder / target.name)
        print("wrote", target)
    shutil.copy(SRC / "LICENSE_FONT", OUT / "LICENSE_FONT.txt")


if __name__ == "__main__":
    main()
