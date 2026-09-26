"""Draw assets/og.png, the link-preview card Discord shows, from data.json."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1200, 630


def font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main():
    s = json.loads((HERE / "data.json").read_text())["summary"]
    img = Image.new("RGB", (W, H), "#062418")
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    for i in range(60, 0, -1):
        r = i / 60
        gd.ellipse([W / 2 - r * 900, -r * 500, W / 2 + r * 900, r * 700], fill=int(255 * (1 - r)))
    img = Image.composite(Image.new("RGB", (W, H), "#17583f"), img, glow.filter(ImageFilter.GaussianBlur(40)))

    logo = Image.open(HERE / "assets/logo.png").convert("RGBA")
    lw = 560
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (W // 2 - lw // 2, 60), logo)
    img = Image.alpha_composite(img.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18)))
    img.paste(logo, (W // 2 - lw // 2, 30), logo)

    dr = ImageDraw.Draw(img)
    serif = font(["/System/Library/Fonts/Supplemental/Didot.ttc", "/System/Library/Fonts/Times.ttc"], 78)
    mono = font(["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"], 26)
    for text, f, y, fill in [
        ("The Record Book", serif, 400, "#f4efe3"),
        (f"{s['nights']} NIGHTS  ·  {s['games']} GAMES  ·  {s['players']} PLAYERS  ·  ${s['money']:,.0f} IN PLAY",
         mono, 515, "#e8c46a"),
    ]:
        dr.text(((W - dr.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)
    img.convert("RGB").save(HERE / "assets/og.png", optimize=True)


if __name__ == "__main__":
    main()
