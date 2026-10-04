"""Tests für Pandora® 🦙 Code – ohne echtes Ollama (Fake-Server im Ollama-Protokoll)."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from pandora_code import banner
from pandora_code.agent import Agent
from pandora_code.cli import is_installed, pick_model
from pandora_code.ollama_client import OllamaClient, OllamaError, normalize_host
from pandora_code.permissions import Permissions
from pandora_code.tools import ToolContext, ToolError, build_tools
from pandora_code.ui import UI


class FakeOllama:
    """Startet einen lokalen HTTP-Server, der vorbereitete Chat-Antworten streamt."""

    def __init__(self, script: list[list[dict]]) -> None:
        outer = self
        self.script = list(script)
        self.requests: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # Ausgabe unterdrücken
                pass

            def _send(self, status: int, body: dict) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.2:latest"}]})
                else:
                    self._send(404, {"error": "nicht gefunden"})

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append(json.loads(self.rfile.read(length)))
                if not outer.script:
                    self._send(400, {"error": "boom"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for chunk in outer.script.pop(0):
                    self.wfile.write((json.dumps(chunk) + "\n").encode())
                    self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def text_chunks(text: str, prompt: int = 0, out: int = 0) -> list[dict]:
    return [
        {"message": {"role": "assistant", "content": text}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": prompt, "eval_count": out},
    ]


def tool_chunks(name: str, arguments: dict, prompt: int = 0, out: int = 0) -> list[dict]:
    call = {"function": {"name": name, "arguments": arguments}}
    return [
        {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": prompt, "eval_count": out},
    ]


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = Path(self._tmp.name).resolve()
        self.ctx = ToolContext(self.cwd)
        self.tools = build_tools()

    def run_tool(self, name: str, **args) -> str:
        return self.tools[name].run(self.ctx, args)


class BannerTests(unittest.TestCase):
    def test_branding_function_runs_without_nameerror(self) -> None:
        with mock.patch.object(banner.os, "system") as system, mock.patch("builtins.print") as printed:
            banner.ASCII_BRANDING()
        system.assert_called_once()
        self.assertIn("██████╗", printed.call_args[0][0])

    def test_original_art_is_preserved(self) -> None:
        self.assertIn("██║     ██║  ██║██║ ╚████║██████╔╝╚██████╔╝██║  ██║██║  ██║", banner.BRAND)
        self.assertIn("░▀▀▀░▀▀▀░▀▀░░▀▀▀", banner.BRAND)

    def test_no_pinning_without_tty(self) -> None:
        pinned = banner.PinnedBanner("Status")
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            pinned.start()
        self.assertFalse(pinned.pinned)
        self.assertIn("Status", out.getvalue())
        self.assertNotIn("\x1b[", out.getvalue())


class ToolTests(TempDirCase):
    def test_write_read_edit_roundtrip(self) -> None:
        self.run_tool("Write", file_path="a.txt", content="eins\nzwei\ndrei\n")
        self.assertIn("     2\tzwei", self.run_tool("Read", file_path="a.txt"))
        self.run_tool("Edit", file_path="a.txt", old_string="zwei", new_string="2")
        self.assertEqual((self.cwd / "a.txt").read_text(), "eins\n2\ndrei\n")

    def test_edit_requires_read_and_unique_match(self) -> None:
        (self.cwd / "b.txt").write_text("x x")
        with self.assertRaises(ToolError):
            self.run_tool("Edit", file_path="b.txt", old_string="x", new_string="y")
        self.run_tool("Read", file_path="b.txt")
        with self.assertRaises(ToolError):
            self.run_tool("Edit", file_path="b.txt", old_string="x", new_string="y")
        self.run_tool("Edit", file_path="b.txt", old_string="x", new_string="y", replace_all="true")
        self.assertEqual((self.cwd / "b.txt").read_text(), "y y")

    def test_write_protects_unread_existing_file(self) -> None:
        (self.cwd / "c.txt").write_text("alt")
        with self.assertRaises(ToolError):
            self.run_tool("Write", file_path="c.txt", content="neu")

    def test_read_rejects_binary_and_missing(self) -> None:
        (self.cwd / "bin.dat").write_bytes(b"\0\1\2")
        with self.assertRaises(ToolError):
            self.run_tool("Read", file_path="bin.dat")
        with self.assertRaises(ToolError):
            self.run_tool("Read", file_path="gibt-es-nicht")

    def test_glob_patterns(self) -> None:
        (self.cwd / "src" / "sub").mkdir(parents=True)
        (self.cwd / "top.py").write_text("")
        (self.cwd / "src" / "m.py").write_text("")
        (self.cwd / "src" / "sub" / "n.js").write_text("")
        (self.cwd / "node_modules").mkdir()
        (self.cwd / "node_modules" / "skip.py").write_text("")
        self.assertEqual(set(self.run_tool("Glob", pattern="**/*.py").split()), {"top.py", "src/m.py"})
        self.assertEqual(set(self.run_tool("Glob", pattern="*.py").split()), {"top.py", "src/m.py"})
        self.assertEqual(self.run_tool("Glob", pattern="src/**/*.{js,ts}").strip(), "src/sub/n.js")
        self.assertEqual(self.run_tool("Glob", pattern="*.rs"), "Keine Treffer.")

    def test_grep(self) -> None:
        (self.cwd / "a.py").write_text("def Foo():\n    pass\n")
        (self.cwd / "b.txt").write_text("foo\n")
        self.assertEqual(self.run_tool("Grep", pattern="def F"), "a.py:1:def Foo():")
        both = self.run_tool("Grep", pattern="foo", case_insensitive=True)
        self.assertIn("a.py:1", both)
        self.assertIn("b.txt:1", both)
        self.assertEqual(self.run_tool("Grep", pattern="foo", glob="*.txt", case_insensitive=True), "b.txt:1:foo")
        with self.assertRaises(ToolError):
            self.run_tool("Grep", pattern="(")

    def test_ls_and_todo(self) -> None:
        (self.cwd / "ordner").mkdir()
        (self.cwd / "datei.txt").write_text("")
        self.assertEqual(self.run_tool("LS").splitlines(), ["ordner/", "datei.txt"])
        result = self.run_tool(
            "TodoWrite", todos=[{"content": "A", "status": "completed"}, {"content": "B", "status": "kaputt"}]
        )
        self.assertIn("[x] A", result)
        self.assertIn("[ ] B", result)

    def test_bash(self) -> None:
        result = self.run_tool("Bash", command="echo hallo && exit 3")
        self.assertIn("hallo", result)
        self.assertIn("[Exit-Code 3]", result)
        self.assertIn("Zeitlimit", self.run_tool("Bash", command="sleep 5", timeout=1))


class PermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = build_tools()

    def test_modes(self) -> None:
        never = mock.Mock(side_effect=AssertionError("darf nicht fragen"))
        self.assertTrue(Permissions("ask", ask=never).allowed(self.tools["Read"], ""))
        self.assertTrue(Permissions("yolo", ask=never).allowed(self.tools["Bash"], ""))
        edits = Permissions("accept-edits", ask=never)
        self.assertTrue(edits.allowed(self.tools["Edit"], ""))
        strict = Permissions("accept-edits", ask=lambda _: "n", show=lambda _: None)
        self.assertFalse(strict.allowed(self.tools["Bash"], ""))

    def test_answers(self) -> None:
        def perms(answer: str) -> Permissions:
            return Permissions("ask", ask=lambda _: answer, show=lambda _: None)

        self.assertTrue(perms("j").allowed(self.tools["Write"], ""))
        self.assertFalse(perms("").allowed(self.tools["Write"], ""))
        always = perms("i")
        self.assertTrue(always.allowed(self.tools["Bash"], ""))
        self.assertIn("Bash", always.always)
        with self.assertRaises(ValueError):
            Permissions("unsinn")


class ClientTests(unittest.TestCase):
    def test_normalize_host(self) -> None:
        self.assertEqual(normalize_host("localhost"), "http://localhost:11434")
        self.assertEqual(normalize_host("0.0.0.0:11434"), "http://127.0.0.1:11434")
        self.assertEqual(normalize_host("https://gpu.example:8443"), "https://gpu.example:8443")

    def test_models_and_selection(self) -> None:
        fake = FakeOllama([])
        self.addCleanup(fake.close)
        models = OllamaClient(fake.host).list_models()
        self.assertEqual(models, ["qwen2.5-coder:7b", "llama3.2:latest"])
        self.assertEqual(pick_model(models), "qwen2.5-coder:7b")
        self.assertTrue(is_installed("llama3.2", models))
        self.assertFalse(is_installed("gemma", models))

    def test_unreachable(self) -> None:
        with self.assertRaises(OllamaError):
            OllamaClient("127.0.0.1:1", timeout=2).list_models()


class AgentTests(TempDirCase):
    def make_agent(self, script, mode="yolo", ask=None):
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        perms = Permissions(mode, ask=ask or input, show=lambda _: None)
        agent = Agent(OllamaClient(fake.host), "qwen2.5-coder:7b", self.ctx, perms, UI(io.StringIO()))
        return agent, fake

    def test_tool_loop_creates_file(self) -> None:
        script = [
            tool_chunks("Write", {"file_path": "hallo.txt", "content": "Hi\n"}, prompt=10, out=5),
            text_chunks("Fertig.", prompt=20, out=3),
        ]
        agent, fake = self.make_agent(script)
        agent.run_turn("Lege hallo.txt an")
        self.assertEqual((self.cwd / "hallo.txt").read_text(), "Hi\n")
        self.assertEqual([m["role"] for m in agent.messages], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(agent.messages[-1]["content"], "Fertig.")
        self.assertEqual((agent.tokens_in, agent.tokens_out), (30, 8))
        second = fake.requests[1]["messages"]
        self.assertEqual(second[0]["role"], "system")
        self.assertIn("geschrieben", second[-1]["content"])
        self.assertEqual(second[-1]["tool_name"], "Write")
        self.assertEqual(fake.requests[0]["options"]["num_ctx"], 16384)
        self.assertEqual({t["function"]["name"] for t in fake.requests[0]["tools"]},
                         {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "LS", "TodoWrite"})

    def test_denied_permission_blocks_write(self) -> None:
        script = [tool_chunks("Write", {"file_path": "x.txt", "content": "1"}), text_chunks("ok")]
        agent, fake = self.make_agent(script, mode="ask", ask=lambda _: "n")
        agent.run_turn("schreibe x")
        self.assertFalse((self.cwd / "x.txt").exists())
        self.assertIn("abgelehnt", fake.requests[1]["messages"][-1]["content"])

    def test_unknown_tool_and_case_insensitive_name(self) -> None:
        (self.cwd / "f.txt").write_text("inhalt")
        script = [tool_chunks("gibtsnicht", {}), tool_chunks("read", {"file_path": "f.txt"}), text_chunks("ok")]
        agent, fake = self.make_agent(script)
        agent.run_turn("los")
        self.assertIn("Unbekanntes Werkzeug", fake.requests[1]["messages"][-1]["content"])
        self.assertIn("inhalt", fake.requests[2]["messages"][-1]["content"])

    def test_string_arguments_are_parsed(self) -> None:
        script = [tool_chunks("Write", json.dumps({"file_path": "s.txt", "content": "z"})), text_chunks("ok")]
        agent, _ = self.make_agent(script)
        agent.run_turn("los")
        self.assertEqual((self.cwd / "s.txt").read_text(), "z")

    def test_error_rolls_back_history(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(OllamaError):
            agent.run_turn("hallo")
        self.assertEqual(agent.messages, [])

    def test_pandora_md_in_system_prompt_and_clear(self) -> None:
        (self.cwd / "PANDORA.md").write_text("Nutze pytest.")
        agent, _ = self.make_agent([])
        self.assertIn("Nutze pytest.", agent.system_prompt())
        agent.messages = [{"role": "user", "content": "x"}]
        self.ctx.read_files.add("irgendwas")
        agent.clear()
        self.assertEqual((agent.messages, self.ctx.read_files), ([], set()))

    def test_compact(self) -> None:
        agent, fake = self.make_agent([text_chunks("Kurzfassung")])
        agent.messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        agent.compact()
        self.assertEqual(len(agent.messages), 2)
        self.assertIn("Kurzfassung", agent.messages[0]["content"])
        self.assertNotIn("tools", fake.requests[0])


if __name__ == "__main__":
    unittest.main()
