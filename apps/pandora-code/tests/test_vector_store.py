"""Tests für Punkt 1b: lokales Vektor-RAG – Chunking, Embedding-Backends, Index-Persistenz, Werkzeuge."""
from __future__ import annotations

import json
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pandora_code.context.vector_store import (
    HashingEmbedder, OllamaEmbedder, VectorStore, _cosine, _python_chunks, chunk_file, pick_embed_model,
)
from pandora_code.ollama_client import OllamaClient, OllamaError
from tests.test_extensions import ExtCase


class FakeEmbedServer:
    """Eigener schlanker Fake-Server für /api/embed und /api/embeddings (kein Streaming, anders als
    FakeOllama in test_pandora_code.py, das auf Chat-NDJSON zugeschnitten ist)."""

    def __init__(self, mode: str = "embed", fail: bool = False) -> None:
        self.mode = mode  # "embed" (neue Route) oder "legacy" (nur /api/embeddings)
        self.fail = fail
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status: int, body: dict) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                outer.requests.append(payload)
                if outer.fail:
                    self._send(500, {"error": "embedding fehlgeschlagen"})
                    return
                if self.path == "/api/embed" and outer.mode == "embed":
                    vectors = [_toy_vector(t) for t in payload["input"]]
                    self._send(200, {"embeddings": vectors})
                elif self.path == "/api/embeddings":
                    self._send(200, {"embedding": _toy_vector(payload["prompt"])})
                elif self.path == "/api/embed" and outer.mode == "legacy":
                    self._send(404, {"error": "404 page not found"})
                else:
                    self._send(404, {"error": "unbekannter Pfad"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _toy_vector(text: str) -> list[float]:
    """Deterministischer Spielzeug-Vektor: Länge + Anzahl 'a' – reicht, um Ähnlichkeitsreihenfolgen zu testen."""
    return [float(len(text)), float(text.lower().count("a"))]


class OllamaClientEmbedTests(unittest.TestCase):
    def test_embed_uses_batched_route(self) -> None:
        server = FakeEmbedServer(mode="embed")
        self.addCleanup(server.close)
        client = OllamaClient(server.host)
        vectors = client.embed("nomic-embed-text", ["hallo", "welt"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(server.requests[0]["input"], ["hallo", "welt"])

    def test_embed_falls_back_to_legacy_route_on_404(self) -> None:
        server = FakeEmbedServer(mode="legacy")
        self.addCleanup(server.close)
        client = OllamaClient(server.host)
        vectors = client.embed("old-embed-model", ["a", "bb"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[0], _toy_vector("a"))

    def test_embed_propagates_real_errors(self) -> None:
        server = FakeEmbedServer(mode="embed", fail=True)
        self.addCleanup(server.close)
        client = OllamaClient(server.host)
        with self.assertRaises(OllamaError):
            client.embed("nomic-embed-text", ["x"])

    def test_embed_empty_list_short_circuits(self) -> None:
        server = FakeEmbedServer(mode="embed")
        self.addCleanup(server.close)
        self.assertEqual(OllamaClient(server.host).embed("m", []), [])
        self.assertEqual(server.requests, [])


class PickEmbedModelTests(unittest.TestCase):
    def test_detects_known_embedding_family(self) -> None:
        installed = ["qwen2.5-coder:14b", "nomic-embed-text:latest", "phi3:mini"]
        self.assertEqual(pick_embed_model(installed), "nomic-embed-text:latest")

    def test_returns_none_when_nothing_matches(self) -> None:
        installed = ["qwen2.5-coder:14b", "phi3:mini", "gemma2:2b"]
        self.assertIsNone(pick_embed_model(installed))

    def test_matches_akis_actual_models_to_none(self) -> None:
        # Genau Akis installierte Modelle enthalten kein Embedding-Modell -> Fallback muss greifen.
        aki_models = [
            "qwen2.5-coder:14b", "qwen2.5-coder:7b", "phi3:mini", "gemma2:2b",
            "llama3.2:3b", "llama3.2:1b", "qwen2.5:3b",
        ]
        self.assertIsNone(pick_embed_model(aki_models))


class HashingEmbedderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = HashingEmbedder(dims=64)

    def test_vectors_are_normalized(self) -> None:
        vec = self.embedder.embed(["def process_payment(amount): return amount * 2"])[0]
        norm = sum(v * v for v in vec) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_similar_text_scores_higher_than_unrelated_text(self) -> None:
        query = self.embedder.embed(["process payment amount"])[0]
        related = self.embedder.embed(["def process_payment(amount): charge the payment amount"])[0]
        unrelated = self.embedder.embed(["def render_html_template(context): return html"])[0]
        self.assertGreater(_cosine(query, related), _cosine(query, unrelated))

    def test_identical_text_scores_close_to_one(self) -> None:
        a = self.embedder.embed(["hallo welt"])[0]
        b = self.embedder.embed(["hallo welt"])[0]
        self.assertAlmostEqual(_cosine(a, b), 1.0, places=5)

    def test_empty_text_does_not_crash(self) -> None:
        vec = self.embedder.embed([""])[0]
        self.assertEqual(vec, [0.0] * 64)


class ChunkingTests(unittest.TestCase):
    def test_python_chunks_split_by_function_and_class(self) -> None:
        src = textwrap.dedent('''
            import os

            def helper_one():
                return 1

            class Thing:
                def method(self):
                    return 2

            def helper_two():
                return 3
        ''')
        chunks = _python_chunks(src)
        labels = {label for _, _, label in chunks}
        self.assertIn("helper_one", labels)
        self.assertIn("Thing", labels)
        self.assertIn("helper_two", labels)

    def test_python_chunks_fall_back_on_syntax_error(self) -> None:
        chunks = _python_chunks("def broken(:\n    pass\n" + "x = 1\n" * 50)
        self.assertTrue(chunks)  # Zeilenfenster-Fallback liefert trotzdem etwas Sinnvolles


class ChunkFileTests(ExtCase):
    def test_python_file_chunks_by_symbol(self) -> None:
        path = self.cwd / "mod.py"
        path.write_text("def a():\n    pass\n\n\ndef b():\n    pass\n", encoding="utf-8")
        chunks = chunk_file(path)
        self.assertEqual({label for _, _, label in chunks}, {"a", "b"})

    def test_js_file_chunks_by_line_window(self) -> None:
        path = self.cwd / "big.js"
        path.write_text("\n".join(f"line{i}();" for i in range(100)), encoding="utf-8")
        chunks = chunk_file(path)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("Zeilen" in label for _, _, label in chunks))


class VectorStoreBuildAndSearchTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "payments.py").write_text(textwrap.dedent('''
            def process_payment(amount):
                """Zieht den Betrag vom Konto des Kunden ein."""
                if amount <= 0:
                    raise ValueError("Betrag muss positiv sein")
                return charge_card(amount)

            def charge_card(amount):
                return {"charged": amount}
        '''), encoding="utf-8")
        (self.cwd / "rendering.py").write_text(textwrap.dedent('''
            def render_template(name, context):
                """Rendert eine HTML-Vorlage mit dem gegebenen Kontext."""
                return f"<html>{name}: {context}</html>"
        '''), encoding="utf-8")
        (self.cwd / "node_modules").mkdir()
        (self.cwd / "node_modules" / "ignored.py").write_text("def process_payment(): pass\n", encoding="utf-8")

    def test_build_creates_chunks_and_skips_excluded_dirs(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder())
        store.build()
        files = {c.file for c in store.chunks}
        self.assertIn("payments.py", files)
        self.assertIn("rendering.py", files)
        self.assertNotIn("node_modules/ignored.py", files)

    def test_search_ranks_semantically_closer_chunk_first(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder())
        store.build()
        # Hashing ist lexikalisch (Wortüberlappung, kein echtes Sprachverständnis) – die Anfrage nutzt daher
        # bewusst Wörter aus der payments.py-Docstring ("Betrag", "Konto", "Kunden"), nicht aus rendering.py.
        hits = store.search("Betrag vom Konto des Kunden abbuchen", top_k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0].file, "payments.py")

    def test_index_persists_and_reloads_without_rebuild(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder())
        store.build()
        chunk_count = len(store.chunks)
        self.assertTrue((self.cwd / ".pandora" / "vector_index.json").exists())

        reloaded = VectorStore(self.cwd, HashingEmbedder())
        self.assertTrue(reloaded.load())
        self.assertEqual(len(reloaded.chunks), chunk_count)

    def test_different_embedder_invalidates_persisted_index(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder(dims=64))
        store.build()
        other = VectorStore(self.cwd, HashingEmbedder(dims=32))  # anderer Name -> anderer Vektorraum
        self.assertFalse(other.load())

    def test_refresh_reembeds_only_changed_file(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder())
        store.build()
        (self.cwd / "rendering.py").write_text("def brand_new_render():\n    pass\n", encoding="utf-8")
        changed, total = store.refresh()
        self.assertEqual(changed, 1)
        names = {c.label for c in store.chunks}
        self.assertIn("brand_new_render", names)
        self.assertNotIn("render_template", names)

    def test_refresh_removes_chunks_for_deleted_file(self) -> None:
        store = VectorStore(self.cwd, HashingEmbedder())
        store.build()
        (self.cwd / "rendering.py").unlink()
        store.refresh()
        self.assertFalse(any(c.file == "rendering.py" for c in store.chunks))

    def test_ollama_embedder_end_to_end_via_fake_server(self) -> None:
        server = FakeEmbedServer(mode="embed")
        self.addCleanup(server.close)
        client = OllamaClient(server.host)
        store = VectorStore(self.cwd, OllamaEmbedder(client, "nomic-embed-text"))
        store.build()
        self.assertTrue(store.chunks)
        hits = store.search("irgendeine Anfrage")
        self.assertTrue(hits)


class VectorRagExtensionTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "lib.py").write_text(textwrap.dedent('''
            def calculate_total(items):
                """Summiert die Preise aller Positionen im Warenkorb."""
                return sum(item.price for item in items)
        '''), encoding="utf-8")

    def test_code_search_tool_uses_hashing_fallback_without_registry(self) -> None:
        agent, _ = self.make_agent([])  # kein registry im Test-Setup -> automatisch Hashing-Fallback
        result = agent.tools["CodeSearch"].run(agent.ctx, {"query": "Summe der Preise im Warenkorb berechnen"})
        self.assertIn("lib.py", result)
        self.assertIsInstance(agent.vector_store.embedder, HashingEmbedder)

    def test_rag_command_builds_and_reports_summary(self) -> None:
        agent, _ = self.make_agent([])
        out: list[str] = []
        from pandora_code.ui import UI
        ui = UI()
        ui.info = out.append  # type: ignore[assignment]
        handler, _ = agent.commands["rag"]
        handler("", agent, ui)
        self.assertTrue(any("Vektor-Index" in line for line in out))

    def test_code_search_requires_query(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(Exception):
            agent.tools["CodeSearch"].run(agent.ctx, {})


if __name__ == "__main__":
    unittest.main()
