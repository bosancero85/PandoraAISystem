"""Tests für das Skill-System (pandora_code/skills.py, extensions/skills.py) – deckt die realen Quellen ab,
die beim Recherchieren der 7 Repos (ECC, Anthropic-Cybersecurity-Skills, scientific-agent-skills,
Agent-Reach, browser-use) gefunden wurden: das agentskills.io-SKILL.md-Format, die werkzeugübergreifende
~/.agents/skills/-Konvention (von 'npx skills add', 'agent-reach install', 'browser-use skill install'
selbst befüllt), und Skills aus installierten Plugins."""
from __future__ import annotations

from pathlib import Path

from pandora_code.extensions.plugins import install_plugin
from pandora_code.skills import discover_skills, load_skill, parse_skill_file, search_skills
from tests.test_extensions import ExtCase
from tests.test_plugins import make_demo_plugin


def write_skill(root: Path, name: str, description: str, body: str = "Tu etwas Nützliches.",
                extra_frontmatter: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra_frontmatter}---\n{body}\n", encoding="utf-8")
    return skill_dir / "SKILL.md"


class ParseSkillFileTests(ExtCase):
    def test_parses_name_and_description(self) -> None:
        path = write_skill(self.cwd, "pdf-filling", "Fills PDF forms programmatically")
        result = parse_skill_file(path)
        self.assertEqual(result, ("pdf-filling", "Fills PDF forms programmatically"))

    def test_falls_back_to_folder_name_without_name_field(self) -> None:
        skill_dir = self.cwd / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: x\n---\nkörper", encoding="utf-8")
        name, _ = parse_skill_file(skill_dir / "SKILL.md")
        self.assertEqual(name, "my-skill")

    def test_handles_agentskills_io_style_extra_fields(self) -> None:
        # Reales Format aus Anthropic-Cybersecurity-Skills / K-Dense scientific-agent-skills.
        path = write_skill(self.cwd, "memory-forensics", "Analyzes memory dumps with Volatility3",
                           extra_frontmatter="domain: cybersecurity\nsubdomain: forensics\n"
                                              "tags: [volatility, memory, dfir]\n")
        result = parse_skill_file(path)
        self.assertEqual(result, ("memory-forensics", "Analyzes memory dumps with Volatility3"))

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(parse_skill_file(self.cwd / "nope" / "SKILL.md"))

    def test_malformed_frontmatter_returns_none(self) -> None:
        skill_dir = self.cwd / "broken"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("kein --- hier", encoding="utf-8")
        self.assertIsNone(parse_skill_file(skill_dir / "SKILL.md"))


class DiscoverySourceTests(ExtCase):
    """Jede der vier Standalone-Quellen einzeln, wie im Modul-Docstring beschrieben."""

    def test_user_level_pandora_skills_dir(self) -> None:
        write_skill(self.home / "skills", "eigener-skill", "Von Hand angelegt")
        skills = discover_skills(self.cwd)
        self.assertIn("eigener-skill", skills)
        self.assertEqual(skills["eigener-skill"].source, str(self.home / "skills"))

    def test_project_level_pandora_skills_dir(self) -> None:
        write_skill(self.cwd / ".pandora" / "skills", "projekt-skill", "Nur für dieses Projekt")
        self.assertIn("projekt-skill", discover_skills(self.cwd))

    def test_cross_tool_user_level_agents_skills_dir(self) -> None:
        # Genau der Pfad, den 'agent-reach install' und 'browser-use skill install' laut ihrer eigenen
        # Dokumentation selbst befüllen. Path.home() wird auf ein von self.cwd verschiedenes Verzeichnis
        # gemockt, damit dieser Test sich eindeutig vom projektlokalen .agents/skills unterscheidet.
        import unittest.mock as mock
        fake_home = self.cwd / "_fake_user_home"
        with mock.patch("pandora_code.skills.Path.home", return_value=fake_home):
            write_skill(fake_home / ".agents" / "skills", "agent-reach", "Reach external platforms")
            skills = discover_skills(self.cwd)
        self.assertIn("agent-reach", skills)
        self.assertNotIn(str(self.cwd / ".agents" / "skills"), skills["agent-reach"].source)

    def test_project_level_agents_skills_dir(self) -> None:
        write_skill(self.cwd / ".agents" / "skills", "projekt-tool-skill", "Projektlokales Fremd-Tool")
        self.assertIn("projekt-tool-skill", discover_skills(self.cwd))

    def test_discovery_has_no_cache_edits_are_picked_up_immediately(self) -> None:
        write_skill(self.home / "skills", "a", "erste Version")
        first = discover_skills(self.cwd)["a"].description
        write_skill(self.home / "skills", "a", "geänderte Version")
        second = discover_skills(self.cwd)["a"].description
        self.assertEqual(first, "erste Version")
        self.assertEqual(second, "geänderte Version")

    def test_non_skill_files_in_skills_dir_are_ignored(self) -> None:
        skills_dir = self.home / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "README.md").write_text("kein Skill", encoding="utf-8")
        self.assertEqual(discover_skills(self.cwd), {})

    def test_empty_when_no_source_exists(self) -> None:
        self.assertEqual(discover_skills(self.cwd), {})


class PluginSkillIntegrationTests(ExtCase):
    """Skills aus einem per /plugin installierten Repo (ECC, Anthropic-Cybersecurity-Skills,
    scientific-agent-skills folgen alle demselben skills/*/SKILL.md-Muster)."""

    def test_installed_plugin_skills_are_discovered(self) -> None:
        source_dir = make_demo_plugin(self.cwd)  # enthält bereits skills/demo-skill/SKILL.md
        agent, _ = self.make_agent([])
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        skills = discover_skills(self.cwd)
        self.assertIn("demo-skill", skills)
        self.assertIn("plugins", skills["demo-skill"].source)

    def test_plugin_skill_available_without_restart(self) -> None:
        source_dir = make_demo_plugin(self.cwd)
        agent, _ = self.make_agent([])
        before = discover_skills(self.cwd)
        self.assertNotIn("demo-skill", before)
        install_plugin(agent, str(source_dir), confirm=lambda p: True)
        after = discover_skills(self.cwd)
        self.assertIn("demo-skill", after)  # Hot Reload: dieselbe laufende Sitzung, kein Neustart


class SearchAndLoadTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        write_skill(self.home / "skills", "pdf-filling", "Fill and flatten PDF forms programmatically",
                   body="1. Lies das Formular.\n2. Fülle die Felder.\n3. Flatte das PDF.")
        write_skill(self.home / "skills", "memory-forensics", "Analyze memory dumps with Volatility3 "
                                                               "for digital forensics investigations")
        write_skill(self.home / "skills", "video-download", "Download videos via yt-dlp from many platforms")

    def test_search_ranks_relevant_skill_first(self) -> None:
        hits = search_skills(self.cwd, "PDF Formular ausfüllen")
        self.assertTrue(hits)
        self.assertEqual(hits[0].name, "pdf-filling")

    def test_search_without_query_returns_everything(self) -> None:
        hits = search_skills(self.cwd, "")
        self.assertEqual({h.name for h in hits}, {"pdf-filling", "memory-forensics", "video-download"})

    def test_search_respects_limit(self) -> None:
        hits = search_skills(self.cwd, "", limit=2)
        self.assertEqual(len(hits), 2)

    def test_search_no_match_returns_empty(self) -> None:
        self.assertEqual(search_skills(self.cwd, "quantencomputer stricken"), [])

    def test_load_returns_full_body(self) -> None:
        body = load_skill(self.cwd, "pdf-filling")
        self.assertIn("Flatte das PDF", body)

    def test_load_is_case_insensitive(self) -> None:
        self.assertEqual(load_skill(self.cwd, "PDF-Filling"), load_skill(self.cwd, "pdf-filling"))

    def test_load_unknown_skill_returns_none(self) -> None:
        self.assertIsNone(load_skill(self.cwd, "gibt-es-nicht"))


class SkillToolsTests(ExtCase):
    def setUp(self) -> None:
        super().setUp()
        write_skill(self.home / "skills", "pdf-filling", "Fill PDF forms", body="Anleitung hier.")

    def test_skill_search_tool(self) -> None:
        agent, _ = self.make_agent([])
        result = agent.tools["SkillSearch"].run(agent.ctx, {"query": "PDF"})
        self.assertIn("pdf-filling", result)

    def test_skill_search_requires_query(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(Exception):
            agent.tools["SkillSearch"].run(agent.ctx, {})

    def test_skill_load_tool_returns_body(self) -> None:
        agent, _ = self.make_agent([])
        result = agent.tools["SkillLoad"].run(agent.ctx, {"name": "pdf-filling"})
        self.assertIn("Anleitung hier.", result)

    def test_skill_load_tool_unknown_name_raises(self) -> None:
        agent, _ = self.make_agent([])
        with self.assertRaises(Exception):
            agent.tools["SkillLoad"].run(agent.ctx, {"name": "unbekannt"})


class SkillsCommandTests(ExtCase):
    def _out(self, agent, arg: str) -> list[str]:
        out: list[str] = []
        agent.ui.info = out.append
        handler, _ = agent.commands["skills"]
        handler(arg, agent, agent.ui)
        return out

    def test_no_skills_reports_searched_locations(self) -> None:
        agent, _ = self.make_agent([])
        out = self._out(agent, "")
        self.assertTrue(any(".agents/skills" in line for line in out))

    def test_lists_count_by_source(self) -> None:
        write_skill(self.home / "skills", "a", "x")
        write_skill(self.home / "skills", "b", "y")
        agent, _ = self.make_agent([])
        out = self._out(agent, "")
        self.assertTrue(any("2 Skill(s)" in line for line in out))

    def test_search_argument_filters(self) -> None:
        write_skill(self.home / "skills", "pdf-filling", "Fill PDF forms")
        write_skill(self.home / "skills", "video-download", "Download videos")
        agent, _ = self.make_agent([])
        out = self._out(agent, "PDF")
        joined = "\n".join(out)
        self.assertIn("pdf-filling", joined)
        self.assertNotIn("video-download", joined)


if __name__ == "__main__":
    import unittest
    unittest.main()
