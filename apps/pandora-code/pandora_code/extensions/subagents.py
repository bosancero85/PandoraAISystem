"""Subagenten: Aufgaben mit eigenem Kontext delegieren (Werkzeug "Task").

Eigene Agenten sind Markdown-Dateien mit Kopfzeilen in ~/.pandora/agents/ oder .pandora/agents/:

    ---
    name: reviewer
    description: Prüft Änderungen auf Fehler
    tools: Read, Grep, Glob        (weglassen = alle außer Task)
    model: qwen2.5-coder:7b        (optional)
    ---
    Du bist ein strenger Code-Reviewer. ...
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from ..agent import Agent
from ..config import home_dir
from ..ollama_client import OllamaError
from ..tools import Tool, ToolContext, ToolError, schema
from ..ui import DIM, UI, summarize_args

EXCLUDED_TOOLS = {"Task", "ExitPlanMode"}  # Subagenten starten keine weiteren Subagenten
SUB_MAX_STEPS = 15
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)

GENERAL_PROMPT = """Du bist ein Subagent von Pandora® 🦙 Code. Du erledigst genau die dir übergebene Aufgabe \
selbstständig mit den verfügbaren Werkzeugen und antwortest am Ende mit einem knappen, in sich verständlichen \
Bericht (Ergebnis, betroffene Dateien, offene Punkte). Du kennst das bisherige Gespräch nicht; alles Nötige steht \
in der Aufgabe. Lies Dateien mit Read, bevor du sie änderst."""

EXPLORE_PROMPT = """Du bist ein schneller, rein lesender Recherche-Subagent von Pandora® 🦙 Code. Durchsuche die \
Codebasis mit Glob, Grep, LS und Read und antworte mit einem knappen Bericht: relevante Dateien mit Pfad und \
Zeilennummern, kurze Erklärung. Du änderst nichts."""


@dataclass
class AgentDef:
    name: str
    description: str
    prompt: str
    tools: list[str] | None = None  # None = alle (außer EXCLUDED_TOOLS)
    model: str | None = None


BUILTIN = {
    "general-purpose": AgentDef(
        "general-purpose", "Allzweck-Agent für Recherche und mehrstufige Teilaufgaben", GENERAL_PROMPT
    ),
    "explore": AgentDef(
        "explore", "Schneller, rein lesender Agent zum Suchen und Verstehen von Code", EXPLORE_PROMPT,
        tools=["Read", "Glob", "Grep", "LS"],
    ),
}


def parse_agent_file(path: Path) -> AgentDef | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONT.match(text)
    if not match:
        return None
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip()
    prompt = match.group(2).strip()
    if not prompt:
        return None
    tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    return AgentDef(
        name=meta.get("name") or path.stem,
        description=meta.get("description") or "Benutzerdefinierter Agent",
        prompt=prompt,
        tools=None if not tools or tools == ["*"] else tools,
        model=meta.get("model") or None,
    )


def load_agents(cwd: Path, extra_dirs: tuple[Path, ...] = ()) -> dict[str, AgentDef]:
    """Liest Agent-Definitionen neu von der Platte – bewusst ohne Cache, damit sowohl von Hand bearbeitete
    .md-Dateien als auch von Plugins mitgebrachte Agenten ohne Neustart wirken (siehe extensions/plugins.py,
    das `extra_dirs` mit den agents/-Ordnern installierter Plugins befüllt)."""
    defs = dict(BUILTIN)
    for folder in (home_dir() / "agents", cwd / ".pandora" / "agents", *extra_dirs):  # je später, desto höher die Priorität
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                definition = parse_agent_file(path)
                if definition:
                    defs[definition.name] = definition
    return defs


def _plugin_agent_dirs() -> tuple[Path, ...]:
    """Lazy Import, um einen Importzyklus mit extensions/plugins.py zu vermeiden (das Modul wird nur
    dann überhaupt gebraucht, wenn tatsächlich ein Plugin mit agents/-Ordner installiert ist)."""
    try:
        from .plugins import agent_dirs
    except ImportError:
        return ()
    return agent_dirs()


class QuietUI(UI):
    """Zeigt von einem Subagenten nur die Werkzeugaufrufe (eingerückt), nicht seinen Text."""

    def __init__(self, parent: UI) -> None:
        super().__init__(parent.out)
        self.color = parent.color

    def begin_assistant(self) -> None: ...
    def thinking(self, text: str) -> None: ...
    def stream(self, text: str) -> None: ...
    def end_assistant(self) -> None: ...
    def tool_result(self, result: str) -> None: ...

    def tool_call(self, name: str, args: dict) -> None:
        self._write(self.paint(DIM, f"   ↳ {name}({summarize_args(args)})") + "\n")


def resolve_subagent_model(parent: Agent, definition: AgentDef, prompt: str = "") -> str:
    """Wählt das Modell des Subagenten. Ohne explizites `model:` in der Agent-Datei entscheidet der
    Smart Model Router (parent.router) nach Aufgabenkomplexität – 'explore' (rein lesende Recherche)
    bekommt immer die schnelle Rolle, da es keine schweren Refactorings/Architekturentscheidungen trifft.
    Fehlt das ermittelte Modell (oder unterstützt es keine Tools), wechselt die ModelRegistry automatisch
    auf ein installiertes, tool-fähiges Modell."""
    requested = definition.model
    if not requested:
        if definition.name == "explore":
            requested = "fast"
        elif parent.router:
            requested = parent.router.classify(prompt).role
        else:
            requested = parent.model
    if not parent.registry:
        return requested
    resolution = parent.registry.resolve(requested, role="general", prefer=parent.model)
    if not resolution.model:
        return requested  # Registry kann gerade nichts abrufen – unverändert versuchen
    if resolution.switched:
        parent.ui.info(f"⚠ Subagent '{definition.name}': {resolution.reason} – verwende '{resolution.model}'.")
    return resolution.model


def run_subagent(parent: Agent, definition: AgentDef, prompt: str, description: str) -> str:
    tools = {
        name: tool
        for name, tool in parent.tools.items()
        if name not in EXCLUDED_TOOLS
        and (definition.tools is None or any(fnmatch.fnmatchcase(name, pattern) for pattern in definition.tools))
    }
    child = Agent(
        parent.client,
        resolve_subagent_model(parent, definition, prompt),
        ToolContext(parent.ctx.cwd),
        parent.perms,  # gleiche Berechtigungen: Änderungen werden weiter erfragt, Plan-Modus gilt auch hier
        QuietUI(parent.ui),
        tools=tools,
        system_prompt=definition.prompt,
        hooks=parent.hooks,
        max_steps=SUB_MAX_STEPS,
        registry=parent.registry,  # damit auch der Subagent selbst bei Ausfall automatisch wechseln kann
    )
    child.depth = parent.depth + 1
    parent.ui.info(f"▸ Subagent {definition.name}: {description}")
    try:
        child.run_turn(prompt)
    except OllamaError as err:  # ein Fehler im Subagenten soll nicht den ganzen Zug des Hauptagenten verwerfen
        raise ToolError(f"Subagent fehlgeschlagen: {err}") from None
    finally:
        parent.tokens_in += child.tokens_in
        parent.tokens_out += child.tokens_out
    for message in reversed(child.messages):
        if message.get("role") == "assistant" and message.get("content", "").strip():
            return message["content"].strip()
    return "(Der Subagent lieferte keine Antwort.)"


def install(agent, settings) -> None:
    def current_defs() -> dict[str, AgentDef]:
        defs = load_agents(agent.ctx.cwd, _plugin_agent_dirs())
        agent.agent_defs = defs  # für /agents und andere Erweiterungen, die den aktuellen Stand lesen wollen
        return defs

    initial = current_defs()  # nur für die Tool-Beschreibung/enum zum Start; task() liest danach immer frisch

    def task(ctx, args: dict) -> str:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ToolError("'prompt' fehlt.")
        kind = str(args.get("subagent_type") or "general-purpose")
        defs = current_defs()  # frisch von der Platte: neu installierte/geänderte Plugin-Agenten wirken sofort
        definition = defs.get(kind)
        if definition is None:
            raise ToolError(f"Unbekannter Subagent '{kind}'. Verfügbar: {', '.join(sorted(defs))}")
        return run_subagent(agent, definition, prompt, str(args.get("description") or kind))

    listing = "\n".join(f"- {d.name}: {d.description}" for d in initial.values())
    agent.add_tool(
        Tool(
            "Task",
            "Delegate a self-contained task to a subagent that works in its own context and returns only a final "
            "report. Use it for broad searches or independent subtasks. The subagent knows nothing about this "
            f"conversation, so put everything it needs into the prompt.\nAvailable agent types:\n{listing}",
            schema(
                {
                    "description": {"type": "string", "description": "Short title (3-5 words)"},
                    "prompt": {"type": "string", "description": "Complete task description for the subagent"},
                    "subagent_type": {"type": "string", "description": "Agent type (see tool description)"},
                },
                ("description", "prompt"),
            ),
            task,
        )
    )

    def agents_command(arg: str, agent, ui) -> str | None:
        defs = current_defs()
        ui.info("\n".join(
            f"{d.name}: {d.description}" + (f"  [Werkzeuge: {', '.join(d.tools)}]" if d.tools else "")
            for d in defs.values()
        ))
        return None

    agent.register_command("agents", agents_command, "/agents  verfügbare Subagenten anzeigen (Hot Reload)")
