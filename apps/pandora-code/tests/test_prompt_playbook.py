"""Tests: editierbarer Prompt, Playbook-Vorlage, Startbefehl `pandora code`."""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from unittest import mock

from pandora_code import cli, prompts
from tests.test_extensions import ExtCase
from tests.test_pandora_code import FakeOllama, text_chunks

TEMPLATE_FILES = {"ablage.md", "fertige_definition.md", "interview.md", "playbook.md", "project.toml", "session_handoff.md"}


class PromptTests(ExtCase):
    def system(self, agent) -> str:
        return agent.system_prompt()

    def test_default_created_once_and_never_overwritten(self) -> None:
        path = prompts.ensure_default_prompt()
        self.assertEqual(path, self.home / "prompt.md")
        self.assertIn("Projekt verstanden.", path.read_text(encoding="utf-8"))
        path.write_text("meine Version", encoding="utf-8")
        prompts.ensure_default_prompt()
        self.assertEqual(path.read_text(encoding="utf-8"), "meine Version")

    def test_project_prompt_wins_over_user_prompt(self) -> None:
        self.home.mkdir()
        (self.home / "prompt.md").write_text("BENUTZER", encoding="utf-8")
        self.assertEqual(prompts.load_user_prompt(self.cwd), "BENUTZER")
        (self.cwd / ".pandora").mkdir()
        (self.cwd / ".pandora" / "prompt.md").write_text("PROJEKT", encoding="utf-8")
        self.assertEqual(prompts.load_user_prompt(self.cwd), "PROJEKT")

    def test_edits_apply_on_next_request_without_restart(self) -> None:
        self.home.mkdir()
        file = self.home / "prompt.md"
        file.write_text("VERSION EINS", encoding="utf-8")
        agent, fake = self.make_agent([text_chunks("a"), text_chunks("b")])
        agent.prompt_loader = lambda: prompts.load_user_prompt(self.cwd)
        agent.run_turn("x")
        file.write_text("VERSION ZWEI", encoding="utf-8")
        agent.run_turn("y")
        self.assertIn("VERSION EINS", fake.requests[0]["messages"][0]["content"])
        self.assertIn("VERSION ZWEI", fake.requests[1]["messages"][0]["content"])
        self.assertNotIn("VERSION EINS", fake.requests[1]["messages"][0]["content"])

    def test_subagents_do_not_get_the_user_prompt(self) -> None:
        from tests.test_pandora_code import tool_chunks

        self.home.mkdir()
        (self.home / "prompt.md").write_text("NUR FUER DEN HAUPTAGENTEN", encoding="utf-8")
        script = [tool_chunks("Task", {"prompt": "suche", "subagent_type": "explore"}), text_chunks("Bericht"), text_chunks("ok")]
        agent, fake = self.make_agent(script)
        agent.prompt_loader = lambda: prompts.load_user_prompt(self.cwd)
        agent.run_turn("los")
        self.assertIn("NUR FUER DEN HAUPTAGENTEN", fake.requests[0]["messages"][0]["content"])
        self.assertNotIn("NUR FUER DEN HAUPTAGENTEN", fake.requests[1]["messages"][0]["content"])  # Subagent
        self.assertIn("NUR FUER DEN HAUPTAGENTEN", fake.requests[2]["messages"][0]["content"])


class PlaybookTests(ExtCase):
    def test_template_has_exactly_the_six_files(self) -> None:
        self.assertEqual({p.name for p in prompts.TEMPLATE_DIR.iterdir()}, TEMPLATE_FILES)
        for name in TEMPLATE_FILES:
            self.assertTrue((prompts.TEMPLATE_DIR / name).read_text(encoding="utf-8").strip(), name)

    def test_install_creates_and_never_overwrites(self) -> None:
        created, skipped = prompts.install_playbook(self.cwd)
        self.assertEqual((set(created), skipped), (TEMPLATE_FILES, []))
        (self.cwd / "playbook" / "project.toml").write_text('name = "meins"', encoding="utf-8")
        created, skipped = prompts.install_playbook(self.cwd)
        self.assertEqual((created, len(skipped)), ([], 6))
        self.assertEqual((self.cwd / "playbook" / "project.toml").read_text(encoding="utf-8"), 'name = "meins"')

    def test_project_toml_is_valid_toml(self) -> None:
        if sys.version_info < (3, 11):
            self.skipTest("tomllib erst ab Python 3.11")
        import tomllib

        data = tomllib.loads((prompts.TEMPLATE_DIR / "project.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["status"], "start")

    def test_playbook_rules_reach_system_prompt_only_when_folder_exists(self) -> None:
        agent, _ = self.make_agent([])
        self.assertNotIn("Playbook (playbook/playbook.md)", agent.system_prompt())
        prompts.install_playbook(self.cwd)
        text = agent.system_prompt()
        self.assertIn("Playbook (playbook/playbook.md) – verbindlich", text)
        self.assertIn("fertige_definition.md", text)

    def test_playbook_command(self) -> None:
        agent, _ = self.make_agent([])
        ui = agent.ui
        cli.handle_command("/playbook", agent, mock.Mock(), ui)
        self.assertEqual({p.name for p in (self.cwd / "playbook").iterdir()}, TEMPLATE_FILES)
        cli.handle_command("/playbook", agent, mock.Mock(), ui)
        self.assertIn("6 vorhanden", agent.out.getvalue())


class StartCommandTests(ExtCase):
    def run_entry(self, entry, argv, fake) -> str:
        args = [*argv, "--host", fake.host, "--cwd", str(self.cwd), "-m", "qwen2.5-coder:7b", "-p"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["pandora", *args]), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as raised:
                entry()
        self.assertEqual(raised.exception.code, 0)
        return out.getvalue()

    def test_pandora_code_drops_the_word_code(self) -> None:
        fake = FakeOllama([text_chunks("hallo")])
        self.addCleanup(fake.close)
        self.run_entry(cli.pandora_entry, ["code", "sag hallo"], fake)
        self.assertEqual(fake.requests[0]["messages"][-1]["content"], "sag hallo")  # 'code' ist nicht Teil des Prompts

    def test_pandora_without_code_and_pandora_code_dash(self) -> None:
        for entry, argv in ((cli.pandora_entry, ["sag hallo"]), (cli.pandora_code_entry, ["sag hallo"])):
            fake = FakeOllama([text_chunks("hallo")])
            self.addCleanup(fake.close)
            self.run_entry(entry, argv, fake)
            self.assertEqual(fake.requests[0]["messages"][-1]["content"], "sag hallo")

    def test_first_start_creates_editable_prompt_and_uses_it(self) -> None:
        fake = FakeOllama([text_chunks("ok")])
        self.addCleanup(fake.close)
        self.run_entry(cli.pandora_entry, ["code", "hi"], fake)
        self.assertTrue((self.home / "prompt.md").is_file())
        self.assertIn("Projekt verstanden.", fake.requests[0]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
