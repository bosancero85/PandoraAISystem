"""Tests für scripts/build_landing.py und die gebaute index.html (ohne Browser, ohne Netz).

Den Browser-Test (Simulator, Download-Umschalter, Lightbox) macht scripts/browser_check.py.
Aufruf:  python -m unittest discover -s scripts -p "test_*.py"
"""
import html
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_landing as bl  # noqa: E402

ROOT = bl.ROOT
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "path", "circle", "rect", "polygon", "line"}


class Balance(HTMLParser):
    """Prüft, dass jedes geöffnete Element wieder geschlossen wird."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id":
                self.ids.append(v)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append("</%s> passt nicht zu %s" % (tag, self.stack[-1:] or "nichts"))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


class LandingBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = bl.build(bl.DEFAULT_REPO)
        cls.sim = html.unescape(re.search(r'srcdoc="([^"]*)"', cls.page, re.S).group(1))

    def test_no_placeholders_left(self):
        self.assertEqual(re.findall(r"\{\{[^}]*\}\}", self.page), [])

    def test_template_is_well_formed(self):
        for name, text in (("Landingpage", re.sub(r'srcdoc="[^"]*"', 'srcdoc=""', self.page)), ("Simulator-Seite", self.sim)):
            p = Balance()
            p.feed(text)
            self.assertEqual(p.errors, [], name)
            self.assertEqual(p.stack, [], "%s: nicht geschlossen: %s" % (name, p.stack))
            self.assertEqual(len(p.ids), len(set(p.ids)), "%s: doppelte IDs" % name)

    def test_one_file_no_external_resources(self):
        outer = re.sub(r'srcdoc="[^"]*"', 'srcdoc=""', self.page)
        # nichts wird von außen geladen: kein <script src>, kein <link href> außer dem eingebetteten Favicon, keine Remote-Bilder
        self.assertEqual(re.findall(r"<script[^>]+src=", outer), [])
        for href in re.findall(r"<link[^>]+href=\"([^\"]+)\"", outer):
            self.assertTrue(href.startswith("data:"), href)
        for src in re.findall(r"<img[^>]+src=\"([^\"]+)\"", outer):
            self.assertTrue(src.startswith("data:image/"), src[:60])
        self.assertNotRegex(self.sim, r"<script[^>]+src=")
        self.assertNotRegex(self.sim, r"<link[^>]+(manifest|stylesheet|apple-touch)")

    def test_simulator_contains_real_chat_and_shim(self):
        for needle in ("window.fetch = function", "pandora-demo-send", "id=\"tokbar\"", "function contextState", "id=\"btnMic\""):
            self.assertTrue(needle in self.sim, "im Simulator fehlt: %r" % needle)
        self.assertTrue(bl.DEMO_CSS in self.sim, "Demo-CSS fehlt")
        self.assertTrue("if(false){" in self.sim, "Service Worker muss in der Demo aus sein")

    def test_demo_uses_its_own_storage_key(self):
        self.assertTrue(bl.DEMO_STORAGE_KEY in self.sim, "Demo-Speicherschlüssel fehlt")
        self.assertFalse(bl.REAL_STORAGE_KEY in self.sim, "echter Speicherschlüssel in der Demo")

    def test_images_embedded_and_reasonably_small(self):
        self.assertGreaterEqual(self.page.count("data:image/webp;base64,"), 10)
        self.assertLess(len(self.page.encode("utf-8")), 1_500_000, "Landingpage ist zu groß geworden")

    def test_every_template_image_key_is_defined(self):
        tpl = (ROOT / "scripts" / "landing_template.html").read_text(encoding="utf-8")
        used = set(re.findall(r"\{\{IMG:([a-z_]+)\}\}", tpl))
        self.assertEqual(used - set(bl.IMAGES), set(), "Platzhalter ohne Bild")
        self.assertEqual(set(bl.IMAGES) - used, set(), "Bild ohne Platzhalter")
        for rel, _ in list(bl.IMAGES.values()) + [bl.BANNER, bl.FAVICON]:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_accessibility_basics(self):
        outer = re.sub(r'srcdoc="[^"]*"', 'srcdoc=""', self.page)
        self.assertTrue('<html lang="de">' in outer)
        self.assertTrue('class="skip"' in outer)
        self.assertTrue("prefers-reduced-motion" in outer)
        self.assertTrue('title="Live-Simulator' in outer)
        self.assertEqual(len(re.findall(r"<img(?![^>]*\balt=)[^>]*>", outer)), 0, "Bild ohne alt-Text")
        self.assertEqual(outer.count("<h1"), 1)

    def test_repo_links_use_given_repo(self):
        page = bl.build("beispiel/MeinRepo")
        outer = re.sub(r'srcdoc="[^"]*"', 'srcdoc=""', page)
        # Die Download-Adressen setzt die Seite im Browser zusammen: BASE = github.com/<REPO>/releases/latest/download/
        self.assertTrue("var REPO = 'beispiel/MeinRepo';" in outer, "REPO nicht ersetzt")
        self.assertTrue("'https://github.com/' + REPO + '/releases/latest/download/'" in outer, "Download-Basis fehlt")
        self.assertTrue("https://github.com/beispiel/MeinRepo/tree/main/apps/pandora-code" in outer, "Ordner-Link fehlt")
        self.assertFalse(bl.DEFAULT_REPO in outer, "Standard-Repo steht noch in der Seite")

    def test_no_personal_data(self):
        for bad in ("musli", "C:\\Users\\m", "/home/claude"):
            self.assertFalse(bad in self.page, "persönliche Daten in der Seite: %r" % bad)


class LandingCliTests(unittest.TestCase):
    def test_cli_writes_file_and_rejects_bad_repo(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "index.html"
            self.assertEqual(bl.main(["--out", str(out)]), 0)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))
            self.assertEqual(bl.main(["--repo", "kein repo", "--out", str(out)]), 2)

    def test_build_fails_loudly_when_chat_changes(self):
        with self.assertRaises(bl.BuildError):
            bl.replace_once("a b c", "x", "y", "Test")
        with self.assertRaises(bl.BuildError):
            bl.replace_once("x x", "x", "y", "Test")

    def test_committed_index_html_is_current(self):
        """index.html im Repo muss zum aktuellen Stand von Vorlage, Chat und Simulator passen."""
        committed = (ROOT / "index.html").read_text(encoding="utf-8")
        fresh = bl.build(bl.DEFAULT_REPO)
        strip = lambda s: re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "data:IMG", s)  # WebP-Bytes dürfen je Pillow-Version abweichen
        self.assertTrue(strip(committed) == strip(fresh), "index.html ist veraltet: python scripts/build_landing.py")


if __name__ == "__main__":
    unittest.main()
