"""Tests für Punkt 7: Modell-Registry (Hot Reload) und automatischer Fallback für Hauptagent/Subagenten."""
from __future__ import annotations

import unittest
from unittest import mock

from pandora_code.agent import Agent
from pandora_code.config import Settings
from pandora_code.extensions import install_all
from pandora_code.extensions.subagents import resolve_subagent_model
from pandora_code.llm.models import ModelRegistry, family_of, parse_model
from pandora_code.ollama_client import OllamaClient
from pandora_code.permissions import Permissions
from pandora_code.ui import UI
from tests.test_extensions import ExtCase
from tests.test_pandora_code import FakeOllama, text_chunks, tool_chunks

# Genau die Modelle, die Aki laut Anfrage installiert hat.
AKI_MODELS = [
    "qwen2.5-coder:14b", "qwen2.5-coder:7b", "phi3:mini", "gemma2:2b",
    "llama3.2:3b", "llama3.2:1b", "qwen2.5:3b",
]


class FakeClient:
    def __init__(self, models: list[str]) -> None:
        self.models = models

    def list_models(self) -> list[str]:
        return list(self.models)


def error_chunk(message: str) -> list[dict]:
    return [{"error": message}]


class ParsingTests(unittest.TestCase):
    def test_family_of_strips_tag_and_namespace(self) -> None:
        self.assertEqual(family_of("qwen2.5-coder:14b"), ("qwen2.5-coder", "14b"))
        self.assertEqual(family_of("hf.co/someuser/llama3.2"), ("llama3.2", "latest"))

    def test_parse_model_detects_size_and_tools(self) -> None:
        info = parse_model("qwen2.5-coder:14b")
        self.assertEqual(info.size_b, 14.0)
        self.assertTrue(info.tools)
        self.assertTrue(info.coder)
        self.assertFalse(parse_model("phi3:mini").tools)  # phi3 unterstützt (noch) keine Tool-Calls
        self.assertEqual(parse_model("gemma2:2b").size_b, 2.0)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ModelRegistry(FakeClient(AKI_MODELS))

    def test_role_assignment_matches_akis_models(self) -> None:
        assign = self.registry.role_assignment()
        self.assertEqual(assign["strong"], "qwen2.5-coder:14b")
        self.assertEqual(assign["general"], "qwen2.5-coder:14b")
        self.assertEqual(assign["fast"], "qwen2.5-coder:7b")
        self.assertEqual(assign["tiny"], "llama3.2:1b")

    def test_resolve_falls_back_when_model_missing(self) -> None:
        res = self.registry.resolve("deepseek-r1:32b", role="strong")
        self.assertTrue(res.switched)
        self.assertEqual(res.model, "qwen2.5-coder:14b")
        self.assertIn("nicht installiert", res.reason)

    def test_resolve_falls_back_when_model_has_no_tools(self) -> None:
        res = self.registry.resolve("phi3:mini")
        self.assertTrue(res.switched)
        self.assertTrue(self.registry.supports_tools(res.model))
        self.assertIn("keine Werkzeuge", res.reason)

    def test_resolve_keeps_installed_model_unchanged(self) -> None:
        res = self.registry.resolve("qwen2.5-coder:7b")
        self.assertEqual(res, type(res)("qwen2.5-coder:7b", False, ""))

    def test_resolve_matches_family_without_tag(self) -> None:
        res = self.registry.resolve("qwen2.5-coder")
        self.assertEqual(res.model, "qwen2.5-coder:14b")  # größtes Modell der Familie

    def test_role_alias_in_wanted_field(self) -> None:
        # Agent-Dateien dürfen "model: fast" statt eines konkreten Namens verwenden.
        self.assertEqual(self.registry.resolve("fast").model, "qwen2.5-coder:7b")

    def test_settings_role_override_is_respected(self) -> None:
        registry = ModelRegistry(FakeClient(AKI_MODELS), roles={"fast": "qwen2.5:3b"})
        self.assertEqual(registry.role_assignment()["fast"], "qwen2.5:3b")

    def test_no_models_installed_reports_unresolvable(self) -> None:
        registry = ModelRegistry(FakeClient([]))
        res = registry.resolve("qwen2.5-coder:7b")
        self.assertFalse(res.model)

    def test_hot_reload_picks_up_newly_pulled_model(self) -> None:
        client = FakeClient(["llama3.2:1b"])
        registry = ModelRegistry(client, ttl=0)
        self.assertIsNone(registry.match("qwen2.5-coder:7b"))
        client.models.append("qwen2.5-coder:7b")  # z. B. während Pandora läuft: `ollama pull ...`
        self.assertEqual(registry.match("qwen2.5-coder:7b"), "qwen2.5-coder:7b")


class AgentHotSwapTests(ExtCase):
    def make(self, script, model="qwen2.5-coder:7b", roles=None):
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        client = OllamaClient(fake.host)
        registry = ModelRegistry(client, roles=roles or {})
        registry.seed(AKI_MODELS)
        agent = Agent(client, model, self.ctx, Permissions("yolo"), UI(), registry=registry)
        self.addCleanup(agent.close)
        return agent, fake, registry

    def test_missing_model_switches_and_completes_turn(self) -> None:
        script = [error_chunk("model \"nicht-da:99b\" not found, try pulling it first"), text_chunks("hallo zurück")]
        agent, fake, _ = self.make(script, model="nicht-da:99b")
        agent.run_turn("hi")
        self.assertEqual(fake.requests[0]["model"], "nicht-da:99b")
        self.assertEqual(fake.requests[1]["model"], "qwen2.5-coder:14b")  # bestes verfügbares Modell (general)
        self.assertEqual(agent.model, "qwen2.5-coder:14b")
        self.assertIn("Erledigt" if False else "hallo zurück", agent.messages[-1]["content"])

    def test_no_tools_error_marks_model_and_switches(self) -> None:
        script = [error_chunk("phi3:mini does not support tools"), text_chunks("ok")]
        agent, fake, registry = self.make(script, model="phi3:mini")
        agent.run_turn("hi")
        self.assertIn("phi3:mini", registry.no_tools)
        self.assertEqual(agent.model, "qwen2.5-coder:14b")

    def test_without_registry_error_propagates_unchanged(self) -> None:
        script = [error_chunk("model \"weg\" not found, try pulling it first")]
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        agent = Agent(OllamaClient(fake.host), "weg", self.ctx, Permissions("yolo"), UI())  # kein registry=
        self.addCleanup(agent.close)
        with self.assertRaises(Exception):
            agent.run_turn("hi")

    def test_unrelated_server_error_is_not_treated_as_missing_model(self) -> None:
        script = [error_chunk("internal server error")]
        agent, fake, _ = self.make(script, model="qwen2.5-coder:7b")
        with self.assertRaises(Exception):
            agent.run_turn("hi")  # kein Modellproblem -> kein automatischer Ersatz, Fehler geht durch


class SubagentModelFallbackTests(ExtCase):
    def test_task_uses_registry_when_agent_file_model_is_missing(self) -> None:
        folder = self.cwd / ".pandora" / "agents"
        folder.mkdir(parents=True)
        (folder / "heavy.md").write_text(
            "---\nname: heavy\ndescription: Schwere Analyse\nmodel: deepseek-r1:32b\n---\nSei gründlich.\n",
            encoding="utf-8",
        )
        script = [
            tool_chunks("Task", {"prompt": "analysiere", "subagent_type": "heavy", "description": "x"}),
            text_chunks("Bericht: fertig"),
            text_chunks("ok"),
        ]
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        client = OllamaClient(fake.host)
        registry = ModelRegistry(client)
        registry.seed(AKI_MODELS)
        out_perms = Permissions("yolo", ask=lambda _: "n", show=lambda _: None)
        agent = Agent(client, "qwen2.5-coder:14b", self.ctx, out_perms, UI(), registry=registry)
        self.addCleanup(agent.close)
        install_all(agent, Settings(), frozenset())
        agent.run_turn("los")
        self.assertEqual(fake.requests[1]["model"], "qwen2.5-coder:14b")  # Ersatz statt 'deepseek-r1:32b'

    def test_resolve_subagent_model_without_registry_keeps_requested(self) -> None:
        class Dummy:
            registry = None
            model = "qwen2.5-coder:7b"
            ui = None

        class Def:
            model = "irgendwas:1b"
            name = "x"

        self.assertEqual(resolve_subagent_model(Dummy(), Def()), "irgendwas:1b")


if __name__ == "__main__":
    unittest.main()
