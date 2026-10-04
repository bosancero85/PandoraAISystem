"""Tests für die Erweiterungen: Konfiguration/Vertrauen, Hooks, Plan-Modus, Bilder, Subagenten, MCP, CLI."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from pandora_code import cli
from pandora_code.agent import Agent
from pandora_code.config import Settings, load_settings
from pandora_code.extensions import MODULES, install_all
from pandora_code.extensions.hooks import HookRunner
from pandora_code.extensions.mcp import HttpTransport, McpServer
from pandora_code.images import ImageError, MAX_IMAGES, encode_image, extract_images
from pandora_code.ollama_client import OllamaClient
from pandora_code.permissions import MODES, Permissions
from pandora_code.ui import UI
from tests.test_pandora_code import FakeOllama, TempDirCase, text_chunks, tool_chunks

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 24


def py_command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


class ExtCase(TempDirCase):
    """Isoliert ~/.pandora in ein Temp-Verzeichnis, damit echte Benutzer-Einstellungen nie einfließen."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.cwd / "_home"
        patcher = mock.patch.dict(os.environ, {"PANDORA_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def script(self, name: str, body: str) -> Path:
        path = self.cwd / name
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def make_agent(self, script, mode="yolo", ask=None, settings=None, disabled=(), answers=None):
        fake = FakeOllama(script)
        self.addCleanup(fake.close)
        out = io.StringIO()
        perms = Permissions(mode, ask=ask or (lambda _: "n"), show=lambda _: None)
        agent = Agent(OllamaClient(fake.host), "qwen2.5-coder:7b", self.ctx, perms, UI(out))
        agent.out = out
        install_all(agent, settings or Settings(), frozenset(disabled))
        self.addCleanup(agent.close)
        return agent, fake


class ConfigTests(ExtCase):
    def write_project(self, hook_cmd: str = "echo hi") -> None:
        (self.cwd / ".pandora").mkdir(exist_ok=True)
        config = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": hook_cmd}]}]}}
        (self.cwd / ".pandora" / "settings.json").write_text(json.dumps(config), encoding="utf-8")

    def test_user_settings_need_no_trust(self) -> None:
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}))
        settings = load_settings(self.cwd, lambda *_: self.fail("keine Rückfrage für Benutzer-Einstellungen"))
        self.assertIn("Stop", settings.hooks)

    def test_project_config_needs_trust(self) -> None:
        self.write_project()
        asked: list[str] = []
        settings = load_settings(self.cwd, lambda cwd, description: asked.append(description) or False)
        self.assertEqual(settings.hooks, {})
        self.assertIn("echo hi", asked[0])
        self.assertTrue(any("ignoriert" in n for n in settings.notices))

    def test_trust_is_remembered_for_exact_file_state(self) -> None:
        self.write_project()
        self.assertIn("PreToolUse", load_settings(self.cwd, lambda *_: True).hooks)
        again = load_settings(self.cwd, lambda *_: self.fail("gleicher Stand darf nicht erneut fragen"))
        self.assertIn("PreToolUse", again.hooks)
        self.write_project("echo geaendert")  # Änderung => wieder fragen, Standard = kein Vertrauen
        asked: list[str] = []
        changed = load_settings(self.cwd, lambda cwd, description: asked.append(description) or False)
        self.assertEqual(changed.hooks, {})
        self.assertEqual(len(asked), 1)

    def test_mcp_json_is_claude_code_compatible(self) -> None:
        (self.cwd / ".mcp.json").write_text(json.dumps({"mcpServers": {"s": {"command": "npx", "args": ["-y", "x"]}}}))
        settings = load_settings(self.cwd, lambda *_: True)
        self.assertEqual(settings.mcp_servers["s"]["command"], "npx")

    def test_invalid_json_becomes_notice(self) -> None:
        self.home.mkdir()
        (self.home / "settings.json").write_text("{kaputt")
        self.assertTrue(load_settings(self.cwd, lambda *_: True).notices)


class PermissionModeTests(unittest.TestCase):
    def test_plan_mode_blocks_even_always(self) -> None:
        from pandora_code.tools import build_tools

        tools = build_tools()
        perms = Permissions("yolo", ask=lambda _: "j", show=lambda _: None)
        perms.always.add("Write")
        perms.set_mode("plan")
        self.assertFalse(perms.allowed(tools["Write"], ""))
        self.assertFalse(perms.allowed(tools["Bash"], ""))
        self.assertTrue(perms.allowed(tools["Read"], ""))
        self.assertIn("plan", MODES)

    def test_previous_mode_and_listeners(self) -> None:
        perms = Permissions("accept-edits")
        seen: list[str] = []
        perms.listeners.append(lambda: seen.append(perms.mode))
        perms.set_mode("plan")
        perms.set_mode("plan")  # gleicher Modus überschreibt previous nicht
        self.assertEqual(perms.previous, "accept-edits")
        self.assertEqual(seen, ["plan", "plan"])


class HookTests(ExtCase):
    def test_exit_code_2_blocks_and_json_decision_blocks(self) -> None:
        block = self.script("block.py", "import sys; print('verboten', file=sys.stderr); sys.exit(2)")
        decide = self.script("decide.py", "import json; print(json.dumps({'decision': 'block', 'reason': 'per JSON'}))")
        ok = self.script("ok.py", "print('nichts')")
        runner = HookRunner({"PreToolUse": [{"matcher": "Write", "hooks": [{"command": py_command(block)}]}]}, self.cwd)
        self.assertEqual(runner.pre_tool("Write", {}), "verboten")
        self.assertIsNone(runner.pre_tool("Read", {}))  # Matcher greift nur für Write
        runner = HookRunner({"PreToolUse": [{"hooks": [{"command": py_command(decide)}]}]}, self.cwd)
        self.assertEqual(runner.pre_tool("Bash", {}), "per JSON")
        runner = HookRunner({"PreToolUse": [{"hooks": [{"command": py_command(ok)}]}]}, self.cwd)
        self.assertIsNone(runner.pre_tool("Bash", {}))

    def test_failing_hook_only_warns(self) -> None:
        crash = self.script("crash.py", "import sys; sys.exit(1)")
        notes: list[str] = []
        runner = HookRunner({"PreToolUse": [{"hooks": [{"command": py_command(crash)}]}]}, self.cwd, notes.append)
        self.assertIsNone(runner.pre_tool("Bash", {}))
        self.assertTrue(notes and "fehlgeschlagen" in notes[0])

    def test_payload_reaches_hook_on_stdin(self) -> None:
        dump = self.script("dump.py", "import sys; open('payload.json', 'w').write(sys.stdin.read())")
        runner = HookRunner({"PostToolUse": [{"matcher": "Read|Grep", "hooks": [{"command": py_command(dump)}]}]}, self.cwd)
        runner.post_tool("Read", {"file_path": "a.txt"}, "inhalt")
        payload = json.loads((self.cwd / "payload.json").read_text())
        self.assertEqual((payload["tool_name"], payload["tool_input"], payload["tool_response"]),
                         ("Read", {"file_path": "a.txt"}, "inhalt"))

    def test_user_prompt_context_and_block(self) -> None:
        ctx = self.script("ctx.py", "print('Branch: main')")
        stop = self.script("stop.py", "import sys; print('nein', file=sys.stderr); sys.exit(2)")
        runner = HookRunner({"UserPromptSubmit": [{"hooks": [{"command": py_command(ctx)}]}]}, self.cwd)
        self.assertEqual(runner.user_prompt("x"), (None, "Branch: main"))
        runner = HookRunner({"UserPromptSubmit": [{"hooks": [{"command": py_command(stop)}]}]}, self.cwd)
        self.assertEqual(runner.user_prompt("x"), ("nein", ""))

    def test_pre_hook_blocks_write_in_agent_loop(self) -> None:
        block = self.script("block.py", "import sys; print('Schreiben verboten', file=sys.stderr); sys.exit(2)")
        settings = Settings(hooks={"PreToolUse": [{"matcher": "Write", "hooks": [{"command": py_command(block)}]}]})
        script = [tool_chunks("Write", {"file_path": "x.txt", "content": "1"}), text_chunks("ok")]
        agent, fake = self.make_agent(script, settings=settings)
        agent.run_turn("schreibe x")
        self.assertFalse((self.cwd / "x.txt").exists())
        self.assertIn("Hook blockiert: Schreiben verboten", fake.requests[1]["messages"][-1]["content"])

    def test_post_hook_feedback_is_appended_to_result(self) -> None:
        fb = self.script("fb.py", "import sys; print('Lint: 1 Warnung', file=sys.stderr); sys.exit(2)")
        settings = Settings(hooks={"PostToolUse": [{"matcher": "Write", "hooks": [{"command": py_command(fb)}]}]})
        script = [tool_chunks("Write", {"file_path": "x.txt", "content": "1"}), text_chunks("ok")]
        agent, fake = self.make_agent(script, settings=settings)
        agent.run_turn("schreibe x")
        self.assertTrue((self.cwd / "x.txt").exists())  # PostToolUse macht nichts rückgängig
        self.assertIn("Lint: 1 Warnung", fake.requests[1]["messages"][-1]["content"])

    def test_user_prompt_hook_can_block_turn(self) -> None:
        stop = self.script("stop.py", "import sys; print('gesperrt', file=sys.stderr); sys.exit(2)")
        settings = Settings(hooks={"UserPromptSubmit": [{"hooks": [{"command": py_command(stop)}]}]})
        agent, fake = self.make_agent([text_chunks("nie")], settings=settings)
        agent.run_turn("hallo")
        self.assertEqual((agent.messages, fake.requests), ([], []))
        self.assertIn("gesperrt", agent.out.getvalue())

    def test_stop_hook_continues_then_gives_up(self) -> None:
        once = self.script(
            "once.py",
            """
            import json, sys
            data = json.load(sys.stdin)
            if not data["stop_hook_active"]:
                print("Tests fehlen noch", file=sys.stderr); sys.exit(2)
            """,
        )
        settings = Settings(hooks={"Stop": [{"hooks": [{"command": py_command(once)}]}]})
        agent, fake = self.make_agent([text_chunks("fertig?"), text_chunks("jetzt wirklich")], settings=settings)
        agent.run_turn("los")
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("Tests fehlen noch", fake.requests[1]["messages"][-1]["content"])
        self.assertEqual(agent.messages[-1]["content"], "jetzt wirklich")

    def test_stop_hook_that_always_blocks_is_capped(self) -> None:
        always = self.script("always.py", "import sys; print('mehr', file=sys.stderr); sys.exit(2)")
        settings = Settings(hooks={"Stop": [{"hooks": [{"command": py_command(always)}]}]})
        agent, fake = self.make_agent([text_chunks(str(i)) for i in range(10)], settings=settings)
        agent.run_turn("los")
        self.assertEqual(len(fake.requests), 4)  # 1 Antwort + 3 erlaubte Fortsetzungen


class PlanModeTests(ExtCase):
    def tool_names(self, request: dict) -> set[str]:
        return {t["function"]["name"] for t in request.get("tools", [])}

    def test_exit_plan_mode_tool_only_visible_in_plan_mode(self) -> None:
        agent, fake = self.make_agent([text_chunks("a"), text_chunks("b")], mode="ask")
        agent.run_turn("normal")
        agent.perms.set_mode("plan")
        agent.run_turn("plane")
        self.assertNotIn("ExitPlanMode", self.tool_names(fake.requests[0]))
        self.assertIn("ExitPlanMode", self.tool_names(fake.requests[1]))
        self.assertIn("PLAN-MODUS", fake.requests[1]["messages"][0]["content"])
        self.assertNotIn("PLAN-MODUS", fake.requests[0]["messages"][0]["content"])

    def test_writes_and_bash_are_blocked_in_plan_mode(self) -> None:
        script = [
            tool_chunks("Write", {"file_path": "x.txt", "content": "1"}),
            tool_chunks("Bash", {"command": "echo hi > y.txt"}),
            text_chunks("ok"),
        ]
        agent, fake = self.make_agent(script, mode="plan", ask=lambda _: self.fail("Plan-Modus fragt nicht"))
        agent.run_turn("los")
        self.assertFalse((self.cwd / "x.txt").exists() or (self.cwd / "y.txt").exists())
        self.assertIn("Plan-Modus aktiv", fake.requests[1]["messages"][-1]["content"])
        self.assertIn("Plan-Modus aktiv", fake.requests[2]["messages"][-1]["content"])

    def test_approval_switches_mode(self) -> None:
        answers = iter(["j"])
        script = [tool_chunks("ExitPlanMode", {"plan": "1. Datei anlegen"}), text_chunks("los geht's")]
        agent, fake = self.make_agent(script, mode="plan", ask=lambda _: next(answers))
        agent.run_turn("plane")
        self.assertEqual(agent.perms.mode, "accept-edits")
        self.assertIn("Plan genehmigt", fake.requests[1]["messages"][-1]["content"])
        self.assertNotIn("PLAN-MODUS", fake.requests[1]["messages"][0]["content"])  # Prompt folgt dem neuen Modus

    def test_manual_approval_and_rejection_with_feedback(self) -> None:
        answers = iter(["m"])
        agent, fake = self.make_agent([tool_chunks("ExitPlanMode", {"plan": "p"}), text_chunks("x")], mode="plan",
                                      ask=lambda _: next(answers))
        agent.run_turn("plane")
        self.assertEqual(agent.perms.mode, "ask")

        answers = iter(["n", "bitte kleiner"])
        agent, fake = self.make_agent([tool_chunks("ExitPlanMode", {"plan": "p"}), text_chunks("x")], mode="plan",
                                      ask=lambda _: next(answers))
        agent.run_turn("plane")
        self.assertEqual(agent.perms.mode, "plan")
        self.assertIn("bitte kleiner", fake.requests[1]["messages"][-1]["content"])

    def test_plan_command_toggles_and_restores_previous_mode(self) -> None:
        agent, _ = self.make_agent([], mode="accept-edits")
        agent.commands["plan"][0]("", agent, agent.ui)
        self.assertEqual(agent.perms.mode, "plan")
        agent.commands["plan"][0]("off", agent, agent.ui)
        self.assertEqual(agent.perms.mode, "accept-edits")


class ImageTests(ExtCase):
    def test_extract_images(self) -> None:
        (self.cwd / "a.png").write_bytes(PNG)
        (self.cwd / "mit leerzeichen.png").write_bytes(PNG)
        (self.cwd / "notiz.txt").write_text("kein bild")
        (self.cwd / "fake.png").write_bytes(b"kein png")
        found = extract_images('Was zeigt @a.png, und @"mit leerzeichen.png"? Siehe @notiz.txt @fake.png @fehlt.png',
                               self.cwd)
        self.assertEqual(found.names, ["a.png", "mit leerzeichen.png"])
        self.assertEqual(len(found.images), 2)
        self.assertIn("[Bild: a.png],", found.text)  # Satzzeichen bleiben erhalten
        self.assertIn("@notiz.txt", found.text)  # Nicht-Bilder bleiben unangetastet
        self.assertEqual([e.split(":")[0] for e in found.errors], ["fake.png"])

    def test_limits(self) -> None:
        for i in range(MAX_IMAGES + 1):
            (self.cwd / f"{i}.png").write_bytes(PNG)
        found = extract_images(" ".join(f"@{i}.png" for i in range(MAX_IMAGES + 1)), self.cwd)
        self.assertEqual(len(found.images), MAX_IMAGES)
        self.assertEqual(len(found.errors), 1)
        big = self.cwd / "big.png"
        big.write_bytes(PNG + b"0" * (10 * 1024 * 1024))
        with self.assertRaises(ImageError):
            encode_image(big)

    def test_prompt_images_are_sent_to_ollama(self) -> None:
        (self.cwd / "shot.png").write_bytes(PNG)
        agent, fake = self.make_agent([text_chunks("Ein Screenshot.")])
        agent.run_turn("Beschreibe @shot.png")
        sent = fake.requests[0]["messages"][-1]
        self.assertEqual(len(sent["images"]), 1)
        self.assertIn("[Bild: shot.png]", sent["content"])

    def test_read_on_image_attaches_it_as_next_message(self) -> None:
        (self.cwd / "shot.png").write_bytes(PNG)
        script = [tool_chunks("Read", {"file_path": "shot.png"}), text_chunks("Ich sehe es.")]
        agent, fake = self.make_agent(script)
        agent.run_turn("schau dir shot.png an")
        second = fake.requests[1]["messages"]
        self.assertEqual(second[-2]["role"], "tool")
        self.assertIn("angehängt", second[-2]["content"])
        self.assertEqual((second[-1]["role"], len(second[-1]["images"])), ("user", 1))
        self.assertEqual(self.ctx.pending_images, [])

    def test_image_command_builds_prompt(self) -> None:
        agent, _ = self.make_agent([])
        handler = agent.commands["image"][0]
        self.assertEqual(handler('shot.png Was ist das?', agent, agent.ui), '@"shot.png" Was ist das?')
        self.assertEqual(handler('"mein bild.png"', agent, agent.ui), '@"mein bild.png" Beschreibe dieses Bild.')
        self.assertIsNone(handler("", agent, agent.ui))

    def test_interrupted_turn_drops_pending_images(self) -> None:
        agent, _ = self.make_agent([])  # leeres Skript => Ollama-Fehler beim ersten Aufruf
        self.ctx.pending_images.append("xyz")
        with self.assertRaises(Exception):
            agent.run_turn("hallo")
        self.assertEqual(self.ctx.pending_images, [])


class SubagentTests(ExtCase):
    def names(self, request: dict) -> set[str]:
        return {t["function"]["name"] for t in request.get("tools", [])}

    def test_task_runs_subagent_and_returns_report(self) -> None:
        (self.cwd / "f.txt").write_text("geheim")
        script = [
            tool_chunks("Task", {"description": "Suche", "prompt": "Finde f.txt", "subagent_type": "explore"}, 10, 1),
            tool_chunks("Read", {"file_path": "f.txt"}, 5, 1),  # Subagent
            text_chunks("Bericht: f.txt enthält 'geheim'", 3, 2),  # Subagent fertig
            text_chunks("Erledigt.", 7, 1),  # Hauptagent
        ]
        agent, fake = self.make_agent(script)
        agent.run_turn("Was steht in f.txt?")
        self.assertEqual(len(fake.requests), 4)
        child_first = fake.requests[1]
        self.assertEqual(self.names(child_first), {"Read", "Glob", "Grep", "LS"})  # explore = nur lesen, kein Task
        self.assertIn("rein lesender", child_first["messages"][0]["content"])
        self.assertEqual(child_first["messages"][1]["content"], "Finde f.txt")  # kennt das Gespräch nicht
        main_again = fake.requests[3]["messages"]
        self.assertIn("Bericht: f.txt enthält", main_again[-1]["content"])
        self.assertEqual((agent.tokens_in, agent.tokens_out), (25, 5))  # Token des Subagenten zählen mit
        self.assertEqual(len(agent.messages), 4)  # Subagent-Verlauf landet nicht im Hauptverlauf
        self.assertNotIn("Task", self.names(child_first))

    def test_subagent_respects_permissions_and_plan_mode(self) -> None:
        script = [
            tool_chunks("Task", {"prompt": "schreibe x.txt", "description": "x"}),
            tool_chunks("Write", {"file_path": "x.txt", "content": "1"}),  # Subagent versucht zu schreiben
            text_chunks("konnte nicht"),
            text_chunks("ok"),
        ]
        agent, fake = self.make_agent(script, mode="plan")
        agent.run_turn("los")
        self.assertFalse((self.cwd / "x.txt").exists())
        self.assertIn("Plan-Modus aktiv", fake.requests[2]["messages"][-1]["content"])

    def test_custom_agent_files_and_unknown_type(self) -> None:
        folder = self.cwd / ".pandora" / "agents"
        folder.mkdir(parents=True)
        (folder / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Prüft Code\ntools: Read, Grep\n---\nDu bist streng.\n", encoding="utf-8")
        (folder / "kaputt.md").write_text("kein Frontmatter", encoding="utf-8")
        script = [
            tool_chunks("Task", {"prompt": "prüfe", "subagent_type": "reviewer"}),
            text_chunks("sieht gut aus"),
            tool_chunks("Task", {"prompt": "x", "subagent_type": "gibtsnicht"}),
            text_chunks("ok"),
        ]
        agent, fake = self.make_agent(script)
        self.assertIn("reviewer", agent.agent_defs)
        self.assertNotIn("kaputt", agent.agent_defs)
        agent.run_turn("los")
        self.assertEqual(self.names(fake.requests[1]), {"Read", "Grep"})
        self.assertTrue(fake.requests[1]["messages"][0]["content"].startswith("Du bist streng."))
        self.assertIn("Unbekannter Subagent", fake.requests[3]["messages"][-1]["content"])

    def test_subagent_hooks_still_apply(self) -> None:
        block = self.script("block.py", "import sys; print('nein', file=sys.stderr); sys.exit(2)")
        settings = Settings(hooks={"PreToolUse": [{"matcher": "Write", "hooks": [{"command": py_command(block)}]}]})
        script = [
            tool_chunks("Task", {"prompt": "schreibe", "description": "x"}),
            tool_chunks("Write", {"file_path": "x.txt", "content": "1"}),
            text_chunks("blockiert"),
            text_chunks("ok"),
        ]
        agent, fake = self.make_agent(script, settings=settings)
        agent.run_turn("los")
        self.assertFalse((self.cwd / "x.txt").exists())
        self.assertIn("Hook blockiert", fake.requests[2]["messages"][-1]["content"])


FAKE_MCP_SERVER = '''
import json, sys

TOOLS = [
    {"name": "echo", "description": "Gibt Text zurück", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "delete", "description": "Löscht etwas", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "shot", "description": "Screenshot", "annotations": {"readOnlyHint": True}},
    {"name": "fail", "description": "Fehler", "annotations": {"readOnlyHint": True}},
]

for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method, params = msg["method"], msg.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params["name"], params.get("arguments", {})
        if name == "echo":
            result = {"content": [{"type": "text", "text": "echo: " + args.get("text", "")}]}
        elif name == "shot":
            result = {"content": [{"type": "image", "data": "QUJD", "mimeType": "image/png"}]}
        elif name == "fail":
            result = {"isError": True, "content": [{"type": "text", "text": "kaputt"}]}
        else:
            result = {"content": [{"type": "text", "text": "gelöscht"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "unbekannt"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
'''


class McpTests(ExtCase):
    def mcp_agent(self, script, mode="ask", ask=None):
        server = self.script("fake_mcp.py", FAKE_MCP_SERVER)
        settings = Settings(mcp_servers={"fake": {"command": sys.executable, "args": [str(server)]}})
        return self.make_agent(script, mode=mode, ask=ask, settings=settings)

    def test_tools_are_registered_with_readonly_detection(self) -> None:
        agent, _ = self.mcp_agent([])
        self.assertIn("MCP: 1 Server verbunden, 4 Werkzeuge", agent.out.getvalue())
        self.assertFalse(agent.tools["mcp__fake__echo"].mutating)  # readOnlyHint => ohne Rückfrage
        self.assertTrue(agent.tools["mcp__fake__delete"].mutating)  # ohne Hinweis => fragen

    def test_call_readonly_tool_without_prompt(self) -> None:
        script = [tool_chunks("mcp__fake__echo", {"text": "hallo"}), text_chunks("ok")]
        agent, fake = self.mcp_agent(script, ask=lambda _: self.fail("readOnly darf nicht fragen"))
        agent.run_turn("echo")
        self.assertIn("echo: hallo", fake.requests[1]["messages"][-1]["content"])

    def test_mutating_tool_asks_and_can_be_denied(self) -> None:
        script = [tool_chunks("mcp__fake__delete", {}), text_chunks("ok")]
        agent, fake = self.mcp_agent(script, ask=lambda _: "n")
        agent.run_turn("lösche")
        self.assertIn("abgelehnt", fake.requests[1]["messages"][-1]["content"])
        script = [tool_chunks("mcp__fake__delete", {}), text_chunks("ok")]
        agent, fake = self.mcp_agent(script, ask=lambda _: "j")
        agent.run_turn("lösche")
        self.assertIn("gelöscht", fake.requests[1]["messages"][-1]["content"])

    def test_error_result_and_image_result(self) -> None:
        script = [tool_chunks("mcp__fake__fail", {}), tool_chunks("mcp__fake__shot", {}), text_chunks("ok")]
        agent, fake = self.mcp_agent(script)
        agent.run_turn("los")
        self.assertIn("Fehler: kaputt", fake.requests[1]["messages"][-1]["content"])
        last = fake.requests[2]["messages"]
        self.assertEqual(last[-1]["images"], ["QUJD"])

    def test_plan_mode_blocks_mutating_mcp_tools_but_not_readonly(self) -> None:
        script = [tool_chunks("mcp__fake__delete", {}), tool_chunks("mcp__fake__echo", {"text": "x"}), text_chunks("ok")]
        agent, fake = self.mcp_agent(script, mode="plan")
        agent.run_turn("los")
        self.assertIn("Plan-Modus aktiv", fake.requests[1]["messages"][-1]["content"])
        self.assertIn("echo: x", fake.requests[2]["messages"][-1]["content"])

    def test_broken_server_does_not_prevent_start(self) -> None:
        settings = Settings(mcp_servers={"weg": {"command": "gibt-es-nicht-xyz"}, "leer": {}})
        agent, _ = self.make_agent([], settings=settings)
        output = agent.out.getvalue()
        self.assertIn("MCP-Server 'weg'", output)
        self.assertIn("MCP-Server 'leer'", output)
        self.assertFalse([n for n in agent.tools if n.startswith("mcp__")])

    def test_http_transport(self) -> None:
        seen: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append({"body": body, "auth": self.headers.get("Authorization")})
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                if body["method"] == "initialize":
                    result = {"protocolVersion": "2025-03-26"}
                elif body["method"] == "tools/list":
                    result = {"tools": [{"name": "ping", "description": "p"}]}
                else:
                    result = {"content": [{"type": "text", "text": "pong"}]}
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
                if body["method"] == "tools/call":  # als SSE-Strom antworten
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(f"event: message\ndata: {payload}\n\n".encode())
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Mcp-Session-Id", "sess-1")
                    self.end_headers()
                    self.wfile.write(payload.encode())

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        with mock.patch.dict(os.environ, {"MCP_TOKEN": "geheim"}):
            server = McpServer("web", {"url": f"http://127.0.0.1:{httpd.server_address[1]}/mcp",
                                       "headers": {"Authorization": "Bearer ${MCP_TOKEN}"}}, self.cwd)
            server.connect()
        self.assertEqual(server.kind, "http")
        self.assertEqual([s["name"] for s in server.tool_specs], ["ping"])
        self.assertEqual(server.call("ping", {})["content"][0]["text"], "pong")
        self.assertEqual({s["auth"] for s in seen}, {"Bearer geheim"})  # $VAR wurde aus der Umgebung ersetzt
        self.assertEqual(server.transport.session, "sess-1")


class InstallTests(ExtCase):
    def test_broken_extension_does_not_block_others(self) -> None:
        agent, _ = self.make_agent([], settings=Settings(notices=["Konfiguration ungültig"]))
        self.assertIn("Konfiguration ungültig", agent.out.getvalue())
        with mock.patch("pandora_code.extensions.hooks.install", side_effect=RuntimeError("boom")):
            agent2, _ = self.make_agent([])
        self.assertIn("Erweiterung 'hooks' konnte nicht geladen werden", agent2.out.getvalue())
        self.assertIn("plan", agent2.commands)  # die anderen wurden trotzdem geladen

    def test_disable(self) -> None:
        agent, _ = self.make_agent([], disabled={"plan", "mcp"})
        self.assertNotIn("plan", agent.commands)
        self.assertNotIn("ExitPlanMode", agent.tools)
        self.assertEqual(set(agent.commands),
                         {"hooks", "autofix", "image", "agents", "graph", "rag", "sandbox", "websearch", "plugin",
                          "skills"})

    def test_all_modules_install_cleanly(self) -> None:
        agent, _ = self.make_agent([])
        self.assertNotIn("konnte nicht geladen", agent.out.getvalue())
        self.assertEqual(set(agent.commands),
                         {"hooks", "autofix", "plan", "image", "agents", "graph", "rag", "sandbox", "websearch",
                          "plugin", "skills"})  # mcp ohne Server: kein Befehl
        self.assertEqual(MODULES, ("hooks", "auto_fix", "plan", "vision", "subagents", "mcp", "ast_graph",
                                   "vector_rag", "sandbox", "web_search", "plugins", "skills"))
        self.assertTrue({"Task", "ExitPlanMode", "CodeSymbols", "CodeDef", "CodeCallers", "CodeSearch",
                         "WebSearch", "WebFetch", "SkillSearch", "SkillLoad"} <= set(agent.tools))


class CliTests(ExtCase):
    def test_help_lists_extension_commands_and_dispatch(self) -> None:
        agent, _ = self.make_agent([])
        banner = mock.Mock()
        ui = UI(io.StringIO())
        cli.handle_command("/help", agent, banner, ui)
        text = ui.out.getvalue()
        for command in ("/plan", "/image", "/hooks", "/agents", "plan | yolo"):
            self.assertIn(command, text)
        self.assertIsNone(cli.handle_command("/plan", agent, banner, ui))
        self.assertEqual(agent.perms.mode, "plan")
        self.assertEqual(cli.handle_command("/image a.png Was?", agent, banner, ui), '@"a.png" Was?')
        self.assertIsNone(cli.handle_command("/permissions plan", agent, banner, ui))

    def run_main(self, fake: FakeOllama, *extra: str) -> tuple[int, str, str]:
        argv = ["-p", "--host", fake.host, "--cwd", str(self.cwd), "-m", "qwen2.5-coder:7b", *extra]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_print_mode_end_to_end(self) -> None:
        fake = FakeOllama([tool_chunks("Write", {"file_path": "n.txt", "content": "neu"}), text_chunks("Fertig.")])
        self.addCleanup(fake.close)
        code, out, _ = self.run_main(fake, "--yolo", "Lege n.txt an")
        self.assertEqual(code, 0)
        self.assertEqual((self.cwd / "n.txt").read_text(), "neu")
        self.assertIn("Fertig.", out)
        names = {t["function"]["name"] for t in fake.requests[0]["tools"]}
        self.assertTrue({"Task", "Read"} <= names)

    def test_print_mode_never_trusts_new_project_hooks(self) -> None:
        marker = self.cwd / "hook_ran.txt"
        (self.cwd / ".pandora").mkdir()
        hook = {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": f"echo x > {shlex.quote(str(marker))}"}]}]}}
        (self.cwd / ".pandora" / "settings.json").write_text(json.dumps(hook))
        fake = FakeOllama([text_chunks("ok")])
        self.addCleanup(fake.close)
        code, out, err = self.run_main(fake, "hallo")
        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())
        self.assertIn("nicht als vertrauenswürdig", out + err)

    def test_disable_option_and_env(self) -> None:
        fake = FakeOllama([text_chunks("a"), text_chunks("b")])
        self.addCleanup(fake.close)
        self.run_main(fake, "--disable", "subagents", "hallo")
        self.assertNotIn("Task", {t["function"]["name"] for t in fake.requests[0]["tools"]})
        with mock.patch.dict(os.environ, {"PANDORA_DISABLE": "plan, vision"}):
            self.run_main(fake, "hallo")
        self.assertNotIn("ExitPlanMode", {t["function"]["name"] for t in fake.requests[1].get("tools", [])})

    def test_mode_plan_is_accepted(self) -> None:
        fake = FakeOllama([text_chunks("nur Plan")])
        self.addCleanup(fake.close)
        code, _, _ = self.run_main(fake, "--mode", "plan", "plane")
        self.assertEqual(code, 0)
        self.assertIn("ExitPlanMode", {t["function"]["name"] for t in fake.requests[0]["tools"]})

    def test_ask_trust_prompt(self) -> None:
        with mock.patch("builtins.input", return_value="j"), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cli.ask_trust(self.cwd, "  Hook X"))
        with mock.patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(cli.ask_trust(self.cwd, "  Hook X"))
        with mock.patch("builtins.input", side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(cli.ask_trust(self.cwd, "  Hook X"))


if __name__ == "__main__":
    unittest.main()
