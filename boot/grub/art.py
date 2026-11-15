#!/usr/bin/env python3
#
# Text of the live boot menu, drawn in Inter as pictures. Under Secure
# Boot the signed GRUB refuses every font that is not built into it, so
# a theme can only show Inter through PNGs (pictures still load).
#
#   themes/raye/title.png      "Raye Linux"
#   themes/raye/release.png    the line under it, from ../../VERSION
#   themes/raye/hint.png       how to use the menu
#   themes/raye/icons/*.png    one picture per menu entry, named after
#                              its --class in grub.cfg
#   themes/raye/timer_c.png    the countdown bar, empty and filled: GRUB
#   themes/raye/timer_fill_c.png  draws a progress bar at least one text
#                              line high, so the thin bar is a stripe in
#                              the middle of a taller picture
#
#   python3 boot/grub/art.py
#
# The output is committed, so the image build doesn't need Pillow. Run
# it again when VERSION or a label changes (tests/test_boot_menu.sh
# notices a stale release.png).

import os

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "themes", "raye")
VERSION = os.path.join(HERE, "..", "..", "VERSION")
INTER = "/usr/share/fonts/opentype/inter"

TEXT = (243, 234, 255)
SECONDARY = (185, 168, 214)
QUIET = (141, 126, 176)
ACCENT = (123, 60, 255)

# must match icon_width and item_height in theme.txt; the height is also
# that of the select_*.png highlight, which GRUB stretches badly. GRUB
# puts the icon 22 px into the highlight (select_w.png), INSET adds to that
ROW_W, ROW_H, INSET = 340, 44, 4
LINE_W = 480
TIMER_H = 28       # the height GRUB gives the progress bar
ENTRIES = {
    "raye-install": "Install Raye Linux",
    "raye-french": "Installer Raye Linux",
    "raye-safe": "Safe graphics",
    "raye-firmware": "UEFI firmware settings",
}
SCALE = 4


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(INTER, f"Inter-{weight}.otf"), size * SCALE)


def paint(mask: Image.Image, colour: tuple) -> Image.Image:
    """Colour through a coverage mask, shrunk back from SCALE."""
    w, h = mask.size
    mask = mask.resize((w // SCALE, h // SCALE), Image.LANCZOS)
    img = Image.new("RGBA", mask.size, colour + (0,))
    img.putalpha(mask)
    return img


def line(text: str, weight: str, size: int, colour: tuple) -> Image.Image:
    """One line centred on a LINE_W wide strip, so theme.txt can centre
    it at 50%-LINE_W/2 whatever the text."""
    f = font(weight, size)
    top, bottom = f.getbbox("Ay↑")[1::2]
    pad = 2 * SCALE
    h = bottom - top + 2 * pad
    mask = Image.new("L", (LINE_W * SCALE, h + (-h) % SCALE), 0)
    ImageDraw.Draw(mask).text((LINE_W * SCALE // 2, pad - top), text,
                              font=f, fill=255, anchor="ma")
    return paint(mask, colour)


def row(text: str) -> Image.Image:
    """A menu entry: the full row, text on the line's middle."""
    f = font("Regular", 20)
    mask = Image.new("L", (ROW_W * SCALE, ROW_H * SCALE), 0)
    ImageDraw.Draw(mask).text((INSET * SCALE, ROW_H * SCALE // 2), text,
                              font=f, fill=255, anchor="lm")
    return paint(mask, TEXT)


def stripe(colour: tuple, alpha: int) -> Image.Image:
    img = Image.new("RGBA", (2, TIMER_H), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((0, TIMER_H // 2 - 2, 1, TIMER_H // 2 + 1), fill=colour + (alpha,))
    return img


def main() -> None:
    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)
    release = open(VERSION, encoding="utf-8").read().strip()

    line("Raye Linux", "SemiBold", 30, TEXT).save(os.path.join(OUT, "title.png"), optimize=True)
    info = PngImagePlugin.PngInfo()
    info.add_text("Raye-Release", release)
    line(release, "Regular", 17, SECONDARY).save(
        os.path.join(OUT, "release.png"), optimize=True, pnginfo=info)
    line("Choose with ↑ and ↓, then press Enter", "Regular", 15, QUIET).save(
        os.path.join(OUT, "hint.png"), optimize=True)
    stripe(TEXT, 36).save(os.path.join(OUT, "timer_c.png"))
    stripe(ACCENT, 255).save(os.path.join(OUT, "timer_fill_c.png"))
    for name, text in ENTRIES.items():
        row(text).save(os.path.join(OUT, "icons", name + ".png"), optimize=True)


if __name__ == "__main__":
    main()
