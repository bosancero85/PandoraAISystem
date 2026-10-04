"""Tests für Punkt 4: Auto-Fix & Continuous Quality Loop – Lint nach jeder Änderung, Tests vor jedem Stopp."""
from __future__ import annotations

import unittest
from unittest import mock

from pandora_code.config import Settings
from pandora_code.extensions.auto_fix import (
    AutoFixHookRunner, AutoFixState, lint_file, pick_linter, pick_test_runner, run_tests,
)
from pandora_code.extensions.hooks import HookRunner
from tests.test_extensions import ExtCase
from tests.test_pandora_code import text_chunks, tool_chunks


class PickLinterTests(unittest.TestCase):
    def test_prefers_ruff_over_flake8_for_python(self) -> None:
        from pathlib import Path
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p in ("ruff", "flake8")):
            self.assertEqual(pick_linter(Path("x.py")), ("ruff", "ruff check --quiet {file}"))

    def test_falls_back_to_flake8_when_ruff_missing(self) -> None:
        from pathlib import Path
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "flake8"):
            self.assertEqual(pick_linter(Path("x.py")), ("flake8", "flake8 {file}"))

    def test_none_when_nothing_installed(self) -> None:
        from pathlib import Path
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            self.assertIsNone(pick_linter(Path("x.py")))

    def test_unsupported_extension_is_none(self) -> None:
        from pathlib import Path
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True):
            self.assertIsNone(pick_linter(Path("x.rs")))

    def test_eslint_for_typescript(self) -> None:
        from pathlib import Path
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "eslint"):
            self.assertEqual(pick_linter(Path("x.tsx")), ("eslint", "eslint {file}"))


class PickTestRunnerTests(ExtCase):
    def test_detects_pytest_via_pyproject(self) -> None:
        (self.cwd / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "pytest"):
            self.assertEqual(pick_test_runner(self.cwd), ("pytest", "pytest -q"))

    def test_detects_npm_via_package_json(self) -> None:
        (self.cwd / "package.json").write_text("{}", encoding="utf-8")
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "npm"):
            self.assertEqual(pick_test_runner(self.cwd), ("npm", "npm test --silent"))

    def test_none_without_marker_file(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True):
            self.assertIsNone(pick_test_runner(self.cwd))

    def test_none_when_program_not_installed_despite_marker(self) -> None:
        (self.cwd / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            self.assertIsNone(pick_test_runner(self.cwd))


class LintFileTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "app.py").write_text("x=1\n", encoding="utf-8")
        self.state = AutoFixState()

    def test_clean_file_returns_none(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "ruff"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(0, "")):
            self.assertIsNone(lint_file(self.cwd, "app.py", self.state))

    def test_lint_errors_are_reported_with_program_name(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "ruff"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "app.py:1:2: E225 missing space")):
            note = lint_file(self.cwd, "app.py", self.state)
        self.assertIn("ruff", note)
        self.assertIn("E225", note)
        self.assertIn("app.py", note)

    def test_disabled_state_skips_lint(self) -> None:
        self.state.enabled = False
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "boom")) as run:
            self.assertIsNone(lint_file(self.cwd, "app.py", self.state))
        run.assert_not_called()

    def test_lint_only_disabled_skips_lint_but_leaves_tests_alone(self) -> None:
        self.state.lint_enabled = False
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True):
            self.assertIsNone(lint_file(self.cwd, "app.py", self.state))

    def test_missing_file_returns_none(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True):
            self.assertIsNone(lint_file(self.cwd, "missing.py", self.state))

    def test_no_linter_installed_returns_none(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            self.assertIsNone(lint_file(self.cwd, "app.py", self.state))


class RunTestsTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        (self.cwd / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        self.state = AutoFixState()

    def test_green_tests_return_none_and_set_last_ok_true(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "pytest"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(0, "5 passed")):
            self.assertIsNone(run_tests(self.cwd, self.state))
        self.assertTrue(self.state.last_test_ok)

    def test_failing_tests_report_output_and_set_last_ok_false(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "pytest"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "1 failed, AssertionError")):
            note = run_tests(self.cwd, self.state)
        self.assertFalse(self.state.last_test_ok)
        self.assertIn("AssertionError", note)
        self.assertIn("pytest", note)

    def test_override_command_takes_precedence(self) -> None:
        self.state.test_command_override = "make check"
        with mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "boom")) as run:
            note = run_tests(self.cwd, self.state)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "make check")
        self.assertIn("boom", note)

    def test_no_runner_detected_returns_none(self) -> None:
        (self.cwd / "pyproject.toml").unlink()
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            self.assertIsNone(run_tests(self.cwd, self.state))

    def test_disabled_state_skips_tests(self) -> None:
        self.state.enabled = False
        with mock.patch("pandora_code.extensions.auto_fix.run_command") as run:
            self.assertIsNone(run_tests(self.cwd, self.state))
        run.assert_not_called()


class HookRunnerWrapperTests(ExtCase):
    """Direkter Test von AutoFixHookRunner, ohne den vollen Agenten-Loop – prüft Verkettung und Config-Durchreichung."""

    class DummyAgent:
        def __init__(self, cwd):
            from pandora_code.tools import ToolContext
            self.ctx = ToolContext(cwd)

    def test_config_passthrough_to_inner_hookrunner(self) -> None:
        inner = HookRunner({"Stop": [{"hooks": [{"command": "x"}]}]}, self.cwd)
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=inner)
        self.assertEqual(wrapper.config, inner.config)

    def test_config_is_empty_dict_without_inner(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=None)
        self.assertEqual(wrapper.config, {})

    def test_pre_tool_and_user_prompt_delegate_to_inner(self) -> None:
        inner = mock.Mock()
        inner.pre_tool.return_value = "geblockt"
        inner.user_prompt.return_value = (None, "Kontext")
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=inner)
        self.assertEqual(wrapper.pre_tool("Bash", {}), "geblockt")
        self.assertEqual(wrapper.user_prompt("hi"), (None, "Kontext"))

    def test_pre_tool_without_inner_never_blocks(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=None)
        self.assertIsNone(wrapper.pre_tool("Bash", {}))

    def test_post_tool_skips_lint_on_tool_error(self) -> None:
        (self.cwd / "app.py").write_text("x=1\n", encoding="utf-8")
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.lint_file") as lint:
            feedback = wrapper.post_tool("Write", {"file_path": "app.py"}, "Fehler: keine Berechtigung")
        lint.assert_not_called()
        self.assertEqual(feedback, "")
        self.assertFalse(wrapper.state.dirty)

    def test_post_tool_marks_dirty_and_appends_lint_feedback(self) -> None:
        (self.cwd / "app.py").write_text("x=1\n", encoding="utf-8")
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.lint_file", return_value="[Auto-Fix: ruff] Problem"):
            feedback = wrapper.post_tool("Write", {"file_path": "app.py"}, "app.py geschrieben.")
        self.assertIn("Problem", feedback)
        self.assertTrue(wrapper.state.dirty)

    def test_post_tool_ignores_non_write_edit_tools(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.lint_file") as lint:
            wrapper.post_tool("Bash", {"command": "ls"}, "ok")
        lint.assert_not_called()
        self.assertFalse(wrapper.state.dirty)

    def test_stop_skips_tests_when_not_dirty(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(dirty=False), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.run_tests") as run:
            self.assertIsNone(wrapper.stop(False))
        run.assert_not_called()

    def test_stop_runs_tests_when_dirty_and_clears_flag_on_green(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(dirty=True), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.run_tests", return_value=None):
            self.assertIsNone(wrapper.stop(False))
        self.assertFalse(wrapper.state.dirty)

    def test_stop_keeps_dirty_flag_when_tests_still_fail(self) -> None:
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(dirty=True), inner=None)
        with mock.patch("pandora_code.extensions.auto_fix.run_tests", return_value="[Auto-Fix] Tests schlagen fehl"):
            reason = wrapper.stop(False)
        self.assertIn("schlagen fehl", reason)
        self.assertTrue(wrapper.state.dirty)

    def test_stop_prefers_inner_block_reason_over_own_tests(self) -> None:
        inner = mock.Mock()
        inner.stop.return_value = "externer Hook sagt nein"
        wrapper = AutoFixHookRunner(self.DummyAgent(self.cwd), AutoFixState(dirty=True), inner=inner)
        with mock.patch("pandora_code.extensions.auto_fix.run_tests") as run:
            reason = wrapper.stop(False)
        self.assertEqual(reason, "externer Hook sagt nein")
        run.assert_not_called()  # eigener Testlauf nur, wenn der verkettete Hook nicht schon blockiert


class AgentIntegrationTests(ExtCase):
    """End-to-End über den echten Agenten-Loop (run_turn mit FakeOllama), wie test_extensions.py es für die
    generischen Hooks tut – prüft, dass Auto-Fix genau dort greift, wo der Agent es tatsächlich sieht."""

    def test_lint_feedback_reaches_the_model_on_next_step(self) -> None:
        script = [tool_chunks("Write", {"file_path": "app.py", "content": "x=1"}), text_chunks("ok")]
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "ruff"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "E225 missing whitespace")):
            agent, fake = self.make_agent(script)
            agent.run_turn("schreibe app.py")
        self.assertIn("E225", fake.requests[1]["messages"][-1]["content"])

    def test_clean_write_adds_no_noise(self) -> None:
        script = [tool_chunks("Write", {"file_path": "app.py", "content": "x = 1\n"}), text_chunks("ok")]
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p == "ruff"), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(0, "")):
            agent, fake = self.make_agent(script)
            agent.run_turn("schreibe app.py")
        self.assertNotIn("Auto-Fix", fake.requests[1]["messages"][-1]["content"])

    def test_failing_tests_block_stop_until_green(self) -> None:
        script = [
            tool_chunks("Write", {"file_path": "app.py", "content": "x=1"}),
            text_chunks("fertig"),
            text_chunks("jetzt wirklich fertig"),
        ]
        (self.cwd / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        results = iter([(1, "1 failed"), (0, "1 passed")])  # erster Stopp-Versuch rot, zweiter grün
        with mock.patch("pandora_code.extensions.auto_fix.which",
                        side_effect=lambda p: p in ("ruff", "pytest")), \
             mock.patch("pandora_code.extensions.auto_fix.run_command",
                        side_effect=lambda *a, **k: next(results) if "pytest" in a[0] else (0, "")):
            agent, fake = self.make_agent(script)
            agent.run_turn("los")
        self.assertEqual(len(fake.requests), 3)  # Write+Antwort, erzwungene Fortsetzung, finale Antwort
        self.assertIn("1 failed", fake.requests[2]["messages"][-1]["content"])
        self.assertEqual(agent.messages[-1]["content"], "jetzt wirklich fertig")

    def test_stop_hook_chain_runs_autofix_after_configured_hook_passes(self) -> None:
        settings = Settings(hooks={})  # keine externen Hooks konfiguriert, nur Auto-Fix aktiv
        script = [
            tool_chunks("Write", {"file_path": "app.py", "content": "x=1"}),
            text_chunks("fertig"),
        ]
        (self.cwd / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        with mock.patch("pandora_code.extensions.auto_fix.which", side_effect=lambda p: p in ("ruff", "pytest")), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(0, "ok")):
            agent, fake = self.make_agent(script, settings=settings)
            agent.run_turn("los")
        self.assertEqual(len(fake.requests), 2)  # Tests grün -> kein erzwungener dritter Versuch

    def test_autofix_off_via_settings_disables_everything(self) -> None:
        settings = Settings(auto_fix=False)
        script = [tool_chunks("Write", {"file_path": "app.py", "content": "x=1"}), text_chunks("ok")]
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=True), \
             mock.patch("pandora_code.extensions.auto_fix.run_command", return_value=(1, "sollte nie laufen")) as run:
            agent, fake = self.make_agent(script, settings=settings)
            agent.run_turn("schreibe")
        run.assert_not_called()


class AutofixCommandTests(ExtCase):
    def _out(self, agent, arg: str) -> list[str]:
        out: list[str] = []
        from pandora_code.ui import UI
        ui = UI()
        ui.info = out.append  # type: ignore[assignment]
        ui.error = out.append  # type: ignore[assignment]
        handler, _ = agent.commands["autofix"]
        handler(arg, agent, ui)
        return out

    def test_shows_status_without_argument(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            agent, _ = self.make_agent([])
            out = self._out(agent, "")
        self.assertTrue(any("Auto-Fix: an" in line for line in out))

    def test_toggle_off_then_on(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            agent, _ = self.make_agent([])
            self._out(agent, "aus")
            out = self._out(agent, "")
            self.assertTrue(any("Auto-Fix: aus" in line for line in out))
            self._out(agent, "an")
            out = self._out(agent, "")
        self.assertTrue(any("Auto-Fix: an" in line for line in out))

    def test_lint_only_toggle(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            agent, _ = self.make_agent([])
            out = self._out(agent, "lint-aus")
        self.assertTrue(any("Lint: aus" in line for line in out))

    def test_invalid_argument_reports_usage(self) -> None:
        with mock.patch("pandora_code.extensions.auto_fix.which", return_value=False):
            agent, _ = self.make_agent([])
            out = self._out(agent, "quatsch")
        self.assertTrue(any("Nutzung" in line for line in out))


if __name__ == "__main__":
    unittest.main()
