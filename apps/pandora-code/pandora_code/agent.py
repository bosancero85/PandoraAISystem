"""Agent-Schleife: Modell fragen, Tool-Calls ausführen, Ergebnisse zurückgeben."""
from __future__ import annotations

import datetime
import json
import platform
from typing import Callable

from .extensions.plan import BLOCK_MESSAGE, PLAN_ADDENDUM
from .images import extract_images
from .llm.models import ModelRegistry, is_missing_model_error, is_no_tools_error
from .llm.router import TaskRouter
from .ollama_client import OllamaClient, OllamaError
from .permissions import Permissions
from .tools import Tool, ToolContext, ToolError, build_tools, describe_shell
from .ui import UI

MAX_MODEL_SWITCHES = 4  # Sicherung gegen Pendeln, falls mehrere Modelle nacheinander ausfallen

MAX_STEPS = 25
MAX_STOP_CONTINUATIONS = 3  # so oft darf ein Stop-Hook den Agenten pro Zug weiterarbeiten lassen
MEMORY_FILE = "PANDORA.md"  # Gegenstück zu CLAUDE.md

ENV_BLOCK = """Umgebung:
- Arbeitsverzeichnis: {cwd}
- Betriebssystem: {os}
- Shell für das Bash-Werkzeug: {shell}
- Datum: {date}"""

SYSTEM_PROMPT = """Du bist Pandora® 🦙 Code, ein interaktiver Coding-Agent im Terminal. \
Du läufst lokal über Ollama und hilfst bei der Softwareentwicklung: Code lesen, schreiben, ändern, \
Befehle ausführen, Fehler suchen.

Regeln:
- Antworte in der Sprache des Benutzers, knapp und sachlich.
- Nutze die Werkzeuge, statt Dateiinhalte zu raten. Lies eine Datei mit Read, bevor du sie mit Edit oder Write änderst.
- Bevorzuge Edit für kleine Änderungen, Write nur für neue oder komplett neu geschriebene Dateien.
- Suche mit Glob und Grep, bevor du Dateien öffnest. Nutze LS für Ordnerübersichten.
- Pflege bei Aufgaben mit mehreren Schritten eine Liste mit TodoWrite.
- Prüfe deine Änderungen, wenn möglich (Tests, Linter, Programm starten) und melde ehrlich, was nicht geklappt hat.
- Ändere nur, was zur Aufgabe gehört, und lege keine unnötigen Dateien an.
- Pfade dürfen relativ zum Arbeitsverzeichnis angegeben werden.

""" + ENV_BLOCK

COMPACT_PROMPT = (
    "Fasse unser bisheriges Gespräch für die Fortsetzung zusammen: Ziel, erledigte Schritte, "
    "geänderte Dateien, offene Punkte. Knapp, nur die Zusammenfassung."
)


class Agent:
    def __init__(
        self,
        client: OllamaClient,
        model: str,
        ctx: ToolContext,
        permissions: Permissions,
        ui: UI,
        *,
        tools: dict[str, Tool] | None = None,
        system_prompt: str | None = None,
        hooks=None,
        max_steps: int = MAX_STEPS,
        prompt_loader: Callable[[], str] | None = None,
        registry: ModelRegistry | None = None,
        router: TaskRouter | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.registry = registry  # ModelRegistry: ermöglicht Hot-Reload-Ersatz, wenn `model` ausfällt
        self.router = router  # TaskRouter: wählt je Nachricht fast/general/strong (None = kein Routing)
        self.auto_route_pinned = False  # per /model gesetzt: Router pausiert, bis /router an wieder aktiviert
        self.consecutive_tool_failures = 0  # Signal für den Router: mehrere Fehler in Folge -> stärkeres Modell
        self.ctx = ctx
        self.perms = permissions
        self.ui = ui
        self.tools: dict[str, Tool] = dict(tools) if tools is not None else build_tools()
        self._by_lower = {name.lower(): tool for name, tool in self.tools.items()}
        self.base_prompt = system_prompt  # None = Standard-Prompt; sonst z. B. der Prompt eines Subagenten
        self.hooks = hooks  # HookRunner oder None (setzt die Erweiterung "hooks")
        self.max_steps = max_steps
        self.prompt_loader = prompt_loader  # liefert den editierbaren Zusatz-Prompt (wird pro Anfrage neu gelesen)
        self.depth = 0  # 0 = Hauptagent, >0 = Subagent
        self.messages: list[dict] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.commands: dict[str, tuple[Callable, str]] = {}  # Slash-Befehle der Erweiterungen
        self.closers: list[Callable[[], None]] = []  # beim Beenden aufzurufen (z. B. MCP-Server schließen)
        self.agent_defs: dict = {}
        self.mcp_servers: list = []

    # -- Erweiterungs-Schnittstelle --------------------------------------------------
    def add_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool
        self._by_lower[tool.name.lower()] = tool

    def register_command(self, name: str, handler: Callable, help_text: str = "") -> None:
        self.commands[name.lower()] = (handler, help_text)

    def notice(self, text: str, error: bool = False) -> None:
        (self.ui.error if error else self.ui.info)(text)

    def close(self) -> None:
        for closer in reversed(self.closers):
            try:
                closer()
            except Exception:  # Aufräumen darf das Beenden nicht verhindern
                pass
        self.closers.clear()

    # -- Prompt ------------------------------------------------------------------
    def system_prompt(self) -> str:
        env = dict(cwd=self.ctx.cwd, os=platform.system(), shell=describe_shell(),
                   date=datetime.date.today().isoformat())
        if self.base_prompt is None:
            text = SYSTEM_PROMPT.format(**env)
        else:
            text = self.base_prompt + "\n\n" + ENV_BLOCK.format(**env)
        memory = self.ctx.cwd / MEMORY_FILE
        if memory.is_file():
            notes = memory.read_text(encoding="utf-8", errors="replace")[:8000]
            text += f"\n\nProjekt-Notizen ({MEMORY_FILE}):\n{notes}"
        if self.base_prompt is None:  # nur Hauptagent; Subagenten haben ihren eigenen Prompt
            extra = self.prompt_loader().strip() if self.prompt_loader else ""
            if extra:
                text += "\n\n" + extra
            playbook = self.ctx.cwd / "playbook" / "playbook.md"
            if playbook.is_file():
                rules = playbook.read_text(encoding="utf-8", errors="replace")[:8000]
                text += f"\n\nPlaybook (playbook/playbook.md) – verbindlich:\n{rules}"
        if self.perms.mode == "plan":
            text += "\n\n" + (PLAN_ADDENDUM if self.depth == 0 else "Plan-Modus: nur lesen, nichts ändern.")
        return text

    def _api_messages(self) -> list[dict]:
        return [{"role": "system", "content": self.system_prompt()}, *self.messages]

    def _schemas(self) -> list[dict]:
        mode = self.perms.mode
        return [t.schema() for t in self.tools.values() if t.modes is None or mode in t.modes]

    # -- Ablauf --------------------------------------------------------------------
    def _user_message(self, text: str) -> dict:
        found = extract_images(text, self.ctx.cwd)
        for problem in found.errors:
            self.ui.error(f"Bild übersprungen – {problem}")
        if found.names:
            self.ui.info("Bilder angehängt: " + ", ".join(found.names))
        message: dict = {"role": "user", "content": found.text}
        if found.images:
            message["images"] = found.images
        return message

    def _flush_images(self) -> None:
        """Bilder aus Werkzeugergebnissen (Read, MCP) gehen als eigene Nachricht ans Modell."""
        if self.ctx.pending_images:
            images, self.ctx.pending_images = self.ctx.pending_images, []
            self.messages.append({"role": "user", "content": "[Bild(er) aus dem letzten Werkzeugergebnis]", "images": images})

    def _route(self, prompt: str) -> None:
        """Wählt vor einem Hauptagent-Zug automatisch fast/general/strong (siehe llm/router.py). Greift nicht,
        wenn kein Router/keine Registry vorhanden ist, der Router deaktiviert ist, oder /model das Modell
        manuell angepinnt hat."""
        if self.depth != 0 or not self.router or not self.registry or self.auto_route_pinned:
            return
        self.router.recent_failures = self.consecutive_tool_failures
        signal = self.router.classify(prompt)
        resolution = self.registry.resolve(role=signal.role, prefer=self.model)
        if resolution.model and resolution.model != self.model:
            self.ui.info(f"↻ Router: {signal.reason} → '{resolution.model}' ({signal.role}).")
            self.model = resolution.model

    def run_turn(self, text: str) -> None:
        hooks = self.hooks if self.depth == 0 else None  # Prompt-/Stop-Hooks gelten nur für den Hauptagenten
        if hooks:
            reason, extra = hooks.user_prompt(text)
            if reason is not None:
                self.ui.error(f"Eingabe von einem Hook blockiert: {reason}")
                return
            if extra:
                text = f"{text}\n\n[Zusätzlicher Kontext von Hooks]\n{extra}"
        self._route(text)
        start = len(self.messages)
        self.messages.append(self._user_message(text))
        stops = 0
        try:
            for _ in range(self.max_steps):
                content, calls = self._stream_response()
                message: dict = {"role": "assistant", "content": content}
                if calls:
                    message["tool_calls"] = calls
                self.messages.append(message)
                if not calls:
                    reason = hooks.stop(stops > 0) if hooks and stops < MAX_STOP_CONTINUATIONS else None
                    if reason is None:
                        return
                    stops += 1
                    self.ui.info(f"Stop-Hook: {reason}")
                    self.messages.append({"role": "user", "content": f"[Stop-Hook] {reason}"})
                    continue
                for call in calls:
                    result = self._execute(call)
                    name = (call.get("function") or {}).get("name", "")
                    self.messages.append({"role": "tool", "tool_name": name, "content": result})
                self._flush_images()
            self.ui.info(f"Schritt-Limit ({self.max_steps}) erreicht – schreib 'weiter', um fortzufahren.")
        except (KeyboardInterrupt, OllamaError):
            del self.messages[start:]  # Verlauf bleibt konsistent
            self.ctx.pending_images.clear()
            raise

    def _stream_response(self) -> tuple[str, list[dict]]:
        schemas = self._schemas()
        self.ui.begin_assistant()
        failed: set[str] = set()
        try:
            for _ in range(MAX_MODEL_SWITCHES):
                content: list[str] = []
                calls: list[dict] = []
                try:
                    for chunk in self.client.chat_stream(self.model, self._api_messages(), schemas):
                        message = chunk.get("message") or {}
                        if message.get("thinking"):
                            self.ui.thinking(message["thinking"])
                        if message.get("content"):
                            content.append(message["content"])
                            self.ui.stream(message["content"])
                        calls.extend(message.get("tool_calls") or [])
                        if chunk.get("done"):
                            self.tokens_in += chunk.get("prompt_eval_count") or 0
                            self.tokens_out += chunk.get("eval_count") or 0
                    return "".join(content), calls
                except OllamaError as err:
                    replacement = self._switch_after_failure(err, failed, bool(schemas))
                    if replacement is None:
                        raise
                    failed.add(self.model)
                    self.model = replacement
        finally:
            self.ui.end_assistant()
        raise OllamaError(f"Kein Modell verfügbar (versucht: {', '.join(sorted(failed)) or self.model}).")

    def _switch_after_failure(self, err: OllamaError, failed: set[str], need_tools: bool) -> str | None:
        """Bei fehlendem/untauglichem Modell (Ollama meldet 'not found' oder 'does not support tools') automatisch
        auf ein installiertes, passendes Modell wechseln (Hot Reload über die ModelRegistry). Gibt den Ersatz
        zurück, oder None – dann wird err erneut ausgelöst, z. B. weil kein Ersatz existiert oder die Ursache
        eine andere ist (Verbindungsfehler, Server-Fehler 5xx)."""
        if not self.registry or self.model in failed:
            return None
        if is_no_tools_error(err):
            self.registry.mark_no_tools(self.model)
        elif not is_missing_model_error(err):
            return None
        resolution = self.registry.resolve(role="general", need_tools=need_tools, exclude=failed | {self.model})
        if not resolution.model or resolution.model in failed or resolution.model == self.model:
            return None
        self.ui.error(f"⚠ Modell '{self.model}' nicht nutzbar ({err}). Wechsle auf '{resolution.model}'.")
        return resolution.model

    def _execute(self, call: dict) -> str:
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        self.ui.tool_call(name, args)
        tool = self.tools.get(name) or self._by_lower.get(name.lower())
        if tool is None:
            result = f"Fehler: Unbekanntes Werkzeug '{name}'. Verfügbar: {', '.join(self.tools)}"
        else:
            result = self._run_tool(tool, args)
        self.consecutive_tool_failures = self.consecutive_tool_failures + 1 if result.startswith("Fehler") else 0
        self.ui.tool_result(result)
        return result

    def _run_tool(self, tool: Tool, args: dict) -> str:
        if self.hooks:
            blocked = self.hooks.pre_tool(tool.name, args)
            if blocked is not None:
                return f"Von einem Hook blockiert: {blocked}"
        if tool.mutating:
            if self.perms.mode == "plan":
                return BLOCK_MESSAGE
            try:
                preview = tool.preview(self.ctx, args) if tool.preview else ""
            except Exception:  # Vorschau ist nur Komfort
                preview = ""
            if not self.perms.allowed(tool, preview or json.dumps(args, ensure_ascii=False)[:500]):
                return "Der Benutzer hat die Ausführung abgelehnt."
        try:
            result = tool.run(self.ctx, args)
        except ToolError as err:
            return f"Fehler: {err}"
        except Exception as err:  # unerwartete Fehler gehen an das Modell zurück, statt abzustürzen
            return f"Fehler ({type(err).__name__}): {err}"
        if self.hooks:
            feedback = self.hooks.post_tool(tool.name, args, result)
            if feedback:
                result += f"\n[Rückmeldung von Hook]\n{feedback}"
        return result

    # -- Verwaltung ------------------------------------------------------------------
    def clear(self) -> None:
        self.messages = []
        self.ctx.read_files.clear()
        self.ctx.todos = []
        self.ctx.pending_images.clear()
        self.consecutive_tool_failures = 0

    def compact(self) -> None:
        if not self.messages:
            return
        prompt = [*self._api_messages(), {"role": "user", "content": COMPACT_PROMPT}]
        parts = [(c.get("message") or {}).get("content", "") for c in self.client.chat_stream(self.model, prompt)]
        summary = "".join(parts).strip() or "(keine Zusammenfassung erhalten)"
        self.messages = [
            {"role": "user", "content": f"Zusammenfassung des bisherigen Gesprächs:\n{summary}"},
            {"role": "assistant", "content": "Verstanden, ich mache damit weiter."},
        ]
