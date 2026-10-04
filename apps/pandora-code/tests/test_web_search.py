"""Tests für Punkt 6: lokaler Doku-/Such-Scraper – WebSearch (SearXNG/DuckDuckGo) und WebFetch."""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from pandora_code.extensions.web_search import (
    WebSearchState, duckduckgo_search, fetch_url, html_to_text, searxng_reachable, searxng_search,
)
from pandora_code.tools import ToolError
from tests.test_extensions import ExtCase


class FakeWebServer:
    """Lokaler Fake-Server für HTML-Seiten, SearXNG-JSON und die DuckDuckGo-HTML-Ausgabe – alles über
    denselben einfachen Pfad-Router, damit ein Server für alle drei Szenarien in den Tests reicht."""

    def __init__(self, routes: dict[str, tuple[int, str, str]]) -> None:
        # routes: path -> (status, content_type, body)
        self.routes = routes
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                for prefix, (status, ctype, body) in outer.routes.items():
                    if self.path.startswith(prefix):
                        self.send_response(status)
                        self.send_header("Content-Type", ctype)
                        self.end_headers()
                        self.wfile.write(body.encode())
                        return
                self.send_response(404)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.url = f"http://{self.host}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags_and_scripts(self) -> None:
        html = "<html><head><style>.x{color:red}</style></head><body><h1>Titel</h1>" \
               "<p>Erster Absatz.</p><script>alert(1)</script><p>Zweiter Absatz.</p></body></html>"
        text = html_to_text(html)
        self.assertIn("Titel", text)
        self.assertIn("Erster Absatz.", text)
        self.assertIn("Zweiter Absatz.", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("color:red", text)

    def test_block_tags_create_line_breaks(self) -> None:
        html = "<div>Eins</div><div>Zwei</div>"
        text = html_to_text(html)
        self.assertIn("Eins", text.splitlines())
        self.assertIn("Zwei", text.splitlines())

    def test_empty_html_returns_empty_string(self) -> None:
        self.assertEqual(html_to_text("<html></html>"), "")

    def test_entities_are_decoded(self) -> None:
        text = html_to_text("<p>Tom &amp; Jerry</p>")
        self.assertIn("Tom & Jerry", text)


class FetchUrlTests(unittest.TestCase):
    def test_rejects_non_http_schemes(self) -> None:
        with self.assertRaises(ToolError):
            fetch_url("file:///etc/passwd")
        with self.assertRaises(ToolError):
            fetch_url("ftp://example.com/x")

    def test_fetches_real_local_server(self) -> None:
        server = FakeWebServer({"/docs": (200, "text/html", "<h1>API-Doku</h1><p>Details hier.</p>")})
        self.addCleanup(server.close)
        html = fetch_url(f"{server.url}/docs")
        self.assertIn("API-Doku", html)

    def test_http_error_is_reported_clearly(self) -> None:
        server = FakeWebServer({"/missing": (404, "text/plain", "nope")})
        self.addCleanup(server.close)
        with self.assertRaises(ToolError) as ctx:
            fetch_url(f"{server.url}/missing")
        self.assertIn("404", str(ctx.exception))

    def test_unreachable_host_is_reported_not_raised_as_generic_exception(self) -> None:
        with self.assertRaises(ToolError):
            fetch_url("http://127.0.0.1:1", timeout=1)


class SearxngTests(unittest.TestCase):
    def test_search_parses_json_results(self) -> None:
        payload = json.dumps({"results": [
            {"title": "Python docs", "url": "https://docs.python.org/3/", "content": "Official docs"},
            {"title": "No URL entry", "content": "wird ignoriert"},
        ]})
        server = FakeWebServer({"/search": (200, "application/json", payload)})
        self.addCleanup(server.close)
        results = searxng_search(server.url, "python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Python docs")
        self.assertIn("q=python", server.requests[0])
        self.assertIn("format=json", server.requests[0])

    def test_search_returns_none_when_json_format_disabled(self) -> None:
        # Typischer Fall: die Instanz gibt bei format=json eine Fehlerseite/HTML statt JSON zurück.
        server = FakeWebServer({"/search": (200, "text/html", "<html>kein JSON hier</html>")})
        self.addCleanup(server.close)
        self.assertIsNone(searxng_search(server.url, "python"))

    def test_search_returns_none_when_unreachable(self) -> None:
        self.assertIsNone(searxng_search("http://127.0.0.1:1", "x", timeout=1))

    def test_search_returns_none_on_non_list_results(self) -> None:
        server = FakeWebServer({"/search": (200, "application/json", json.dumps({"results": "kaputt"}))})
        self.addCleanup(server.close)
        self.assertIsNone(searxng_search(server.url, "x"))

    def test_reachable_true_via_healthz(self) -> None:
        server = FakeWebServer({"/healthz": (200, "text/plain", "OK")})
        self.addCleanup(server.close)
        self.assertTrue(searxng_reachable(server.url))

    def test_reachable_false_when_nothing_listens(self) -> None:
        self.assertFalse(searxng_reachable("http://127.0.0.1:1", timeout=1))

    def test_reachable_falls_back_to_root_without_healthz(self) -> None:
        server = FakeWebServer({"/": (200, "text/html", "<html>Startseite</html>")})
        self.addCleanup(server.close)
        self.assertTrue(searxng_reachable(server.url))


class DuckDuckGoTests(unittest.TestCase):
    def test_parses_typical_result_markup(self) -> None:
        body = (
            '<div class="result"><a class="result__a" href="https://example.com/">Example &amp; Co</a>'
            '<a class="result__snippet">Ein Beispiel-Snippet.</a></div>'
        )
        server = FakeWebServer({"/html/": (200, "text/html", body)})
        self.addCleanup(server.close)
        results = duckduckgo_search("beispiel", base_url=f"{server.url}/html/")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.com/")
        self.assertEqual(results[0]["title"], "Example & Co")
        self.assertIn("Beispiel-Snippet", results[0]["snippet"])

    def test_no_results_returns_empty_list(self) -> None:
        server = FakeWebServer({"/html/": (200, "text/html", "<html>keine Treffer</html>")})
        self.addCleanup(server.close)
        self.assertEqual(duckduckgo_search("x", base_url=f"{server.url}/html/"), [])


class WebSearchStateTests(unittest.TestCase):
    def test_explicit_url_used_when_reachable(self) -> None:
        server = FakeWebServer({"/healthz": (200, "text/plain", "OK")})
        self.addCleanup(server.close)
        state = WebSearchState(searxng_url=server.url)
        self.assertEqual(state.resolve_searxng(), server.url)

    def test_explicit_url_ignored_when_unreachable(self) -> None:
        state = WebSearchState(searxng_url="http://127.0.0.1:1")
        self.assertIsNone(state.resolve_searxng())

    def test_auto_detect_caches_within_ttl(self) -> None:
        state = WebSearchState(ttl=1000.0)
        with mock.patch("pandora_code.extensions.web_search.searxng_reachable", return_value=False) as check:
            state.resolve_searxng()
            state.resolve_searxng()
        self.assertEqual(check.call_count, len(__import__(
            "pandora_code.extensions.web_search", fromlist=["DEFAULT_SEARXNG_CANDIDATES"]
        ).DEFAULT_SEARXNG_CANDIDATES))  # zweiter Aufruf kam komplett aus dem Cache


class WebSearchToolTests(ExtCase):
    def test_search_prefers_reachable_searxng_over_duckduckgo(self) -> None:
        payload = json.dumps({"results": [{"title": "Lokal", "url": "http://intra/doc", "content": "..."}]})
        server = FakeWebServer({
            "/healthz": (200, "text/plain", "OK"),
            "/search": (200, "application/json", payload),
        })
        self.addCleanup(server.close)
        from pandora_code.config import Settings
        settings = Settings(searxng_url=server.url)
        agent, _ = self.make_agent([], settings=settings)
        result = agent.tools["WebSearch"].run(agent.ctx, {"query": "irgendwas"})
        self.assertIn("Lokal", result)
        self.assertIn("SearXNG", result)

    def test_search_falls_back_to_duckduckgo_without_searxng(self) -> None:
        ddg = FakeWebServer({"/html/": (200, "text/html",
            '<a class="result__a" href="https://x.example/">X Docs</a>'
            '<a class="result__snippet">Snippet</a>')})
        self.addCleanup(ddg.close)
        agent, _ = self.make_agent([])
        with mock.patch("pandora_code.extensions.web_search.DEFAULT_SEARXNG_CANDIDATES", ()), \
             mock.patch("pandora_code.extensions.web_search.DUCKDUCKGO_URL", f"{ddg.url}/html/"):
            result = agent.tools["WebSearch"].run(agent.ctx, {"query": "x docs"})
        self.assertIn("X Docs", result)
        self.assertIn("DuckDuckGo", result)

    def test_search_disabled_via_settings_raises(self) -> None:
        from pandora_code.config import Settings
        agent, _ = self.make_agent([], settings=Settings(web_search=False))
        with self.assertRaises(Exception):
            agent.tools["WebSearch"].run(agent.ctx, {"query": "x"})

    def test_search_requires_query(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(Exception):
            agent.tools["WebSearch"].run(agent.ctx, {})

    def test_fetch_tool_returns_readable_text(self) -> None:
        server = FakeWebServer({"/page": (200, "text/html", "<h1>Titel</h1><p>Inhalt der Seite.</p>")})
        self.addCleanup(server.close)
        agent, _ = self.make_agent([])
        result = agent.tools["WebFetch"].run(agent.ctx, {"url": f"{server.url}/page"})
        self.assertIn("Titel", result)
        self.assertIn("Inhalt der Seite.", result)

    def test_fetch_tool_requires_url(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(Exception):
            agent.tools["WebFetch"].run(agent.ctx, {})

    def test_fetch_render_without_playwright_falls_back_with_note(self) -> None:
        server = FakeWebServer({"/spa": (200, "text/html", "<p>Statischer Inhalt</p>")})
        self.addCleanup(server.close)
        agent, _ = self.make_agent([])
        with mock.patch("pandora_code.extensions.web_search.PLAYWRIGHT_AVAILABLE", False):
            result = agent.tools["WebFetch"].run(agent.ctx, {"url": f"{server.url}/spa", "render": True})
        self.assertIn("Statischer Inhalt", result)
        self.assertIn("Playwright nicht installiert", result)

    def test_fetch_render_with_playwright_available_uses_it(self) -> None:
        agent, _ = self.make_agent([])
        with mock.patch("pandora_code.extensions.web_search.PLAYWRIGHT_AVAILABLE", True), \
             mock.patch("pandora_code.extensions.web_search.render_with_playwright",
                        return_value="<p>Von Playwright gerendert</p>") as render:
            result = agent.tools["WebFetch"].run(agent.ctx, {"url": "https://spa.example/app", "render": True})
        render.assert_called_once()
        self.assertEqual(render.call_args.args[0], "https://spa.example/app")
        self.assertIn("Von Playwright gerendert", result)
        self.assertNotIn("Hinweis", result)

    def test_fetch_render_playwright_failure_is_reported_not_raised(self) -> None:
        agent, _ = self.make_agent([])
        with mock.patch("pandora_code.extensions.web_search.PLAYWRIGHT_AVAILABLE", True), \
             mock.patch("pandora_code.extensions.web_search.render_with_playwright",
                        side_effect=RuntimeError("Browser nicht gefunden")):
            result = agent.tools["WebFetch"].run(agent.ctx, {"url": "https://spa.example/app", "render": True})
        self.assertIn("Fehler", result)
        self.assertIn("Browser nicht gefunden", result)

    def test_web_js_render_setting_enables_rendering_by_default(self) -> None:
        from pandora_code.config import Settings
        agent, _ = self.make_agent([], settings=Settings(web_js_render=True))
        with mock.patch("pandora_code.extensions.web_search.PLAYWRIGHT_AVAILABLE", True), \
             mock.patch("pandora_code.extensions.web_search.render_with_playwright",
                        return_value="<p>gerendert</p>") as render:
            agent.tools["WebFetch"].run(agent.ctx, {"url": "https://spa.example/app"})  # kein render=True nötig
        render.assert_called_once()


class WebsearchCommandTests(ExtCase):
    def _out(self, agent, arg: str) -> list[str]:
        out: list[str] = []
        from pandora_code.ui import UI
        ui = UI()
        ui.info = out.append  # type: ignore[assignment]
        ui.error = out.append  # type: ignore[assignment]
        handler, _ = agent.commands["websearch"]
        handler(arg, agent, ui)
        return out

    def test_shows_status(self) -> None:
        agent, _ = self.make_agent([])
        out = self._out(agent, "")
        self.assertTrue(any("WebSearch: an" in line for line in out))

    def test_toggle_off(self) -> None:
        agent, _ = self.make_agent([])
        out = self._out(agent, "aus")
        self.assertTrue(any("WebSearch: aus" in line for line in out))
        with self.assertRaises(Exception):
            agent.tools["WebSearch"].run(agent.ctx, {"query": "x"})

    def test_invalid_argument_reports_usage(self) -> None:
        agent, _ = self.make_agent([])
        out = self._out(agent, "quatsch")
        self.assertTrue(any("Nutzung" in line for line in out))


if __name__ == "__main__":
    unittest.main()
