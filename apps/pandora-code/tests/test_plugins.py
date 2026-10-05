"""Tests für das Plugin-System (extensions/plugins.py): Installation aus echten lokalen Git-Repos und
lokalen Pfaden (kein Netzwerk nötig), Hot Reload über Task/Agenten/Hooks/MCP/Commands, Marketplace-Auflösung
nach dem .claude-plugin-Format, und die Sicherheitsabfrage vor jeder Installation."""
from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from pandora_code.extensions.plugins import (
    NAME_RE, _looks_like_local_path, _unwrap_hook_config, fetch_source, install_plugin, list_plugins,
    plugins_root, reload_plugin, remove_plugin, resolve_components, resolve_marketplace_entry,
)
from pandora_code.tools import ToolError, ToolContext
from tests.test_extensions import ExtCase
from tests.test_pandora_code import text_chunks, tool_chunks


def make_demo_plugin(root: Path, *, name: str = "demo", with_python: bool = False) -> Path:
    plugin_dir = root / name
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "description": f"{name}-Testplugin", "version": "1.0.0"}), encoding="utf-8")
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "commands" / "greet.md").write_text(
        "---\ndescription: Grüßt\n---\nHallo $ARGUMENTS, von Plugin " + name + "!", encoding="utf-8")
    (plugin_dir / "agents").mkdir()
    (plugin_dir / "agents" / "helper.md").write_text(
        f"---\nname: {name}-helper\ndescription: Hilfsagent aus dem Plugin {name}\n---\n"
        "Du hilfst bei Testaufgaben.\n", encoding="utf-8")
    (plugin_dir / "hooks").mkdir()
    (plugin_dir / "hooks" / "hooks.json").write_text(
        json.dumps({"Stop": [{"hooks": [{"type": "command", "command": "echo plugin-stop-hook"}]}]}),
        encoding="utf-8")
    (plugin_dir / "skills" / "demo-skill").mkdir(parents=True)
    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\n---\nTu etwas.",
                                                                    encoding="utf-8")
    if with_python:
        (plugin_dir / "pandora_plugin.py").write_text(textwrap.dedent('''
            def install(agent, settings):
                agent.plugin_marker = "python-plugin-loaded"
        '''), encoding="utf-8")
    return plugin_dir


def make_git_repo(tmp_path: Path, plugin_dir: Path) -> Path:
    """Baut ein ECHTES lokales Git-Repo (kein Netzwerk nötig) aus einem Plugin-Ordner, als Quelle für
    'git clone'-Tests."""
    repo = tmp_path / "repo.git_src"
    import shutil
    shutil.copytree(plugin_dir, repo)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.de", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t.de"}
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, env={**__import__("os").environ, **env})
    return repo


class PureHelperTests(unittest.TestCase):
    def test_looks_like_local_path(self) -> None:
        for value in ("/abs/path", "./rel", "../rel", "~/x", "C:\\x"):
            self.assertTrue(_looks_like_local_path(value), value)
        # 'file://' ist ein explizites Git-Fernarchiv-Schema (git klont es nativ) und bekommt deshalb
        # bewusst GIT-Semantik (eigenständige Kopie), keinen Live-Symlink - siehe fetch_source()-Docstring.
        for value in ("https://github.com/a/b", "git@github.com:a/b.git", "file:///abs/plugin.git"):
            self.assertFalse(_looks_like_local_path(value), value)

    def test_name_regex_rejects_path_traversal(self) -> None:
        self.assertIsNone(NAME_RE.match("../../etc"))
        self.assertIsNone(NAME_RE.match("a/b"))
        self.assertTrue(NAME_RE.match("my-plugin_2"))

    def test_unwrap_hook_config_direct(self) -> None:
        class Direct:
            def __init__(self):
                self.config = {"Stop": []}
        direct = Direct()
        self.assertIs(_unwrap_hook_config(direct), direct.config)

    def test_unwrap_hook_config_through_wrapper_chain(self) -> None:
        class Inner:
            def __init__(self):
                self.config = {"Stop": []}

        class Wrapper:
            def __init__(self, inner):
                self.inner = inner

        inner = Inner()
        wrapper = Wrapper(inner)
        self.assertIs(_unwrap_hook_config(wrapper), inner.config)

    def test_unwrap_hook_config_none_without_hooks(self) -> None:
        self.assertIsNone(_unwrap_hook_config(None))


class ResolveComponentsTests(ExtCase):
    def test_defaults_used_when_no_manifest_overrides(self) -> None:
        plugin_dir = make_demo_plugin(self.cwd)
        manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        comp = resolve_components(plugin_dir, manifest)
        self.assertEqual(comp.commands, [plugin_dir / "commands"])
        self.assertEqual(comp.agents, [plugin_dir / "agents"])
        self.assertEqual(comp.hooks_file, plugin_dir / "hooks" / "hooks.json")
        self.assertIsNone(comp.mcp_file)  # kein .mcp.json im Demo-Plugin
        self.assertIsNone(comp.python_plugin)  # kein pandora_plugin.py im Demo-Plugin

    def test_manifest_overrides_are_honoured(self) -> None:
        plugin_dir = self.cwd / "custom"
        (plugin_dir / "weird").mkdir(parents=True)
        (plugin_dir / "weird" / "x.md").write_text("x", encoding="utf-8")
        manifest = {"name": "custom", "commands": "./weird/"}
        comp = resolve_components(plugin_dir, manifest)
        self.assertEqual(comp.commands, [plugin_dir / "weird"])

    def test_missing_directories_are_simply_absent(self) -> None:
        plugin_dir = self.cwd / "empty"
        plugin_dir.mkdir()
        comp = resolve_components(plugin_dir, {"name": "empty"})
        self.assertEqual(comp.commands, [])
        self.assertEqual(comp.agents, [])
        self.assertIsNone(comp.hooks_file)
        self.assertIsNone(comp.mcp_file)
        self.assertIsNone(comp.python_plugin)


class FetchSourceTests(ExtCase):
    def test_local_path_is_symlinked_not_copied(self) -> None:
        plugin_dir = make_demo_plugin(self.cwd)
        dest = self.cwd / "dest"
        kind = fetch_source(str(plugin_dir), dest)
        self.assertEqual(kind, "lokal (verknüpft)")
        self.assertTrue(dest.is_symlink())
        # Live-Bearbeitung der Quelle muss sofort im Ziel sichtbar sein (wichtig für /plugin reload beim
        # lokalen Entwickeln eines Plugins).
        (plugin_dir / "commands" / "neu.md").write_text("Neuer Befehl", encoding="utf-8")
        self.assertTrue((dest / "commands" / "neu.md").is_file())

    def test_missing_local_path_raises(self) -> None:
        with self.assertRaises(ToolError):
            fetch_source(str(self.cwd / "nicht-vorhanden"), self.cwd / "dest")

    def test_git_clone_from_real_local_repo(self) -> None:
        plugin_dir = make_demo_plugin(self.cwd, name="gitdemo")
        repo = make_git_repo(self.cwd, plugin_dir)
        dest = self.cwd / "cloned"
        kind = fetch_source(f"file://{repo}", dest)
        self.assertEqual(kind, "git")
        self.assertTrue((dest / ".claude-plugin" / "plugin.json").is_file())
        self.assertTrue((dest / ".git").is_dir())  # tatsächlich ein git-Klon, kein Kopieren

    def test_missing_git_binary_is_reported_clearly(self) -> None:
        with mock.patch("pandora_code.extensions.plugins.shutil.which", return_value=None):
            with self.assertRaises(ToolError) as ctx:
                fetch_source("https://example.com/repo.git", self.cwd / "dest")
        self.assertIn("git", str(ctx.exception))

    def test_git_clone_failure_is_reported_not_raised_as_subprocess_error(self) -> None:
        with self.assertRaises(ToolError):
            fetch_source(f"file://{self.cwd}/does-not-exist.git", self.cwd / "dest")


class MarketplaceTests(ExtCase):
    def test_entry_with_source_subdirectory(self) -> None:
        repo = self.cwd / "marketplace"
        make_demo_plugin(repo / "plugins", name="sub")
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"plugins": [{"name": "sub", "source": "./plugins/sub"}]}), encoding="utf-8")
        resolved = resolve_marketplace_entry(repo, "sub")
        self.assertEqual(resolved, (repo / "plugins" / "sub").resolve())

    def test_self_referential_entry_like_ecc_at_ecc(self) -> None:
        repo = self.cwd / "ecc_repo"
        make_demo_plugin(repo.parent, name=repo.name)  # Inhalt direkt im Repo-Root
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"plugins": [{"name": "ecc"}]}), encoding="utf-8")
        resolved = resolve_marketplace_entry(repo, "ecc")
        self.assertEqual(resolved, repo)

    def test_unknown_plugin_name_raises(self) -> None:
        repo = self.cwd / "mp"
        (repo / ".claude-plugin").mkdir(parents=True)
        (repo / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")
        with self.assertRaises(ToolError):
            resolve_marketplace_entry(repo, "nope")

    def test_missing_marketplace_file_raises(self) -> None:
        repo = self.cwd / "nomarket"
        repo.mkdir()
        with self.assertRaises(ToolError):
            resolve_marketplace_entry(repo, "x")


class InstallEndToEndTests(ExtCase):
    """Über einen echten Agenten (FakeOllama) – prüft, dass Installation sofort wirkt (Hot Reload), ohne
    Neustart: neuer Slash-Befehl, neuer Subagent über das Task-Werkzeug, gemergte Hooks."""

    def test_install_declines_without_confirmation(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([], ask=lambda _: "nein")
        with self.assertRaises(ToolError):
            install_plugin(agent, str(source_dir), confirm=lambda p: False)
        self.assertEqual(list_plugins(), [])

    def test_install_local_plugin_registers_command_immediately(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        self.assertIn("greet", agent.commands)
        handler, _ = agent.commands["greet"]
        self.assertEqual(handler("Aki", agent, agent.ui), "Hallo Aki, von Plugin demo!")

    def test_install_merges_hooks_into_live_hook_runner(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        before = len((_unwrap_hook_config(agent.hooks) or {}).get("Stop", []))
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        after = _unwrap_hook_config(agent.hooks)["Stop"]
        self.assertEqual(len(after), before + 1)
        self.assertIn("plugin-stop-hook", json.dumps(after))

    def test_installed_agent_is_usable_via_task_tool_without_restart(self) -> None:
        # Die Tool-Beschreibung des Task-Werkzeugs listet nur die beim Start bekannten Agenten (als reiner
        # Hinweistext, einmalig gebaut) - die eigentliche VALIDIERUNG in task() liest aber bei jedem Aufruf
        # frisch von der Platte (siehe subagents.current_defs()), erkennt 'demo-helper' hier also trotzdem,
        # obwohl das Plugin NACH dem Start des Agenten installiert wurde. Genau das ist der Hot-Reload-Test.
        source_dir = make_demo_plugin(self.cwd)
        script = [tool_chunks("Task", {"prompt": "hilf mir", "subagent_type": "demo-helper",
                                       "description": "x"}), text_chunks("Bericht: erledigt"),
                  text_chunks("fertig")]
        agent, fake = self.make_agent(script)
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        agent.run_turn("los")
        tool_result_message = fake.requests[-1]["messages"][-1]["content"]
        self.assertNotIn("Unbekannter Subagent", tool_result_message)
        self.assertIn("Bericht: erledigt", tool_result_message)
        self.assertEqual(agent.messages[-1]["content"], "fertig")

    def test_list_plugins_reports_components(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        entries = list_plugins()
        self.assertEqual(len(entries), 1)
        name, comp, manifest = entries[0]
        self.assertEqual(name, "demo")
        self.assertTrue(comp.commands and comp.agents and comp.hooks_file and comp.skills)

    def test_reload_reapplies_after_local_edit(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        (source_dir / "commands" / "greet.md").write_text("Geändert: $ARGUMENTS", encoding="utf-8")
        reload_plugin(agent, "demo", confirm=lambda p: True)
        handler, _ = agent.commands["greet"]
        self.assertEqual(handler("x", agent, agent.ui), "Geändert: x")

    def test_remove_plugin_deletes_directory(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        remove_plugin("demo")
        self.assertEqual(list_plugins(), [])

    def test_remove_nonexistent_plugin_raises(self) -> None:
        with self.assertRaises(ToolError):
            remove_plugin("nichtinstalliert")

    def test_python_plugin_requires_separate_confirmation(self) -> None:
        source_dir = make_demo_plugin(self.cwd, with_python=True)
        agent, _ = self.make_agent([])
        prompts: list[str] = []

        def confirm(p: str) -> bool:
            prompts.append(p)
            return "Python-Code" not in p  # alles außer dem Python-Schritt bestätigen

        install_plugin(agent, str(source_dir), confirm=confirm)
        self.assertFalse(hasattr(agent, "plugin_marker"))  # abgelehnt -> nicht geladen
        self.assertIn("greet", agent.commands)  # Rest (Commands/Hooks/Agenten) trotzdem aktiv
        self.assertGreaterEqual(len(prompts), 2)

    def test_python_plugin_loads_when_confirmed(self) -> None:
        source_dir = make_demo_plugin(self.cwd, with_python=True)
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        self.assertEqual(agent.plugin_marker, "python-plugin-loaded")

    def test_invalid_manifest_name_is_rejected(self) -> None:
        source_dir = self.cwd / "bad"
        (source_dir / ".claude-plugin").mkdir(parents=True)
        (source_dir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "../escape"}), encoding="utf-8")
        agent, _ = self.make_agent([])
        with self.assertRaises(ToolError):
            install_plugin(agent, str(source_dir), confirm=lambda p: True)


class PluginCommandTests(ExtCase):
    def _run(self, agent, arg: str) -> list[str]:
        out: list[str] = []
        agent.ui.info = out.append
        agent.ui.error = out.append
        handler, _ = agent.commands["plugin"]
        handler(arg, agent, agent.ui)
        return out

    def test_list_with_no_plugins(self) -> None:
        agent, _ = self.make_agent([])
        out = self._run(agent, "list")
        self.assertTrue(any("Keine Plugins" in line for line in out))

    def test_install_via_command_then_list_shows_it(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([], ask=lambda _: "ja")
        self._run(agent, f"install {source_dir}")
        out = self._run(agent, "list")
        self.assertTrue(any("demo" in line for line in out))

    def test_install_without_argument_reports_usage(self) -> None:
        agent, _ = self.make_agent([])
        out = self._run(agent, "install")
        self.assertTrue(any("Nutzung" in line for line in out))

    def test_unknown_action_reports_usage(self) -> None:
        agent, _ = self.make_agent([])
        out = self._run(agent, "foo")
        self.assertTrue(any("Nutzung" in line for line in out))

    def test_remove_via_command(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([], ask=lambda _: "ja")
        self._run(agent, f"install {source_dir}")
        self._run(agent, "remove demo")
        out = self._run(agent, "list")
        self.assertTrue(any("Keine Plugins" in line for line in out))


if __name__ == "__main__":
    unittest.main()
