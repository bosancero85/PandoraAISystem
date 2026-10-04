# Icon-Werkzeug fuer die Build-Skripte (benoetigt Pillow)
#
#   python make_icons.py png     ORDNER 16 32 64 ...   -> ORDNER/icon_<N>.png (quadratisch)
#   python make_icons.py iconset ORDNER                -> macOS-.iconset (fuer `iconutil -c icns`)
#   python make_icons.py icns    DATEI.icns            -> .icns direkt per Pillow (Fallback)
#   python make_icons.py ico     DATEI.ico             -> Windows-.ico
#
# Quelle ist ollama_model_installer_icon.png. Das Motiv wird auf den sichtbaren
# Bereich zugeschnitten und mittig auf eine quadratische, transparente
# Flaeche gesetzt (wie in build.bat).

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "ollama_model_installer_icon.png")

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# Namen und Pixelgroessen eines macOS-.iconset
ICONSET = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def square_icon(path=SOURCE):
    """Quelle laden, auf sichtbaren Inhalt zuschneiden, quadratisch auffuellen."""
    im = Image.open(path).convert("RGBA")
    box = im.getchannel("A").getbbox() or im.getbbox()
    im = im.crop(box)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas


def resized(base, size):
    return base.resize((size, size), Image.LANCZOS)


def write_pngs(folder, sizes):
    os.makedirs(folder, exist_ok=True)
    base = square_icon()
    for size in sizes:
        resized(base, size).save(os.path.join(folder, f"icon_{size}.png"), format="PNG")


def write_iconset(folder):
    os.makedirs(folder, exist_ok=True)
    base = square_icon()
    for name, size in ICONSET:
        resized(base, size).save(os.path.join(folder, name), format="PNG")


def write_icns(path):
    base = resized(square_icon(), 1024)
    base.save(path, format="ICNS")


def write_ico(path):
    square_icon().save(path, format="ICO", sizes=ICO_SIZES)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    mode, target = argv[1], argv[2]
    if not os.path.exists(SOURCE):
        print(f"[FEHLER] Quelle fehlt: {SOURCE}")
        return 1
    if mode == "png":
        sizes = [int(a) for a in argv[3:]] or [16, 32, 48, 64, 128, 256, 512]
        write_pngs(target, sizes)
    elif mode == "iconset":
        write_iconset(target)
    elif mode == "icns":
        write_icns(target)
    elif mode == "ico":
        write_ico(target)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
