#!/usr/bin/env python3
"""Browser-Test der Landingpage (braucht: pip install playwright && playwright install chromium).

Prüft im echten Chromium: Simulator antwortet, Beispiel-Knöpfe, Kontextwarnung, Ansichtswechsel,
OS-Erkennung und Download-Links, Lightbox, keine Skriptfehler, kein seitliches Überlaufen am Handy.
Aufruf:  python scripts/browser_check.py [--shots ordner]
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
BASE = "https://github.com/bosancero85/PandoraAISystem/releases/latest/download/"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print("  %s  %s%s" % ("ok  " if ok else "FAIL", name, (" -> " + str(detail)) if detail and not ok else ""))


async def wait_idle(frame, timeout=20000):
    await frame.wait_for_function("!document.getElementById('send').classList.contains('stop')", timeout=timeout)


async def run(shots):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        errors = []

        async def new_page(width=1280, height=900, ua=None, **kw):
            ctx = await browser.new_context(viewport={"width": width, "height": height}, user_agent=ua, **kw)
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            return ctx, page

        # ---------- Desktop (Windows) ----------
        win_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
        ctx, page = await new_page(ua=win_ua)
        await page.goto(URL); await page.wait_for_timeout(600)
        check("Windows erkannt", "Windows erkannt" in await page.inner_text("#heroNote"))
        check("Download-Link Windows (Installer)", await page.get_attribute('.dl[data-tool="installer"] [data-role="btn"]', "href") == BASE + "Ollama-Installer-Win.exe")
        for os_name, expect in (("macos", "MiniWebserver-Mac.dmg"), ("linux", "MiniWebserver-Linux.AppImage"), ("windows", "MiniWebserver-Win.exe")):
            await page.click('.os-switch button[data-os="%s"]' % os_name)
            href = await page.get_attribute('.dl[data-tool="webserver"] [data-role="btn"]', "href")
            check("Umschalter %s -> %s" % (os_name, expect), href == BASE + expect, href)
        await page.click('.os-switch button[data-os="linux"]')
        check("Linux zeigt .deb-Hinweis", ".deb" in await page.inner_text('.dl[data-tool="code"] [data-role="alt"]'))
        check("Chat-Paket für alle Systeme gleich", await page.get_attribute('.dl[data-tool="chat"] [data-role="btn"]', "href") == BASE + "Ollama-Browser-Chat-Web.zip")

        handle = await page.wait_for_selector("#simFrame")
        frame = await handle.content_frame()
        await frame.wait_for_selector("#send"); await page.wait_for_timeout(500)
        check("Simulator: Modell geladen", "qwen2.5-coder" in await frame.inner_text("#model, .model-wrap"))
        check("Simulator: Mikrofon und Anhang ausgeblendet", await frame.evaluate("getComputedStyle(document.getElementById('btnMic')).display") == "none")

        await page.click('.chip[data-say="Schreibe mir eine Python-Funktion"]')
        await page.wait_for_timeout(700); await wait_idle(frame)
        body = await frame.inner_text("#messages, main, body")
        check("Beispiel-Knopf: Python-Antwort mit Code", "dateien_nach_groesse" in body)
        digits = await frame.evaluate("['tokIn','tokOut','tokSum'].map(id => [...document.getElementById(id).querySelectorAll('svg')].reduce((n, s) => n + s.querySelectorAll('.on').length, 0))")
        check("Token-Anzeige zählt (IN, OUT, Σ > 0)", all(d > 0 for d in digits), digits)

        await page.click('.chip.warn'); await page.wait_for_timeout(700); await wait_idle(frame); await page.wait_for_timeout(600)
        cls = await frame.evaluate("document.getElementById('tokIn').parentNode.className")
        check("Kontextwarnung: IN rot", "full" in cls, cls)

        await page.click("#viewDesk"); await page.wait_for_timeout(500)
        w = await page.evaluate("document.getElementById('frame').getBoundingClientRect().width")
        check("Desktop-Ansicht verbreitert den Rahmen", w > 600, w)
        await page.click("#viewPhone")
        if shots:
            await page.locator("#sim").scroll_into_view_if_needed()
            await page.screenshot(path=str(Path(shots) / "landing-simulator.png"))

        # Antwort abbrechen: neue Nachricht während einer laufenden Antwort
        await page.click('.chip[data-say="Hallo"]'); await page.wait_for_timeout(450)
        await page.click('.chip[data-say="Zeig mir eine HTML-Seite"]')
        await page.wait_for_timeout(700); await wait_idle(frame)
        check("Zweite Nachricht während Antwort: App bleibt bedienbar", "<!DOCTYPE html>" in await frame.inner_text("#messages, main, body") or "Hallo Pandora" in await frame.inner_text("#messages, main, body"))

        await page.evaluate("window.scrollTo(0, 0)")
        await page.click(".tool .shot")
        await page.wait_for_timeout(300)
        check("Lightbox öffnet", await page.evaluate("document.getElementById('lb').open"))
        await page.keyboard.press("Escape")
        check("Lightbox schließt mit Escape", not await page.evaluate("document.getElementById('lb').open"))
        if shots:
            await page.evaluate("document.documentElement.style.scrollBehavior='auto'; window.scrollTo(0, 0)")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(Path(shots) / "landing-top.png"))
            await page.screenshot(path=str(Path(shots) / "landing-full.png"), full_page=True)
        await ctx.close()

        # ---------- macOS, Linux ----------
        for label, ua, expect in (("macOS", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17 Safari/605.1.15", "MiniWebserver-Mac.dmg"),
                                  ("Linux", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36", "MiniWebserver-Linux.AppImage")):
            ctx, page = await new_page(ua=ua)
            await page.goto(URL); await page.wait_for_timeout(400)
            href = await page.get_attribute('.dl[data-tool="webserver"] [data-role="btn"]', "href")
            check("%s erkannt, Link %s" % (label, expect), href == BASE + expect, href)
            await ctx.close()

        # ---------- Handy ----------
        ctx, page = await new_page(width=390, height=844, device_scale_factor=2, is_mobile=True, has_touch=True,
                                   ua="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36")
        await page.goto(URL); await page.wait_for_timeout(500)
        check("Handy erkannt: Hinweis zum Simulator", "Handy" in await page.inner_text("#heroNote"))
        over = await page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        check("Handy: kein seitliches Überlaufen", not over)
        if shots:
            await page.screenshot(path=str(Path(shots) / "landing-handy.png"))
        await ctx.close()

        check("Keine Skriptfehler in der Konsole", not errors, errors[:3])
        await browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="Ordner für Screenshots")
    args = ap.parse_args()
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(run(args.shots))
    except ImportError:
        print("Playwright fehlt: pip install playwright && playwright install chromium")
        return 2
    bad = [c for c in CHECKS if not c[1]]
    print("\n%d von %d Prüfungen bestanden." % (len(CHECKS) - len(bad), len(CHECKS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
