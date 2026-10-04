"""Tests für Punkt 9: Windows/macOS/Linux-Tauglichkeit – Shell-Auswahl des Bash-Werkzeugs und VT100.

Diese Sandbox läuft unter Linux, daher wird das Windows-Verhalten über mock.patch("platform.system", ...)
und mock.patch("shutil.which", ...) simuliert, statt sich auf die reale Plattform zu verlassen – so ist
das Verhalten für alle drei Betriebssysteme deterministisch und unabhängig davon prüfbar, wo die Tests
tatsächlich laufen.
"""
from __future__ import annotations

import io
import subprocess
import unittest
from unittest import mock

from pandora_code.tools import ToolContext, bash_backend, bash_tool, describe_shell
from pandora_code.ui import UI, enable_windows_vt
from tests.test_pandora_code import TempDirCase


class BashBackendTests(unittest.TestCase):
    def test_posix_uses_native_shell_unchanged(self) -> None:
        with mock.patch("platform.system", return_value="Linux"):
            prefix, desc = bash_backend()
        self.assertIsNone(prefix)
        self.assertIn("POSIX", desc)

    def test_macos_also_uses_native_shell(self) -> None:
        with mock.patch("platform.system", return_value="Darwin"):
            prefix, desc = bash_backend()
        self.assertIsNone(prefix)
        self.assertIn("POSIX", desc)

    def test_windows_with_git_bash_or_wsl_uses_real_bash(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value=r"C:\Program Files\Git\bin\bash.exe"):
            prefix, desc = bash_backend()
        self.assertEqual(prefix, [r"C:\Program Files\Git\bin\bash.exe", "-c"])
        self.assertIn("Bash", desc)
        self.assertIn("gefunden", desc)

    def test_windows_without_bash_falls_back_to_cmd_with_clear_hint(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value=None):
            prefix, desc = bash_backend()
        self.assertIsNone(prefix)
        self.assertIn("cmd.exe", desc)
        self.assertIn("powershell", desc.lower())

    def test_describe_shell_matches_backend_description(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value=None):
            self.assertEqual(describe_shell(), bash_backend()[1])


class BashToolPlatformTests(TempDirCase):
    def test_posix_path_runs_via_shell_true(self) -> None:
        with mock.patch("platform.system", return_value="Linux"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="ok\n", stderr="", returncode=0)) as run:
            bash_tool(self.ctx, {"command": "echo ok"})
        self.assertEqual(run.call_args.kwargs["shell"], True)
        self.assertEqual(run.call_args.args[0], "echo ok")

    def test_windows_with_bash_runs_via_explicit_argv_not_shell(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value="/usr/bin/bash"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="ok\n", stderr="", returncode=0)) as run:
            bash_tool(self.ctx, {"command": "echo ok"})
        self.assertEqual(run.call_args.kwargs["shell"], False)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/bash", "-c", "echo ok"])

    def test_windows_without_bash_runs_via_shell_true_cmd(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="ok\n", stderr="", returncode=0)) as run:
            bash_tool(self.ctx, {"command": "dir"})
        self.assertEqual(run.call_args.kwargs["shell"], True)
        self.assertEqual(run.call_args.args[0], "dir")

    def test_real_execution_still_works_end_to_end_on_this_platform(self) -> None:
        # Kein Mock: bestätigt, dass die Umstellung auf die reale Ausführung dieser (Linux-)Sandbox
        # keinen Einfluss hat - derselbe Test wie zuvor in test_pandora_code.py.
        result = bash_tool(self.ctx, {"command": "echo hallo && exit 3"})
        self.assertIn("hallo", result)
        self.assertIn("[Exit-Code 3]", result)

    def test_timeout_message_unchanged_regardless_of_backend(self) -> None:
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dir", timeout=1)):
            result = bash_tool(self.ctx, {"command": "dir", "timeout": 1})
        self.assertIn("Zeitlimit", result)


class SystemPromptShellAwarenessTests(TempDirCase):
    def test_default_prompt_mentions_detected_shell(self) -> None:
        from pandora_code.agent import Agent
        from pandora_code.ollama_client import OllamaClient
        from pandora_code.permissions import Permissions
        agent = Agent(OllamaClient("127.0.0.1:1"), "m", self.ctx, Permissions("yolo"), UI(io.StringIO()))
        with mock.patch("pandora_code.agent.platform.system", return_value="Windows"), \
             mock.patch("pandora_code.tools.platform.system", return_value="Windows"), \
             mock.patch("pandora_code.tools.shutil.which", return_value=None):
            prompt = agent.system_prompt()
        self.assertIn("Windows", prompt)
        self.assertIn("cmd.exe", prompt)
        agent.close()


class WindowsVtTests(unittest.TestCase):
    def test_enable_windows_vt_is_noop_on_posix(self) -> None:
        with mock.patch("os.name", "posix"), mock.patch("os.system") as system:
            enable_windows_vt()
        system.assert_not_called()

    def test_enable_windows_vt_calls_os_system_on_windows(self) -> None:
        with mock.patch("os.name", "nt"), mock.patch("os.system") as system:
            enable_windows_vt()
        system.assert_called_once_with("")

    def test_ui_init_enables_vt_without_requiring_banner(self) -> None:
        with mock.patch("pandora_code.ui.enable_windows_vt") as enable:
            UI(io.StringIO())
        enable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
