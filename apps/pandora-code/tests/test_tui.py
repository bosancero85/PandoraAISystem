"""Tests für Punkt 5a: Textual-TUI – die textual-unabhängige Logik (TuiUI, Rückfrage-Brücke, Diff-Wrapping).

Textual ist in dieser Umgebung nicht installiert (optionale Abhängigkeit, `pip install pandora-code[tui]`).
Alles hier Getestete hängt bewusst nur von einem duck-typed 'app'-Objekt ab (call_from_thread/append_log/
set_diff/request_confirmation) und ist daher unabhängig von einer echten Textual-Installation lauffähig –
nur `PandoraTuiApp` selbst (echte Widgets) bleibt ungetestet, siehe Modul-Docstring von ui/tui.py.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from pandora_code.permissions import Permissions
from pandora_code.tools import Tool, ToolContext, ToolError, schema
from pandora_code.ui.tui import (
    INSTALL_HINT, TEXTUAL_AVAILABLE, ConfirmRequest, TuiUI, attach, make_tui_ask, make_tui_show,
    wrap_diff_tool,
)
from tests.test_extensions import ExtCase
from tests.test_pandora_code import FakeOllama, TempDirCase


class FakeApp:
    """Ruft alles synchron im aufrufenden Thread auf – reicht, um die Logik zu prüfen, ohne dass ein
    echter Textual-Event-Loop läuft."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.diffs: list[str] = []
        self.confirmations: list[ConfirmRequest] = []
        self.next_answer = "j"

    def call_from_thread(self, func, *args) -> None:
        func(*args)

    def append_log(self, text: str, style: str = "") -> None:
        self.log.append((text, style))

    def set_diff(self, text: str) -> None:
        self.diffs.append(text)

    def request_confirmation(self, request: ConfirmRequest) -> None:
        self.confirmations.append(request)
        request.answer = self.next_answer
        request.event.set()


class TuiUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FakeApp()
        self.ui = TuiUI(self.app)

    def test_stream_appends_plain_text(self) -> None:
        self.ui.begin_assistant()
        self.ui.stream("Hallo ")
        self.ui.stream("Welt")
        self.ui.end_assistant()
        texts = [t for t, _ in self.app.log]
        self.assertEqual(texts, ["Hallo ", "Welt", "\n"])

    def test_thinking_then_stream_inserts_blank_line(self) -> None:
        self.ui.begin_assistant()
        self.ui.thinking("überlege...")
        self.ui.stream("Antwort")
        texts = [t for t, _ in self.app.log]
        self.assertEqual(texts, ["überlege...", "\n", "Antwort"])

    def test_thinking_uses_dim_style(self) -> None:
        self.ui.thinking("x")
        self.assertEqual(self.app.log[0][1], "dim")

    def test_tool_call_formats_name_and_args(self) -> None:
        self.ui.tool_call("Write", {"file_path": "a.py", "content": "x" * 300})
        text, style = self.app.log[0]
        self.assertIn("Write(", text)
        self.assertEqual(style, "bold")

    def test_tool_result_truncates_long_output(self) -> None:
        result = "\n".join(f"line {i}" for i in range(20))
        self.ui.tool_result(result)
        text, style = self.app.log[0]
        self.assertIn("… (+12 Zeilen)", text)
        self.assertEqual(style, "dim")

    def test_tool_result_short_output_not_truncated(self) -> None:
        self.ui.tool_result("eine Zeile")
        text, _ = self.app.log[0]
        self.assertNotIn("…", text)
        self.assertIn("eine Zeile", text)

    def test_error_uses_bold_red(self) -> None:
        self.ui.error("kaputt")
        text, style = self.app.log[0]
        self.assertIn("kaputt", text)
        self.assertEqual(style, "bold red")

    def test_info_uses_dim(self) -> None:
        self.ui.info("Hinweis")
        self.assertEqual(self.app.log[0][1], "dim")


class ConfirmationBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FakeApp()

    def test_show_forwards_preview_to_diff_panel(self) -> None:
        make_tui_show(self.app)("--- a\n+++ b\n")
        self.assertEqual(self.app.diffs, ["--- a\n+++ b\n"])

    def test_ask_returns_answer_set_by_app(self) -> None:
        self.app.next_answer = "immer"
        answer = make_tui_ask(self.app)("Write erlauben?")
        self.assertEqual(answer, "immer")
        self.assertEqual(len(self.app.confirmations), 1)
        self.assertEqual(self.app.confirmations[0].prompt, "Write erlauben?")

    def test_ask_blocks_until_event_is_set(self) -> None:
        """Mit einer App, die NICHT sofort antwortet (echter Cross-Thread-Fall): ask() muss warten."""
        released = threading.Event()

        class SlowApp(FakeApp):
            def call_from_thread(self, func, *args):
                def worker():
                    released.wait(timeout=2)
                    func(*args)
                threading.Thread(target=worker, daemon=True).start()

        app = SlowApp()
        app.next_answer = "n"
        result_box: dict[str, str] = {}

        def call_ask():
            result_box["answer"] = make_tui_ask(app)("Bash erlauben?")

        t = threading.Thread(target=call_ask)
        t.start()
        time.sleep(0.05)
        self.assertNotIn("answer", result_box)  # noch nicht beantwortet -> Worker-Thread wartet wirklich
        released.set()
        t.join(timeout=2)
        self.assertEqual(result_box["answer"], "n")

    def test_permissions_integration_ask_and_show_are_called(self) -> None:
        """End-to-End mit der echten Permissions-Klasse: show() zeigt den Diff, ask() liefert die Antwort."""
        app = FakeApp()
        app.next_answer = "j"
        perms = Permissions("ask", ask=make_tui_ask(app), show=make_tui_show(app))
        tool = Tool("Write", "...", schema({}, ()), lambda ctx, a: "ok", mutating=True)
        self.assertTrue(perms.allowed(tool, "--- diff ---"))
        self.assertEqual(app.diffs, ["--- diff ---"])
        self.assertEqual(len(app.confirmations), 1)


class WrapDiffToolTests(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = FakeApp()

    def test_successful_write_pushes_diff_to_panel(self) -> None:
        original = Tool(
            "Write", "...", schema({}, ()),
            run=lambda ctx, args: "Datei geschrieben.",
            preview=lambda ctx, args: "--- vorher\n+++ nachher\n",
            mutating=True,
        )
        wrapped = wrap_diff_tool(original, self.app)
        result = wrapped.run(self.ctx, {"file_path": "a.py"})
        self.assertEqual(result, "Datei geschrieben.")
        self.assertEqual(self.app.diffs, ["--- vorher\n+++ nachher\n"])

    def test_failed_write_does_not_touch_diff_panel(self) -> None:
        original = Tool(
            "Write", "...", schema({}, ()),
            run=lambda ctx, args: "Fehler: keine Berechtigung",
            preview=lambda ctx, args: "--- diff ---",
            mutating=True,
        )
        wrapped = wrap_diff_tool(original, self.app)
        wrapped.run(self.ctx, {"file_path": "a.py"})
        self.assertEqual(self.app.diffs, [])

    def test_preview_exception_does_not_break_the_tool(self) -> None:
        def boom(ctx, args):
            raise ValueError("kaputte Vorschau")

        original = Tool("Write", "...", schema({}, ()), run=lambda ctx, args: "ok", preview=boom, mutating=True)
        wrapped = wrap_diff_tool(original, self.app)
        self.assertEqual(wrapped.run(self.ctx, {}), "ok")
        self.assertEqual(self.app.diffs, [])  # leerer Diff wird nicht angezeigt, aber kein Absturz

    def test_tool_without_preview_is_returned_unchanged(self) -> None:
        original = Tool("Bash", "...", schema({}, ()), run=lambda ctx, args: "ok", preview=None, mutating=True)
        self.assertIs(wrap_diff_tool(original, self.app), original)


class AttachTests(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = FakeApp()

    def _make_agent(self):
        from pandora_code.agent import Agent
        from pandora_code.ollama_client import OllamaClient
        from pandora_code.ui import UI
        client = OllamaClient("127.0.0.1:1")
        perms = Permissions("yolo")
        return Agent(client, "qwen2.5-coder:7b", self.ctx, perms, UI())

    def test_attach_replaces_ui_and_permission_callbacks(self) -> None:
        agent = self._make_agent()
        attach(agent, self.app)
        self.assertIsInstance(agent.ui, TuiUI)
        self.assertIs(agent.ui.app, self.app)
        agent.perms.show("--- diff ---")
        self.assertEqual(self.app.diffs, ["--- diff ---"])

    def test_attach_wraps_write_and_edit_tools_for_diff_preview(self) -> None:
        agent = self._make_agent()
        original_write = agent.tools["Write"]
        attach(agent, self.app)
        self.assertIsNot(agent.tools["Write"], original_write)
        agent.tools["Write"].run(agent.ctx, {"file_path": "new.py", "content": "x = 1\n"})
        self.assertTrue(self.app.diffs)  # Diff wurde tatsächlich ins Panel geschickt

    def test_attach_leaves_other_tools_untouched(self) -> None:
        agent = self._make_agent()
        original_bash = agent.tools["Bash"]
        attach(agent, self.app)
        self.assertIs(agent.tools["Bash"], original_bash)


class ModuleAvailabilityTests(unittest.TestCase):
    def test_install_hint_mentions_pip_extra(self) -> None:
        self.assertIn("pandora-code[tui]", INSTALL_HINT)

    def test_textual_not_installed_in_this_environment(self) -> None:
        # Dokumentiert bewusst den Zustand dieser Sandbox (kein Netzwerk): launch_tui() muss dann klar
        # scheitern statt sich schlechter zu verhalten, siehe CliTuiFlagTests für den vollen CLI-Pfad.
        self.assertFalse(TEXTUAL_AVAILABLE)

    def test_launch_tui_without_textual_raises_clear_error(self) -> None:
        if TEXTUAL_AVAILABLE:
            self.skipTest("Textual ist installiert – dieser Zweig gilt nur für die Fallback-Variante.")
        from pandora_code.ui.tui import launch_tui
        with self.assertRaises(RuntimeError) as ctx:
            launch_tui(mock.Mock())
        self.assertIn("textual", str(ctx.exception).lower())


class CliTuiFlagTests(ExtCase):
    """--tui auf CLI-Ebene: ohne installiertes Textual muss main() klar mit Exit-Code 1 abbrechen,
    NACHDEM Modell/Erweiterungen normal aufgelöst wurden (kein stiller Rückfall auf die Konsole)."""

    def test_tui_flag_without_textual_fails_clearly(self) -> None:
        if TEXTUAL_AVAILABLE:
            self.skipTest("Textual ist installiert – dieser Zweig gilt nur für die Fallback-Variante.")
        import contextlib
        import io

        from pandora_code import cli
        fake = FakeOllama([])
        self.addCleanup(fake.close)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--tui", "--host", fake.host, "--cwd", str(self.cwd)])
        self.assertEqual(code, 1)
        self.assertIn("textual", err.getvalue().lower())

    def test_tui_flag_is_recognized_by_the_parser(self) -> None:
        from pandora_code.cli import build_parser
        args = build_parser().parse_args(["--tui"])
        self.assertTrue(args.tui)


if __name__ == "__main__":
    unittest.main()
