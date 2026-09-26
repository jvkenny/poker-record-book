#!/usr/bin/env python3
"""
Draw badge art for the trophies SettleStack has no image for (trophies.EXTRA).

    ../settle-stack/.venv/bin/python tools/gen_badges.py          # missing badges only
    ../settle-stack/.venv/bin/python tools/gen_badges.py --all    # redraw every one
    ../settle-stack/.venv/bin/python tools/gen_badges.py --sheet  # also write a contact sheet

Matches the SettleStack set: a gold rim with suit pips, a dark felt centre, and a
poker chip carrying a gold emblem. The chip colour comes from the trophy's tone.
Emblems are Google's Material Symbols (Apache 2.0); the font is not committed:
    curl -L -o tools/MaterialSymbolsRounded.ttf \\
      "https://github.com/google/material-design-icons/raw/master/variablefont/MaterialSymbolsRounded%5BFILL,GRAD,opsz,wght%5D.ttf"
    curl -L -o tools/MaterialSymbolsRounded.codepoints \\
      "https://github.com/google/material-design-icons/raw/master/variablefont/MaterialSymbolsRounded%5BFILL,GRAD,opsz,wght%5D.codepoints"
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import trophies  # noqa: E402
from build import slug  # noqa: E402

TOOLS = ROOT / "tools"
OUT = ROOT / "assets/badges"
S = 512           # drawn at 512, saved at 200 like the SettleStack thumbnails
C = S / 2

# chip face colours by tone: (face, rim) — the emblem stays gold on all of them
TONES = {
    "gold":   ("#0f5c38", "#0a3f27"),
    "money":  ("#17191a", "#050606"),
    "shame":  ("#8c1f26", "#5a1016"),
    "ice":    ("#1f5f8f", "#123b5a"),
    "fire":   ("#b0431b", "#6f240c"),
    "night":  ("#1c2757", "#0e1535"),
    "legend": ("#5b2d8f", "#361859"),
}
GOLD = [(0.0, (255, 243, 186)), (0.35, (240, 199, 92)), (0.6, (184, 130, 38)), (1.0, (110, 70, 16))]


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(stops, t):
    t = max(0.0, min(1.0, t))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            k = (t - a) / (b - a) if b > a else 0
            return tuple(round(x + (y - x) * k) for x, y in zip(ca, cb))
    return stops[-1][1]


def linear(size, stops, angle=135):
    """Gradient image across `size`, direction in degrees (135 = top-left light)."""
    w, h = size
    g = Image.new("RGB", (256, 1))
    for i in range(256):
        g.putpixel((i, 0), lerp(stops, i / 255))
    g = g.resize((int(math.hypot(w, h)) + 2, int(math.hypot(w, h)) + 2))
    g = g.rotate(-(angle - 90), resample=Image.BICUBIC, expand=False)
    x0, y0 = (g.width - w) // 2, (g.height - h) // 2
    return g.crop((x0, y0, x0 + w, y0 + h))


def radial(size, inner, outer, cx=0.5, cy=0.42):
    w, h = size
    y, x = np.mgrid[0:h, 0:w]
    d = np.minimum(1.0, np.hypot(x / w - cx, y / h - cy) / 0.62)[..., None]
    rgb = np.array(inner) + (np.array(outer) - np.array(inner)) * d
    return Image.fromarray(rgb.round().astype("uint8"), "RGB")


def disc(r, cx=C, cy=C):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m


def ring(r_out, r_in):
    return ImageChops.subtract(disc(r_out), disc(r_in))


FELT = radial((S, S), (36, 122, 78), (5, 38, 24))
SUITS = ImageFont.truetype("/System/Library/Fonts/Apple Symbols.ttf", 44)
ICONS = ImageFont.truetype(str(TOOLS / "MaterialSymbolsRounded.ttf"), 196)
ICONS.set_variation_by_axes([1, 0, 48, 600])     # filled, weight 600
CODE = {}
for line in (TOOLS / "MaterialSymbolsRounded.codepoints").read_text().splitlines():
    name, cp = line.split()
    CODE[name] = chr(int(cp, 16))


def paste(base, fill, mask):
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.paste(fill if isinstance(fill, Image.Image) else Image.new("RGB", (S, S), fill), (0, 0), mask)
    return Image.alpha_composite(base, layer)


def shadow(mask, offset=(0, 6), blur=8, alpha=160):
    sh = Image.new("L", (S, S), 0)
    sh.paste(mask, offset)
    sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: v * alpha // 255)
    return sh


def draw(icon: str, tone: str) -> Image.Image:
    face, rim = (hexrgb(c) for c in TONES[tone])
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # rim: gold ring with a dark lip either side and a highlight on the upper-left
    img = paste(img, (0, 0, 0), shadow(disc(248), (0, 8), 10, 150))
    img = paste(img, linear((S, S), GOLD), ring(250, 204))
    img = paste(img, (70, 44, 10), ring(250, 246))
    img = paste(img, (70, 44, 10), ring(208, 204))
    hl = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hl).arc([14, 14, S - 14, S - 14], 190, 280, fill=150, width=6)
    img = paste(img, (255, 250, 220), hl.filter(ImageFilter.GaussianBlur(3)))

    # suit pips engraved into the rim
    pips = Image.new("L", (S, S), 0)
    pd = ImageDraw.Draw(pips)
    for i, suit in enumerate("♠♥♣♦♠♥♣♦"):
        a = math.radians(i * 45 - 90)
        x, y = C + 227 * math.cos(a), C + 227 * math.sin(a)
        pd.text((x, y), suit, font=SUITS, anchor="mm", fill=255)
    img = paste(img, (255, 244, 200), ImageChops.offset(pips, 1, 1).point(lambda v: v * 0.5))
    img = paste(img, (46, 30, 6), pips)

    # felt, with a soft light from above; legendary badges get rays
    img = paste(img, FELT, disc(204))
    if tone == "legend":
        rays = Image.new("L", (S, S), 0)
        rd = ImageDraw.Draw(rays)
        for i in range(24):
            a = math.radians(i * 15)
            rd.polygon([(C, C), (C + 210 * math.cos(a - .05), C + 210 * math.sin(a - .05)),
                        (C + 210 * math.cos(a + .05), C + 210 * math.sin(a + .05))], fill=38)
        img = paste(img, (255, 225, 140), ImageChops.multiply(rays, disc(203)))
    img = paste(img, (0, 0, 0), ImageChops.multiply(ring(204, 186), Image.new("L", (S, S), 90)).filter(ImageFilter.GaussianBlur(6)))

    # the chip
    img = paste(img, (0, 0, 0), shadow(disc(138), (0, 10), 12, 170))
    img = paste(img, radial((S, S), tuple(min(255, c + 30) for c in face), rim, 0.5, 0.35), disc(138))
    spots = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(spots)
    for i in range(8):
        a0 = i * 45 - 9
        sd.pieslice([C - 138, C - 138, C + 138, C + 138], a0, a0 + 18, fill=255)
    spots = ImageChops.multiply(spots, ring(138, 112))
    img = paste(img, (244, 236, 214), spots)
    img = paste(img, linear((S, S), GOLD), ring(110, 104))
    img = paste(img, radial((S, S), face, rim, 0.5, 0.3), disc(104))

    # the emblem: gold, with an engraved shadow
    glyph = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glyph).text((C, C + 2), CODE[icon], font=ICONS, anchor="mm", fill=255)
    bbox = glyph.getbbox()
    if bbox:   # keep big glyphs inside the chip face
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        k = min(1.0, 168 / max(w, h))
        if k < 1:
            glyph = glyph.resize((round(S * k), round(S * k)), Image.LANCZOS)
            pad = Image.new("L", (S, S), 0)
            pad.paste(glyph, ((S - glyph.width) // 2, (S - glyph.height) // 2))
            glyph = pad
    img = paste(img, (0, 0, 0), shadow(glyph, (0, 6), 5, 190))
    img = paste(img, linear((S, S), GOLD, 100), glyph)
    edge = ImageChops.subtract(glyph, glyph.filter(ImageFilter.MinFilter(5)))
    img = paste(img, (255, 248, 210), ImageChops.multiply(ImageChops.offset(edge, -1, -1), Image.new("L", (S, S), 120)))

    # sparkle on the rarest
    if tone == "legend":
        sp = Image.new("L", (S, S), 0)
        d = ImageDraw.Draw(sp)
        for x, y, r in [(C + 150, C - 150, 16), (C - 165, C - 120, 10), (C + 175, C + 110, 8)]:
            d.polygon([(x, y - r), (x + r / 4, y - r / 4), (x + r, y), (x + r / 4, y + r / 4),
                       (x, y + r), (x - r / 4, y + r / 4), (x - r, y), (x - r / 4, y - r / 4)], fill=255)
        img = paste(img, (255, 250, 225), sp.filter(ImageFilter.GaussianBlur(0.6)))
    return img.resize((200, 200), Image.LANCZOS)


def main():
    redo = "--all" in sys.argv
    made = []
    for aid, name, _desc, _cat, icon, tone in trophies.EXTRA:
        path = OUT / f"{slug(name)}.png"
        if path.exists() and not redo:
            continue
        draw(icon, tone).save(path, optimize=True)
        made.append(path)
    print(f"drew {len(made)} badge(s)")
    if "--sheet" in sys.argv:
        items = trophies.EXTRA
        cols = 8
        sheet = Image.new("RGBA", (cols * 200, math.ceil(len(items) / cols) * 200), (13, 59, 42, 255))
        for i, (_, name, *_rest) in enumerate(items):
            b = Image.open(OUT / f"{slug(name)}.png")
            sheet.paste(b, ((i % cols) * 200, (i // cols) * 200), b)
        sheet.save(TOOLS / "sheet.png")


if __name__ == "__main__":
    main()
