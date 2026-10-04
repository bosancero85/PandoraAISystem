"""Tests für Punkt 2: Sandbox-Engine – Firejail/Docker statt direkter Host-Ausführung für Bash."""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from pandora_code.extensions.sandbox import (
    BACKENDS, SandboxConfig, SandboxState, build_argv, docker_daemon_ok, resolve,
)
from tests.test_extensions import ExtCase


class ResolveTests(unittest.TestCase):
    def test_off_always_wins(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="off"), {"firejail": True, "docker": True})
        self.assertEqual(backend, "none")
        self.assertIn("deaktiviert", reason)

    def test_auto_prefers_firejail_over_docker(self) -> None:
        backend, _ = resolve(SandboxConfig(backend="auto"), {"firejail": True, "docker": True})
        self.assertEqual(backend, "firejail")

    def test_auto_falls_back_to_docker_when_configured(self) -> None:
        cfg = SandboxConfig(backend="auto", container="devbox")
        backend, reason = resolve(cfg, {"firejail": False, "docker": True})
        self.assertEqual(backend, "docker")
        self.assertIn("auto", reason)

    def test_auto_ignores_docker_without_container_or_image(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="auto"), {"firejail": False, "docker": True})
        self.assertEqual(backend, "none")
        self.assertIn("verfügbar", reason)

    def test_auto_with_nothing_available_is_none(self) -> None:
        backend, _ = resolve(SandboxConfig(backend="auto"), {"firejail": False, "docker": False})
        self.assertEqual(backend, "none")

    def test_explicit_firejail_without_binary_falls_back_with_reason(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="firejail"), {"firejail": False, "docker": True})
        self.assertEqual(backend, "none")
        self.assertIn("nicht installiert", reason)

    def test_explicit_docker_without_daemon_falls_back(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="docker", image="alpine"), {"firejail": True, "docker": False})
        self.assertEqual(backend, "none")
        self.assertIn("Daemon", reason)

    def test_explicit_docker_without_container_or_image_falls_back(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="docker"), {"firejail": False, "docker": True})
        self.assertEqual(backend, "none")
        self.assertIn("sandboxContainer", reason)

    def test_explicit_docker_with_image_wins(self) -> None:
        backend, _ = resolve(SandboxConfig(backend="docker", image="my-kali"), {"firejail": True, "docker": True})
        self.assertEqual(backend, "docker")

    def test_unknown_backend_string_is_none(self) -> None:
        backend, reason = resolve(SandboxConfig(backend="qemu"), {"firejail": True, "docker": True})
        self.assertEqual(backend, "none")
        self.assertIn("unbekannt", reason)

    def test_firejail_missing_hint_is_platform_aware(self) -> None:
        with mock.patch("platform.system", return_value="Linux"):
            _, reason = resolve(SandboxConfig(backend="firejail"), {"firejail": False, "docker": False})
        self.assertIn("apt install firejail", reason)
        for system in ("Darwin", "Windows"):
            with mock.patch("platform.system", return_value=system):
                _, reason = resolve(SandboxConfig(backend="firejail"), {"firejail": False, "docker": False})
            self.assertIn("gibt es nicht für " + system, reason)
            self.assertNotIn("apt install", reason)

    def test_auto_fallback_hint_is_platform_aware(self) -> None:
        with mock.patch("platform.system", return_value="Windows"):
            _, reason = resolve(SandboxConfig(backend="auto"), {"firejail": False, "docker": False})
        self.assertIn("Docker", reason)
        self.assertNotIn("firejail installieren", reason)


class DockerDaemonCheckTests(unittest.TestCase):
    def test_false_when_binary_missing(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(docker_daemon_ok())

    def test_true_when_binary_present_and_info_succeeds(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(docker_daemon_ok())

    def test_false_when_daemon_unreachable(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertFalse(docker_daemon_ok())

    def test_false_on_timeout(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=3)):
            self.assertFalse(docker_daemon_ok())


class BuildArgvTests(unittest.TestCase):
    def test_firejail_blocks_network_by_default(self) -> None:
        argv = build_argv("firejail", "ls -la", SandboxConfig(), cwd="/proj")
        self.assertIn("--net=none", argv)
        self.assertIn("--noroot", argv)
        self.assertEqual(argv[-3:], ["bash", "-c", "ls -la"])

    def test_firejail_allows_network_when_enabled(self) -> None:
        argv = build_argv("firejail", "curl x", SandboxConfig(network=True), cwd="/proj")
        self.assertNotIn("--net=none", argv)

    def test_docker_exec_uses_existing_container(self) -> None:
        cfg = SandboxConfig(container="devbox", workdir="/work")
        argv = build_argv("docker", "make test", cfg, cwd="/proj")
        self.assertEqual(argv, ["docker", "exec", "-w", "/work", "devbox", "bash", "-c", "make test"])

    def test_docker_run_uses_ephemeral_image_with_network_disabled(self) -> None:
        cfg = SandboxConfig(image="kali-mini")
        argv = build_argv("docker", "id", cfg, cwd="/proj")
        self.assertIn("--rm", argv)
        self.assertIn("/proj:/workspace", argv)
        self.assertIn("--network", argv)
        self.assertIn("none", argv)
        self.assertEqual(argv[-4:], ["kali-mini", "bash", "-c", "id"])

    def test_docker_run_honours_network_flag(self) -> None:
        cfg = SandboxConfig(image="kali-mini", network=True)
        argv = build_argv("docker", "id", cfg, cwd="/proj")
        self.assertNotIn("--network", argv)


class SandboxStateCacheTests(unittest.TestCase):
    def test_result_is_cached_within_ttl(self) -> None:
        cfg = SandboxConfig(backend="auto")
        state = SandboxState(cfg, ttl=1000.0)
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}) as det:
            first = state.current()
            second = state.current()
        self.assertEqual(det.call_count, 1)  # zweiter Aufruf kam aus dem Cache
        self.assertEqual(first, second)

    def test_invalidate_forces_redetect(self) -> None:
        cfg = SandboxConfig(backend="auto")
        state = SandboxState(cfg, ttl=1000.0)
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}) as det:
            state.current()
            state.invalidate()
            state.current()
        self.assertEqual(det.call_count, 2)


class BashReplacementTests(ExtCase):
    """Prüft, dass die Erweiterung das Bash-Werkzeug wirklich ersetzt und alle Backends korrekt anspricht."""

    def test_without_any_backend_falls_back_to_original_host_execution(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": False, "docker": False}):
            agent, _ = self.make_agent([])
        result = agent.tools["Bash"].run(agent.ctx, {"command": "echo hallo"})
        self.assertIn("hallo", result)
        self.assertIn("Exit-Code 0", result)
        self.assertNotIn("[Sandbox:", result)  # Host-Fallback nutzt unverändert den Original-Bash-Pfad

    def test_bash_description_mentions_sandbox(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": False, "docker": False}):
            agent, _ = self.make_agent([])
        self.assertIn("sandbox", agent.tools["Bash"].description.lower())

    def test_firejail_backend_is_actually_invoked(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            fake_proc = mock.Mock(stdout="ok\n", stderr="", returncode=0)
            with mock.patch("pandora_code.extensions.sandbox.subprocess.run", return_value=fake_proc) as run:
                result = agent.tools["Bash"].run(agent.ctx, {"command": "whoami"})
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "firejail")
        self.assertIn("whoami", argv)
        self.assertIn("[Sandbox: firejail]", result)

    def test_docker_backend_is_actually_invoked(self) -> None:
        settings = self._settings_with(sandbox="docker", sandbox_container="devbox")
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": False, "docker": True}):
            agent, _ = self.make_agent([], settings=settings)
            fake_proc = mock.Mock(stdout="root\n", stderr="", returncode=0)
            with mock.patch("pandora_code.extensions.sandbox.subprocess.run", return_value=fake_proc) as run:
                result = agent.tools["Bash"].run(agent.ctx, {"command": "whoami"})
        argv = run.call_args.args[0]
        self.assertEqual(argv[:2], ["docker", "exec"])
        self.assertIn("devbox", argv)
        self.assertIn("[Sandbox: docker]", result)

    def test_timeout_is_reported_with_backend_name(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            with mock.patch("pandora_code.extensions.sandbox.subprocess.run",
                            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
                result = agent.tools["Bash"].run(agent.ctx, {"command": "sleep 999", "timeout": 5})
        self.assertIn("Zeitlimit", result)
        self.assertIn("firejail", result)

    def test_backend_launch_failure_is_reported_not_raised(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            with mock.patch("pandora_code.extensions.sandbox.subprocess.run", side_effect=OSError("nicht gefunden")):
                result = agent.tools["Bash"].run(agent.ctx, {"command": "ls"})
        self.assertIn("Fehler", result)
        self.assertIn("/sandbox", result)

    def test_command_missing_still_raises_tool_error(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            with self.assertRaises(Exception):
                agent.tools["Bash"].run(agent.ctx, {})

    def _settings_with(self, **overrides):
        from pandora_code.config import Settings
        settings = Settings()
        for key, value in overrides.items():
            setattr(settings, key, value)
        return settings


class SandboxCommandTests(ExtCase):
    def _run_command(self, agent, arg: str) -> list[str]:
        out: list[str] = []
        from pandora_code.ui import UI
        ui = UI()
        ui.info = out.append  # type: ignore[assignment]
        ui.error = out.append  # type: ignore[assignment]
        handler, _ = agent.commands["sandbox"]
        handler(arg, agent, ui)
        return out

    def test_shows_current_backend_without_argument(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            out = self._run_command(agent, "")
        self.assertTrue(any("Sandbox: firejail (" in line for line in out))

    def test_switch_to_off_disables_sandbox_immediately(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": True, "docker": False}):
            agent, _ = self.make_agent([])
            out = self._run_command(agent, "off")
            self.assertTrue(any("Sandbox: none" in line for line in out))
            result = agent.tools["Bash"].run(agent.ctx, {"command": "echo x"})
        self.assertNotIn("[Sandbox:", result)  # off -> unveränderter Host-Pfad

    def test_invalid_choice_reports_usage(self) -> None:
        with mock.patch("pandora_code.extensions.sandbox.detect", return_value={"firejail": False, "docker": False}):
            agent, _ = self.make_agent([])
        out = self._run_command(agent, "qemu")
        self.assertTrue(any("Nutzung" in line for line in out))


class ModuleListTest(unittest.TestCase):
    def test_backends_tuple_matches_cli_choices(self) -> None:
        self.assertEqual(BACKENDS, ("auto", "firejail", "docker", "off"))


if __name__ == "__main__":
    unittest.main()
