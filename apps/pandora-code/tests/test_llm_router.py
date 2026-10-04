"""Tests für Punkt 3: Smart Model Router – automatische fast/general/strong-Wahl nach Aufgabenkomplexität."""
from __future__ import annotations

import unittest

from pandora_code.agent import Agent
from pandora_code.extensions.subagents import BUILTIN, resolve_subagent_model
from pandora_code.llm.models import ModelRegistry
from pandora_code.llm.router import TaskRouter
from pandora_code.permissions import Permissions
from pandora_code.ui import UI
from tests.test_extensions import ExtCase
from tests.test_pandora_code import FakeOllama, text_chunks, tool_chunks

AKI_MODELS = [
    "qwen2.5-coder:14b", "qwen2.5-coder:7b", "phi3:mini", "gemma2:2b",
    "llama3.2:3b", "llama3.2:1b", "qwen2.5:3b",
]


class ClassifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = TaskRouter()

    def test_short_command_is_fast(self) -> None:
        self.assertEqual(self.router.classify("suche alle TODO Kommentare").role, "fast")
        self.assertEqual(self.router.classify("lösche die Datei tmp.log").role, "fast")

    def test_architecture_keyword_is_strong(self) -> None:
        self.assertEqual(self.router.classify("Bitte überarbeite die Architektur des Moduls grundlegend").role, "strong")
        self.assertEqual(self.router.classify("Finde den Grund für den Deadlock beim Debuggen").role, "strong")

    def test_plain_question_is_general(self) -> None:
        self.assertEqual(self.router.classify("Wie spät ist es gerade in Berlin?").role, "general")

    def test_long_prompt_escalates_to_strong(self) -> None:
        self.assertEqual(self.router.classify("x " * 400).role, "strong")

    def test_repeated_failures_escalate_regardless_of_text(self) -> None:
        self.router.recent_failures = 2
        self.assertEqual(self.router.classify("liste dateien").role, "strong")

    def test_disabled_router_always_general(self) -> None:
        self.router.enabled = False
        self.assertEqual(self.router.classify("überarbeite die Architektur").role, "general")


class AgentRoutingTests(ExtCase):
    def make(self, script, prompt_text, model="qwen2.5-coder:14b", enabled=True):
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        from pandora_code.ollama_client import OllamaClient
        client = OllamaClient(fake.host)
        registry = ModelRegistry(client)
        registry.seed(AKI_MODELS)
        router = TaskRouter(enabled=enabled)
        agent = Agent(client, model, self.ctx, Permissions("yolo"), UI(), registry=registry, router=router)
        self.addCleanup(agent.close)
        return agent, fake

    def test_fast_command_switches_down_to_fast_model(self) -> None:
        agent, fake = self.make([text_chunks("ok")], "suche alle TODOs im Projekt", model="qwen2.5-coder:14b")
        agent.run_turn("suche alle TODOs im Projekt")
        self.assertEqual(agent.model, "qwen2.5-coder:7b")
        self.assertEqual(fake.requests[0]["model"], "qwen2.5-coder:7b")

    def test_architecture_request_switches_up_to_strong_model(self) -> None:
        agent, fake = self.make([text_chunks("ok")], "x", model="qwen2.5-coder:7b")
        agent.run_turn("Überarbeite bitte die komplette Architektur dieses Moduls, es ist zu komplex geworden.")
        self.assertEqual(agent.model, "qwen2.5-coder:14b")

    def test_disabled_router_never_switches(self) -> None:
        agent, fake = self.make([text_chunks("ok")], "x", model="qwen2.5-coder:7b", enabled=False)
        agent.run_turn("Überarbeite bitte die komplette Architektur.")
        self.assertEqual(agent.model, "qwen2.5-coder:7b")

    def test_manual_model_pin_stops_router_until_reenabled(self) -> None:
        agent, fake = self.make([text_chunks("a"), text_chunks("b")], "x", model="qwen2.5-coder:7b")
        agent.model, agent.auto_route_pinned = "qwen2.5-coder:7b", True  # entspricht /model qwen2.5-coder:7b
        agent.run_turn("Überarbeite die Architektur gründlich, sehr komplex.")
        self.assertEqual(agent.model, "qwen2.5-coder:7b")  # Router hätte sonst auf 'strong' gewechselt
        agent.auto_route_pinned = False  # entspricht /router an
        agent.run_turn("Überarbeite die Architektur gründlich, sehr komplex.")
        self.assertEqual(agent.model, "qwen2.5-coder:14b")

    def test_consecutive_tool_failures_escalate_next_turn(self) -> None:
        script = [
            tool_chunks("Read", {"file_path": "nope.txt"}),
            tool_chunks("Read", {"file_path": "nope2.txt"}),
            text_chunks("beide Dateien fehlen"),
            text_chunks("verstanden"),
        ]
        agent, fake = self.make(script, "x", model="qwen2.5-coder:7b")
        agent.run_turn("lies nope.txt und nope2.txt")  # zwei Fehler in Folge (Datei existiert nicht)
        self.assertGreaterEqual(agent.consecutive_tool_failures, 2)
        agent.run_turn("was jetzt?")  # kurzer, unspezifischer Folgesatz -> nur die Fehlerquote begründet 'strong'
        self.assertEqual(agent.model, "qwen2.5-coder:14b")

    def test_no_registry_or_router_leaves_model_untouched(self) -> None:
        from pandora_code.ollama_client import OllamaClient
        fake = FakeOllama([text_chunks("ok")])
        self.addCleanup(fake.close)
        agent = Agent(OllamaClient(fake.host), "qwen2.5-coder:7b", self.ctx, Permissions("yolo"), UI())
        self.addCleanup(agent.close)
        agent.run_turn("Überarbeite die Architektur gründlich.")
        self.assertEqual(agent.model, "qwen2.5-coder:7b")


class SubagentRoutingTests(unittest.TestCase):
    class DummyUI:
        def info(self, *_a, **_k) -> None: ...

    def make_parent(self, router_role: str | None):
        class DummyRouter:
            def classify(self_, prompt):
                from pandora_code.llm.router import Signal
                return Signal(router_role or "general", "test")

        class Dummy:
            registry = ModelRegistry(type("C", (), {"list_models": lambda self: AKI_MODELS})())
            router = DummyRouter() if router_role is not None else None
            model = "qwen2.5-coder:14b"
            ui = SubagentRoutingTests.DummyUI()

        return Dummy()

    def test_explore_always_gets_fast_role_regardless_of_router(self) -> None:
        parent = self.make_parent(router_role="strong")  # Router würde 'strong' sagen ...
        model = resolve_subagent_model(parent, BUILTIN["explore"], "sehr komplexe Architekturfrage")
        self.assertEqual(model, "qwen2.5-coder:7b")  # ... explore bleibt trotzdem auf der schnellen Rolle

    def test_general_purpose_follows_router_classification(self) -> None:
        parent = self.make_parent(router_role="strong")
        model = resolve_subagent_model(parent, BUILTIN["general-purpose"], "irrelevant")
        self.assertEqual(model, "qwen2.5-coder:14b")

    def test_general_purpose_without_router_uses_parent_model(self) -> None:
        parent = self.make_parent(router_role=None)
        model = resolve_subagent_model(parent, BUILTIN["general-purpose"], "irrelevant")
        self.assertEqual(model, "qwen2.5-coder:14b")


if __name__ == "__main__":
    unittest.main()
