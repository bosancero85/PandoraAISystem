"""Symbol für Tray und .exe, gezeichnet mit Pillow (keine Bilddateien nötig)."""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw


def make_icon(running: bool = False, size: int = 64) -> Image.Image:
    scale = 4  # zeichnen in hoher Auflösung, dann glätten
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = (34, 197, 94, 255) if running else (148, 163, 184, 255)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big // 5, fill=(24, 30, 40, 255))
    m = big // 6
    draw.ellipse((m, m, big - m, big - m), outline=accent, width=max(2, big // 16))
    c = big // 2
    r = big // 7
    if running:  # Play-Dreieck
        draw.polygon([(c - r // 2, c - r), (c - r // 2, c + r), (c + r, c)], fill=accent)
    else:  # Stopp-Quadrat
        draw.rectangle((c - r, c - r, c + r, c + r), fill=accent)
    return img.resize((size, size), Image.LANCZOS)


def write_ico(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    make_icon(True, 256).save(path, format="ICO",
                              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def write_png(path: str, size: int = 256) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    make_icon(True, size).save(path, format="PNG")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join("assets", "icon.ico")
    (write_png if target.lower().endswith(".png") else write_ico)(target)
    print("Symbol geschrieben:", target)
