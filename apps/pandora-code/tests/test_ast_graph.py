"""Tests für Punkt 1a: AST-Code-Graph-Engine – strukturelles Codeverständnis statt reiner Grep-Suche."""
from __future__ import annotations

import textwrap
import unittest

from pandora_code.extensions.ast_graph import (
    TREE_SITTER_AVAILABLE, CodeGraph, _index_python, _index_regex,
)
from tests.test_extensions import ExtCase


class PythonAstBackendTests(unittest.TestCase):
    """Direkter Test des Python-Backends (ast-Modul) ohne Datei-I/O."""

    SOURCE = textwrap.dedent('''
        import os

        class Greeter:
            def __init__(self, name):
                self.name = name

            def greet(self):
                return format_message(self.name)

        def format_message(name):
            return f"Hallo {name}"

        def main():
            g = Greeter("Aki")
            print(g.greet())
            format_message("direkt")
    ''')

    def setUp(self) -> None:
        self.symbols, self.calls, self.error = _index_python(self.SOURCE, "demo.py")

    def test_no_syntax_error(self) -> None:
        self.assertIsNone(self.error)

    def test_finds_class_and_methods_and_functions(self) -> None:
        by_qual = {s.qualname: s for s in self.symbols}
        self.assertEqual(by_qual["Greeter"].kind, "class")
        self.assertEqual(by_qual["Greeter.greet"].kind, "method")
        self.assertEqual(by_qual["format_message"].kind, "function")
        self.assertEqual(by_qual["format_message"].signature, "(name)")
        self.assertEqual(by_qual["Greeter.__init__"].signature, "(name)")  # 'self' wird herausgefiltert

    def test_finds_callers_of_format_message(self) -> None:
        callers = [c for c in self.calls if c.callee == "format_message"]
        self.assertEqual(len(callers), 2)
        callers_by_scope = {c.caller_qualname for c in callers}
        self.assertEqual(callers_by_scope, {"Greeter.greet", "main"})

    def test_does_not_confuse_definition_with_call(self) -> None:
        # 'def format_message(name):' darf nicht als Aufruf von 'format_message' auftauchen.
        lines_with_def = [c.line for c in self.calls if c.callee == "format_message"]
        self.assertNotIn(12, lines_with_def)  # Zeile der Definition wird nicht als Call gezählt

    def test_syntax_error_is_reported_not_raised(self) -> None:
        symbols, calls, error = _index_python("def broken(:\n    pass", "bad.py")
        self.assertEqual((symbols, calls), ([], []))
        self.assertIsNotNone(error)


class RegexFallbackTests(unittest.TestCase):
    """Fallback für Nicht-Python-Sprachen, wenn kein Tree-sitter installiert ist (Standardfall ohne Extra-Paket)."""

    def test_javascript_function_and_class_detected(self) -> None:
        src = textwrap.dedent('''
            class Widget {
              render() { return null; }
            }
            function buildWidget(name) {
              return helper(name);
            }
            const helper = (name) => name.trim();
        ''')
        symbols, calls, error = _index_regex(src, "widget.js", "javascript")
        self.assertIsNone(error)
        names = {s.name for s in symbols}
        self.assertIn("Widget", names)
        self.assertIn("buildWidget", names)
        self.assertIn("helper", names)
        self.assertTrue(all(s.backend == "regex" for s in symbols))
        self.assertIn("helper", {c.callee for c in calls})

    def test_lua_function_detected(self) -> None:
        src = "local function greet(name)\n  print(name)\nend\n"
        symbols, _, error = _index_regex(src, "greet.lua", "lua")
        self.assertIsNone(error)
        self.assertIn("greet", {s.name for s in symbols})

    def test_control_keywords_are_not_reported_as_calls(self) -> None:
        src = "function f() {\n  if (x) {\n    doThing();\n  }\n}\n"
        _, calls, _ = _index_regex(src, "f.js", "javascript")
        callees = {c.callee for c in calls}
        self.assertNotIn("if", callees)
        self.assertIn("doThing", callees)


class CodeGraphIntegrationTests(ExtCase):
    """End-to-End über echte Dateien im Projektordner (self.cwd aus TempDirCase)."""

    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "app.py").write_text(textwrap.dedent('''
            def load_config(path):
                return open(path).read()

            class Server:
                def start(self):
                    cfg = load_config("cfg.yaml")
                    return cfg
        '''), encoding="utf-8")
        (self.cwd / "helpers.py").write_text(textwrap.dedent('''
            from app import load_config

            def bootstrap():
                return load_config("default.yaml")
        '''), encoding="utf-8")
        (self.cwd / "node_modules").mkdir()
        (self.cwd / "node_modules" / "ignored.py").write_text("def load_config(): pass\n", encoding="utf-8")

    def test_build_indexes_python_files_and_skips_excluded_dirs(self) -> None:
        graph = CodeGraph(self.cwd)
        graph.build()
        files = {info for info in graph.files}
        self.assertTrue(any(p.name == "app.py" for p in files))
        self.assertFalse(any("node_modules" in p.parts for p in files))

    def test_find_definitions_across_files(self) -> None:
        graph = CodeGraph(self.cwd)
        graph.build()
        defs = graph.find_definitions("Server")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].file, "app.py")
        self.assertEqual(defs[0].kind, "class")

    def test_find_callers_across_files(self) -> None:
        graph = CodeGraph(self.cwd)
        graph.build()
        callers = graph.find_callers("load_config")
        files = {c.file for c in callers}
        self.assertEqual(files, {"app.py", "helpers.py"})  # node_modules-Kopie zählt nicht mit

    def test_refresh_picks_up_changed_file_without_full_rebuild(self) -> None:
        graph = CodeGraph(self.cwd)
        graph.build()
        (self.cwd / "app.py").write_text("def brand_new():\n    pass\n", encoding="utf-8")
        changed, total = graph.refresh()
        self.assertGreaterEqual(changed, 1)
        self.assertTrue(any(s.name == "brand_new" for s in graph.all_symbols()))
        self.assertFalse(any(s.name == "Server" for s in graph.all_symbols()))  # überschriebene Datei neu gelesen

    def test_summary_mentions_tree_sitter_hint_state(self) -> None:
        (self.cwd / "extra.js").write_text("function f() {}\n", encoding="utf-8")
        graph = CodeGraph(self.cwd)
        graph.build()
        summary = graph.summary()
        if not TREE_SITTER_AVAILABLE:
            self.assertIn("tree_sitter_languages nicht installiert", summary)


class AgentToolIntegrationTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "lib.py").write_text(textwrap.dedent('''
            class PaymentProcessor:
                def charge(self, amount):
                    return validate(amount)

            def validate(amount):
                if amount <= 0:
                    raise ValueError("ungültig")
                return True
        '''), encoding="utf-8")

    def test_code_def_tool_finds_class(self) -> None:
        agent, _ = self.make_agent([])
        result = agent.tools["CodeDef"].run(agent.ctx, {"name": "PaymentProcessor"})
        self.assertIn("lib.py:", result)
        self.assertIn("class", result)

    def test_code_callers_tool_finds_call_site(self) -> None:
        agent, _ = self.make_agent([])
        result = agent.tools["CodeCallers"].run(agent.ctx, {"name": "validate"})
        self.assertIn("lib.py:", result)
        self.assertIn("PaymentProcessor.charge", result)

    def test_code_symbols_tool_filters_by_kind(self) -> None:
        agent, _ = self.make_agent([])
        result = agent.tools["CodeSymbols"].run(agent.ctx, {"kind": "class"})
        self.assertIn("PaymentProcessor", result)
        self.assertNotIn("validate", result)

    def test_graph_command_reports_summary(self) -> None:
        agent, _ = self.make_agent([])
        out = []
        from pandora_code.ui import UI
        ui = UI()
        ui.info = out.append  # type: ignore[assignment]
        handler, _ = agent.commands["graph"]
        handler("", agent, ui)
        self.assertTrue(any("Code-Graph" in line for line in out))


if __name__ == "__main__":
    unittest.main()
