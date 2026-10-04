"""Lokaler Doku- & Such-Scraper: Werkzeuge `WebSearch` und `WebFetch`.

Wenn Ollama eine Bibliothek/API nicht kennt (sein Trainingsstand ist zwangsläufig älter als "heute"), kann
der Agent damit aktuelle Dokumentation nachschlagen und einlesen, statt zu raten.

Zwei unabhängige Werkzeuge:
- **WebFetch**: lädt eine konkrete URL und wandelt das HTML in lesbaren Text um (reine Python-
  Standardbibliothek: `urllib` + `html.parser`, keine Zusatzinstallation nötig). Optional (`render: true`
  im Werkzeugaufruf, oder `"webJsRender": true` in `settings.json`) wird stattdessen Playwright genutzt,
  falls installiert (`pip install pandora-code[web]`) – für Seiten, die ohne JavaScript leer bleiben. Ohne
  Playwright fällt das einfach auf den ungerenderten HTML-Text zurück, mit klarem Hinweis, statt zu scheitern.
- **WebSearch**: sucht zuerst über eine **lokale SearXNG-Instanz** (Meta-Suchmaschine zum Selbsthosten,
  privat, ohne Tracking) – automatisch erkannt (`http://localhost:8080` u. ä.) oder über `"searxngUrl"` in
  `settings.json` konfiguriert. SearXNG muss dafür `formats: [html, json]` in seiner `settings.yml` erlauben
  (Suche -> `json` mit eintragen); das ist der einzige Grund, warum die JSON-API nicht immer sofort
  funktioniert. Ohne erreichbare SearXNG-Instanz weicht die Suche auf die DuckDuckGo-HTML-Ausgabe aus (kein
  API-Key nötig, aber extern und mit einfacher, störanfälliger Regex-Extraktion – wer das vermeiden will,
  richtet sich eine eigene SearXNG-Instanz ein). Welche Quelle tatsächlich genutzt wurde, steht immer mit im
  Ergebnis.

`/websearch [an|aus]` zeigt Status/erkanntes Backend oder schaltet die Suche komplett ab.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

from ..tools import Tool, ToolContext, ToolError, clip, schema

FETCH_TIMEOUT = 20
SEARCH_TIMEOUT = 10
MAX_FETCH_BYTES = 3_000_000
DETECT_TTL = 60.0  # Sekunden Cache für die SearXNG-Erkennung (keine Netzwerkprüfung bei jeder Anfrage)
DEFAULT_SEARXNG_CANDIDATES = ("http://localhost:8080", "http://127.0.0.1:8080")
USER_AGENT = "Mozilla/5.0 (compatible; PandoraCode/1.0; local coding agent)"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"

try:
    from playwright.sync_api import sync_playwright  # type: ignore
    PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - optionale Abhängigkeit
    PLAYWRIGHT_AVAILABLE = False


# -- HTML -> Text (Standardbibliothek, kein BeautifulSoup nötig) -------------------------------------------
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_BLOCK_TAGS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS and self.chunks and self.chunks[-1] != "\n":
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.chunks.append(data.strip())


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    text = " ".join(extractor.chunks).replace(" \n ", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# -- HTTP-Grundfunktionen -----------------------------------------------------------------------------
def _http_get(url: str, timeout: float, accept: str = "text/html,*/*") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - Schema wird geprüft
        raw = response.read(MAX_FETCH_BYTES + 1)
        charset = response.headers.get_content_charset() or "utf-8"
    if len(raw) > MAX_FETCH_BYTES:
        raw = raw[:MAX_FETCH_BYTES]
    return raw.decode(charset, errors="replace")


def fetch_url(url: str, timeout: float = FETCH_TIMEOUT) -> str:
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in ("http", "https"):
        raise ToolError(f"Nur http:// und https:// werden unterstützt (nicht '{scheme or url}').")
    try:
        return _http_get(url, timeout)
    except urllib.error.HTTPError as err:
        raise ToolError(f"HTTP-Fehler {err.code} beim Abruf von {url}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ToolError(f"Konnte {url} nicht laden: {err}") from None


def render_with_playwright(url: str, timeout: float) -> str:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            return page.content()
        finally:
            browser.close()


# -- Suche: SearXNG (bevorzugt, lokal) ------------------------------------------------------------------
def searxng_search(base_url: str, query: str, timeout: float = SEARCH_TIMEOUT) -> list[dict] | None:
    """None = diese Instanz liefert kein JSON (z. B. 'json' Format nicht in settings.yml erlaubt) oder ist
    nicht erreichbar -> Aufrufer soll auf DuckDuckGo ausweichen."""
    url = f"{base_url.rstrip('/')}/search?q={urllib.parse.quote(query)}&format=json"
    try:
        body = _http_get(url, timeout, accept="application/json")
        data = json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return None
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in results if isinstance(r, dict) and r.get("url")
    ]


def searxng_reachable(base_url: str, timeout: float = 2.0) -> bool:
    try:
        _http_get(f"{base_url.rstrip('/')}/healthz", timeout, accept="text/plain")
        return True
    except Exception:
        try:  # manche Instanzen haben keinen /healthz-Endpunkt -> Startseite reicht als Erreichbarkeitstest
            _http_get(base_url, timeout)
            return True
        except Exception:
            return False


# -- Suche: DuckDuckGo-HTML (Fallback, extern, kein API-Key) ----------------------------------------------
_DDG_RESULT = re.compile(
    r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>', re.S,
)
_TAG = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG.sub("", text).replace("&amp;", "&").replace("&#x27;", "'").strip()


def duckduckgo_search(query: str, timeout: float = SEARCH_TIMEOUT, base_url: str | None = None) -> list[dict]:
    """Einfache, bewusst simple Regex-Extraktion der stabilen html.duckduckgo.com-Ausgabe (kein API-Key,
    aber extern und störanfälliger als eine echte JSON-API – kann brechen, wenn DuckDuckGo das Markup
    ändert). `base_url` ist injizierbar (Standard: das Modul-Level DUCKDUCKGO_URL, dynamisch zur
    Aufrufzeit gelesen statt als Default-Argument gebunden, damit Tests es per mock.patch ersetzen können),
    damit Tests gegen einen lokalen Fake-Server laufen können, statt echte externe Anfragen zu senden."""
    url = f"{base_url or DUCKDUCKGO_URL}?q={urllib.parse.quote(query)}"
    body = _http_get(url, timeout)
    return [
        {"title": _strip_tags(title), "url": href, "snippet": _strip_tags(snippet)}
        for href, title, snippet in _DDG_RESULT.findall(body)
    ]


@dataclass
class WebSearchState:
    enabled: bool = True
    searxng_url: str | None = None  # explizit konfiguriert (settings.json "searxngUrl")
    js_render: bool = False
    ttl: float = DETECT_TTL
    _detected: str | None = None
    _checked_at: float = 0.0

    def resolve_searxng(self) -> str | None:
        if self.searxng_url:
            return self.searxng_url if searxng_reachable(self.searxng_url) else None
        now = time.monotonic()
        if self._detected is None or now - self._checked_at >= self.ttl:
            self._detected = next((c for c in DEFAULT_SEARXNG_CANDIDATES if searxng_reachable(c)), "")
            self._checked_at = now
        return self._detected or None


def _format_results(results: list[dict], source: str, limit: int) -> str:
    if not results:
        return f"Keine Treffer ({source})."
    lines = [f"Quelle: {source}"]
    for r in results[:limit]:
        lines.append(f"- {r['title'] or r['url']}\n  {r['url']}" + (f"\n  {r['snippet']}" if r.get("snippet") else ""))
    return "\n".join(lines)


def install(agent, settings) -> None:
    state = WebSearchState(
        enabled=bool(getattr(settings, "web_search", True)),
        searxng_url=getattr(settings, "searxng_url", None),
        js_render=bool(getattr(settings, "web_js_render", False)),
    )

    def web_search(ctx: ToolContext, args: dict) -> str:
        if not state.enabled:
            raise ToolError("WebSearch ist deaktiviert (settings.json: \"webSearch\": false, oder /websearch an).")
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolError("'query' fehlt.")
        limit = max(1, min(int(args.get("top_k") or 5), 10))
        base = state.resolve_searxng()
        if base:
            results = searxng_search(base, query)
            if results is not None:
                return clip(_format_results(results, f"SearXNG ({base})", limit))
        try:
            results = duckduckgo_search(query)
        except ToolError as err:
            return f"Fehler: Suche fehlgeschlagen ({err})."
        return clip(_format_results(results, "DuckDuckGo (extern, kein lokales SearXNG gefunden)", limit))

    def web_fetch(ctx: ToolContext, args: dict) -> str:
        url = str(args.get("url") or "").strip()
        if not url:
            raise ToolError("'url' fehlt.")
        want_render = bool(args.get("render")) or state.js_render
        note = ""
        if want_render:
            if PLAYWRIGHT_AVAILABLE:
                try:
                    html = render_with_playwright(url, FETCH_TIMEOUT)
                except Exception as err:
                    return f"Fehler: Playwright konnte {url} nicht rendern ({err})."
            else:
                html = fetch_url(url)
                note = "\n[Hinweis: Playwright nicht installiert, ungerendertes HTML genutzt – pip install pandora-code[web]]"
        else:
            html = fetch_url(url)
        text = html_to_text(html) or "(keine Textinhalte gefunden)"
        return clip(text) + note

    agent.add_tool(_make_tool(
        "WebSearch",
        "Search the web (prefers a local SearXNG instance if reachable/configured; otherwise falls back to "
        "DuckDuckGo). Use this to find current documentation, library versions, or APIs that may postdate "
        "the model's training data. 'top_k' caps results (default 5, max 10).",
        {"query": {"type": "string", "description": "Search query"},
         "top_k": {"type": "integer", "description": "Max results (default 5, max 10)"}},
        ("query",), web_search,
    ))
    agent.add_tool(_make_tool(
        "WebFetch",
        "Fetch a URL (http/https only) and return its readable text content (HTML stripped). Use this to "
        "read documentation pages found via WebSearch or given by the user. Set 'render': true for "
        "JavaScript-heavy pages that are empty without it (needs Playwright, pip install pandora-code[web]; "
        "falls back to the unrendered page with a note otherwise).",
        {"url": {"type": "string", "description": "Full http(s) URL"},
         "render": {"type": "boolean", "description": "Render with a real browser (Playwright) if available"}},
        ("url",), web_fetch,
    ))

    def websearch_command(arg: str, agent, ui) -> str | None:
        choice = arg.strip().lower()
        if choice in ("an", "on"):
            state.enabled = True
        elif choice in ("aus", "off"):
            state.enabled = False
        elif choice:
            ui.error("Nutzung: /websearch [an|aus]")
            return None
        base = state.resolve_searxng()
        lines = [
            f"WebSearch: {'an' if state.enabled else 'aus'}",
            f"  SearXNG: {base or ('konfiguriert (' + state.searxng_url + '), aber nicht erreichbar' if state.searxng_url else 'keine lokale Instanz gefunden -> DuckDuckGo-Fallback')}",
            f"  JS-Rendering (Playwright): {'installiert' if PLAYWRIGHT_AVAILABLE else 'nicht installiert'}"
            + (", standardmäßig an" if state.js_render else ""),
        ]
        ui.info("\n".join(lines))
        return None

    agent.register_command(
        "websearch", websearch_command,
        "/websearch [an|aus]  Websuche (SearXNG/DuckDuckGo) anzeigen oder komplett abschalten",
    )


def _make_tool(name: str, description: str, properties: dict, required: tuple, run):
    return Tool(name, description, schema(properties, required), run)
