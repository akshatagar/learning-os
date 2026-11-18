"""Draws desktop/learning-os.ico: the Resolve mark (two sources curving into
one red concept) on the app's black tile. Run again only if the mark changes:

    uv run python desktop/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 4096          # drawn at 4x, then scaled down smoothly for every icon size
UNIT = S / 32     # the mark is designed on a 32-unit grid (web/static/favicon.svg)
INK = "#ededea"
SIGNAL = "#ff5a3c"
TILE = "#0a0a0b"
STROKE = 2.4 * UNIT   # the top-bar weight; the 16px favicon uses 3


def pt(x, y):
    return (x * UNIT, y * UNIT)


def cubic(p0, p1, p2, p3, steps=64):
    """Points along a cubic Bézier, in grid units."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        out.append(pt(a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                      a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def ring(draw, cx, cy, r):
    x, y = pt(cx, cy)
    # SVG centres a stroke on the circle; Pillow draws an outline inside its
    # box, so the box grows by half a stroke to put the line where SVG does.
    rr = r * UNIT + STROKE / 2
    draw.ellipse((x - rr, y - rr, x + rr, y + rr), outline=INK, width=int(STROKE))


def stroke(draw, points):
    """A round brush dragged along the curve: smooth at any width, where
    thick polyline joins in Pillow come out jagged."""
    h = STROKE / 2
    for x, y in points:
        draw.ellipse((x - h, y - h, x + h, y + h), fill=INK)


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(6 * UNIT), fill=TILE)
ring(draw, 7, 7, 3)
ring(draw, 7, 25, 3)
stroke(draw, cubic((10, 8.5), (15, 11), (16, 14), (19, 16), steps=600))
stroke(draw, cubic((10, 23.5), (15, 21), (16, 18), (19, 16), steps=600))
cx, cy = pt(23.5, 16)
r = 4.5 * UNIT
draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SIGNAL)
img = img.resize((1024, 1024), Image.LANCZOS)

out = Path(__file__).with_name("learning-os.ico")
img.save(out, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print(f"wrote {out}")
