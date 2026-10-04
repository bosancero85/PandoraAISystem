#!/usr/bin/env python3
"""Baut die Landingpage `index.html` als einzelne Datei.

Zutaten:
  scripts/landing_template.html          Seite mit Platzhaltern ({{...}})
  docs/                                  Banner, Favicon, Screenshots
  apps/ollama-browser-chat/              die echte Chat-App (HTML, CSS, JS)
  scripts/simulator_shim.js              ersetzt Ollama durch vorgefertigte Antworten

Der Chat wird als `srcdoc` in einen iframe eingebettet. Dafür werden CSS und JS in die HTML-Datei
gezogen. Bilder werden als WebP-Daten-URI eingebettet, damit die Seite ohne weitere Dateien läuft
(auch aus einer E-Mail, vom USB-Stick oder über GitHub Pages).

Aufruf:  python scripts/build_landing.py [--repo besitzer/name] [--out index.html]
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "bosancero85/PandoraAISystem"

# Platzhalter {{IMG:name}} -> Datei und Zielbreite (Pixel)
IMAGES = {
    "chat_desktop": ("docs/screenshots/chat-desktop.png", 1100),
    "chat_handy": ("docs/screenshots/chat-handy.png", 560),
    "chat_kontext": ("docs/screenshots/chat-kontextwarnung.png", 560),
    "chat_settings": ("docs/screenshots/chat-einstellungen.png", 512),
    "mini": ("docs/screenshots/mini-webserver.png", 662),
    "installer": ("docs/screenshots/models-installer.png", 1100),
    "code_term": ("docs/screenshots/pandora-code-terminal.png", 643),
    "code_tui": ("docs/screenshots/pandora-code-tui.png", 1100),
    "code_tui_keys": ("docs/screenshots/pandora-code-tui-tasten.png", 1100),
}
BANNER = ("docs/banner.jpg", 1200)
FAVICON = ("docs/favicon.png", 64)

# Die Demo darf die Einstellungen einer echten Chat-App auf derselben Herkunft nicht überschreiben.
REAL_STORAGE_KEY = "ollamaMobile.v1"
DEMO_STORAGE_KEY = "pandoraDemo.v1"

# Zusätzliches CSS nur für die Demo: Mikrofon und Anhänge gibt es dort nicht.
DEMO_CSS = "#btnMic,#btnAttach{display:none!important}"


class BuildError(Exception):
    pass


def data_uri(rel: str, width: int, fmt: str = "WEBP", quality: int = 84) -> str:
    """Bild verkleinern und als Daten-URI zurückgeben."""
    from PIL import Image

    path = ROOT / rel
    if not path.is_file():
        raise BuildError("Bild fehlt: %s" % rel)
    im = Image.open(path)
    im = im.convert("RGBA" if rel.endswith(".png") and fmt == "PNG" else "RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "PNG":
        im.save(buf, "PNG", optimize=True)
        mime = "image/png"
    else:
        im.save(buf, "WEBP", quality=quality, method=6)
        mime = "image/webp"
    return "data:%s;base64,%s" % (mime, base64.b64encode(buf.getvalue()).decode("ascii"))


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise BuildError("Datei fehlt: %s" % rel)
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, what: str) -> str:
    """Genau eine Ersetzung. Ändert sich die Chat-App, fällt der Build laut auf statt still falsch zu bauen."""
    if text.count(old) != 1:
        raise BuildError("%s: Muster %d-mal gefunden (erwartet: 1): %r" % (what, text.count(old), old[:70]))
    return text.replace(old, new, 1)


def build_sim_document() -> str:
    """Die Chat-App als eine HTML-Datei mit eingebautem Simulator."""
    page = read("apps/ollama-browser-chat/ollama.html")
    css = read("apps/ollama-browser-chat/style.css")
    js = read("apps/ollama-browser-chat/script.js")
    shim = read("scripts/simulator_shim.js")

    # Verweise auf Dateien entfernen, die in der eingebetteten Seite nicht existieren
    page = re.sub(r'\s*<link rel="manifest"[^>]*>', "", page)
    page = re.sub(r'\s*<link rel="apple-touch-icon"[^>]*>', "", page)
    page = re.sub(r'\s*<link rel="icon"[^>]*>', "", page)
    page = replace_once(page, '<link rel="stylesheet" href="style.css">',
                        "<style>\n%s\n%s\n</style>" % (css, DEMO_CSS), "style.css einbetten")

    # Service Worker gibt es in der Demo nicht
    js = replace_once(js, "if('serviceWorker' in navigator && window.isSecureContext){", "if(false){", "Service Worker aus")

    # Eigener Speicherschlüssel für die Demo (in Chat und Simulator)
    if REAL_STORAGE_KEY not in js or REAL_STORAGE_KEY not in shim:
        raise BuildError("Speicherschlüssel %r nicht gefunden" % REAL_STORAGE_KEY)
    js = js.replace(REAL_STORAGE_KEY, DEMO_STORAGE_KEY)
    shim = shim.replace(REAL_STORAGE_KEY, DEMO_STORAGE_KEY)

    if "</script>" in js or "</script>" in shim:
        # Würde den eingebetteten Skriptblock beenden. Aktuell nicht der Fall, der Build soll es aber merken.
        js = js.replace("</script>", "<\\/script>")
        shim = shim.replace("</script>", "<\\/script>")
    page = replace_once(page, '<script src="script.js"></script>',
                        "<script>\n%s\n</script>\n<script>\n%s\n</script>" % (shim, js), "script.js einbetten")
    return page


def build(repo: str) -> str:
    template = read("scripts/landing_template.html")
    sim = build_sim_document()

    values = {"REPO": repo, "BANNER": data_uri(*BANNER, fmt="WEBP", quality=82), "FAVICON": data_uri(*FAVICON, fmt="PNG"),
              "SIM_SRCDOC": html.escape(sim, quote=True)}
    for key, (rel, width) in IMAGES.items():
        values["IMG:" + key] = data_uri(rel, width)

    def fill(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in values:
            raise BuildError("Unbekannter Platzhalter: {{%s}}" % name)
        return values[name]

    out = re.sub(r"\{\{([A-Z_]+(?::[a-z_]+)?)\}\}", fill, template)
    left = re.findall(r"\{\{[^}]*\}\}", out)
    if left:
        raise BuildError("Platzhalter übrig: %s" % ", ".join(sorted(set(left))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=DEFAULT_REPO, help="GitHub-Repo als besitzer/name (Standard: %(default)s)")
    ap.add_argument("--out", default=str(ROOT / "index.html"), help="Zieldatei (Standard: index.html im Repo-Hauptordner)")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        print("[FEHLER] --repo muss die Form besitzer/name haben", file=sys.stderr)
        return 2
    try:
        page = build(args.repo)
    except BuildError as exc:
        print("[FEHLER] %s" % exc, file=sys.stderr)
        return 1
    out = Path(args.out)
    out.write_text(page, encoding="utf-8", newline="\n")
    print("[OK] %s geschrieben (%.0f KB)" % (out, out.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
