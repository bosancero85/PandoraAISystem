"""Textual-TUI: volle Terminal-Oberfläche statt der einfachen Konsolen-Ausgabe (`pandora code --tui`).

Drei Bereiche:
- Links: Gedanken-/Tool-Aktivitäts-Stream (was das Modell gerade denkt und tut).
- Rechts: Live-Diff-Vorschau der zuletzt geänderten Datei (Write/Edit).
- Unten: Eingabezeile und Statuszeile (Modell, Modus, Verzeichnis) in Neon-Violett/Cyan.

Optionale Abhängigkeit: `pip install pandora-code[tui]` (installiert `textual`). Ohne Textual bleibt die
normale Konsolen-Oberfläche (`pandora_code.cli.repl`) unverändert nutzbar; `pandora code --tui` gibt dann
eine klare Installationsanweisung aus und beendet sich, statt sich nur schlechter zu verhalten.

Technik: `Agent.run_turn()` ist synchron/blockierend (Ollama-HTTP-Streaming, Bash-/Lint-/Test-Subprozesse).
Textual selbst läuft in einer asyncio-Schleife im Haupt-Thread; `run_turn()` läuft deshalb in einem
Worker-Thread (`App.run_worker(..., thread=True)`), jede UI-Aktualisierung aus diesem Thread geht über
`App.call_from_thread(...)` zurück auf den Haupt-Thread – Textuals eigener Mechanismus dafür, damit die
Oberfläche auch während langer Modell-/Werkzeugaufrufe reaktionsfähig bleibt.

Testbarkeit: Die eigentliche Logik (TuiUI, die Rückfrage-Brücke für Permissions, das Einhängen der
Diff-Vorschau in Write/Edit) hängt nur von einem duck-typed 'app'-Objekt ab (call_from_thread/append_log/
set_diff/request_confirmation) und ist daher ohne installiertes Textual vollständig testbar. Nur die
eigentliche `PandoraTuiApp`-Klasse (echte Widgets/CSS) und `launch_tui` brauchen echtes Textual und sind
entsprechend hinter TEXTUAL_AVAILABLE abgeschottet.
"""
from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass, field

from . import summarize_args

NEON_VIOLET = "#9D00FF"
CYAN = "#00E5FF"
MAX_RESULT_LINES = 8
MAX_LINE_CHARS = 160

INSTALL_HINT = (
    "Die TUI braucht das optionale Paket 'textual'. Installieren mit: pip install 'pandora-code[tui]' "
    "(oder: pip install textual). Ohne Textual einfach normal starten: pandora code"
)

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Footer, Header, Input, Static

    try:
        from textual.widgets import RichLog as LogWidget  # Textual >= 0.42
    except ImportError:  # pragma: no cover - ältere Textual-Version
        from textual.widgets import TextLog as LogWidget  # type: ignore

    TEXTUAL_AVAILABLE = True
except Exception:  # pragma: no cover - optionale Abhängigkeit, absichtlich weit gefasst
    TEXTUAL_AVAILABLE = False


# -- Textual-unabhängige Logik (voll testbar ohne installiertes Textual) ----------------------------------
class TuiUI:
    """Ersetzt pandora_code.ui.UI, sobald der Agent unter der TUI läuft: dieselben Methoden
    (begin_assistant/thinking/stream/end_assistant/tool_call/tool_result/info/error), aber jede
    Aktualisierung geht thread-sicher über `app.call_from_thread(app.append_log, ...)`."""

    def __init__(self, app) -> None:
        self.app = app
        self._was_thinking = False

    def begin_assistant(self) -> None:
        self._was_thinking = False

    def thinking(self, text: str) -> None:
        self._was_thinking = True
        self.app.call_from_thread(self.app.append_log, text, "dim")

    def stream(self, text: str) -> None:
        if self._was_thinking:
            self._was_thinking = False
            self.app.call_from_thread(self.app.append_log, "\n", "")
        self.app.call_from_thread(self.app.append_log, text, "")

    def end_assistant(self) -> None:
        self.app.call_from_thread(self.app.append_log, "\n", "")

    def tool_call(self, name: str, args: dict) -> None:
        self.app.call_from_thread(self.app.append_log, f"\n● {name}({summarize_args(args)})\n", "bold")

    def tool_result(self, result: str) -> None:
        lines = result.splitlines() or [""]
        shown = "\n".join(
            ("  ⎿ " if i == 0 else "    ") + line[:MAX_LINE_CHARS] for i, line in enumerate(lines[:MAX_RESULT_LINES])
        )
        if len(lines) > MAX_RESULT_LINES:
            shown += f"\n    … (+{len(lines) - MAX_RESULT_LINES} Zeilen)"
        self.app.call_from_thread(self.app.append_log, shown + "\n", "dim")

    def info(self, text: str) -> None:
        self.app.call_from_thread(self.app.append_log, text + "\n", "dim")

    def error(self, text: str) -> None:
        self.app.call_from_thread(self.app.append_log, text + "\n", "bold red")


@dataclass
class ConfirmRequest:
    """Trägt eine Rückfrage (Permissions.ask) über den Thread hinweg: der Worker-Thread wartet auf
    `event`, der Haupt-Thread (Eingabezeile) trägt die Antwort ein und setzt das Event."""
    prompt: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: str = "n"


def make_tui_show(app):
    """Für Permissions(show=...): zeigt die Diff-/Befehlsvorschau im rechten Panel, bevor gefragt wird."""

    def show(preview: str) -> None:
        app.call_from_thread(app.set_diff, preview)

    return show


def make_tui_ask(app):
    """Für Permissions(ask=...): blockiert den Worker-Thread, bis die Eingabezeile im Haupt-Thread eine
    Antwort entgegengenommen hat (siehe PandoraTuiApp.request_confirmation)."""

    def ask(prompt: str) -> str:
        request = ConfirmRequest(prompt)
        app.call_from_thread(app.request_confirmation, request)
        request.event.wait()
        return request.answer

    return ask


def wrap_diff_tool(original, app):
    """Hüllt Write/Edit so ein, dass ihr Diff (Tool.preview) unabhängig vom Berechtigungsmodus im rechten
    Panel erscheint – auch in yolo/accept-edits, wo Permissions.show() sonst nie aufgerufen wird."""
    if original.preview is None:
        return original

    def run(ctx, args):
        try:
            diff = original.preview(ctx, args)
        except Exception:
            diff = ""
        result = original.run(ctx, args)
        if diff and not result.startswith("Fehler"):
            app.call_from_thread(app.set_diff, diff)
        return result

    return dataclasses.replace(original, run=run)


def attach(agent, app) -> None:
    """Verdrahtet einen bereits fertig gebauten Agenten mit der TUI: tauscht agent.ui und die
    Permissions-Rückfragen aus und hüllt Write/Edit für die Diff-Vorschau ein. Wird von launch_tui()
    aufgerufen, nachdem cli.main() den Agenten wie gewohnt mit der Konsolen-UI gebaut hat – so bleibt die
    ganze Modell-/Registry-/Erweiterungs-Auflösung in main() unverändert wiederverwendbar."""
    agent.ui = TuiUI(app)
    agent.perms.show = make_tui_show(app)
    agent.perms.ask = make_tui_ask(app)
    for name in ("Write", "Edit"):
        tool = agent.tools.get(name)
        if tool is not None:
            agent.add_tool(wrap_diff_tool(tool, app))


# -- Echte Textual-App (nur mit installiertem Textual definiert) ------------------------------------------
if TEXTUAL_AVAILABLE:

    class PandoraTuiApp(App):
        CSS = f"""
        Screen {{ background: $surface; }}
        #body {{ height: 1fr; }}
        #left {{ width: 1fr; border: round {NEON_VIOLET}; padding: 0 1; }}
        #right {{ width: 1fr; border: round {CYAN}; padding: 0 1; }}
        #status {{ height: 1; color: {CYAN}; padding: 0 1; }}
        #status .model {{ color: {NEON_VIOLET}; text-style: bold; }}
        Input {{ border: round {NEON_VIOLET}; }}
        """
        BINDINGS = [("ctrl+c", "quit", "Beenden")]

        def __init__(self, agent, first_prompt: str | None = None) -> None:
            super().__init__()
            self.agent = agent
            self._first_prompt = first_prompt
            self._pending: ConfirmRequest | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                yield LogWidget(id="left", highlight=False, markup=False, wrap=True)
                yield LogWidget(id="right", highlight=False, markup=False, wrap=True)
            yield Static(self._status_text(), id="status")
            yield Input(placeholder="Nachricht an Pandora Code …", id="prompt")
            yield Footer()

        def on_mount(self) -> None:
            attach(self.agent, self)
            self.query_one("#left", LogWidget).write(
                "Pandora Code TUI – Ctrl+C zum Beenden. Rechts erscheint der Diff der zuletzt "
                "geänderten Datei.\n"
            )
            if self._first_prompt:
                self.submit_prompt(self._first_prompt)

        def _status_text(self):
            from rich.text import Text
            text = Text()
            text.append(" Modell: ", style=CYAN)
            text.append(self.agent.model, style=f"bold {NEON_VIOLET}")
            text.append("  Modus: ", style=CYAN)
            text.append(self.agent.perms.mode, style=f"bold {NEON_VIOLET}")
            text.append("  Verzeichnis: ", style=CYAN)
            text.append(str(self.agent.ctx.cwd), style="white")
            return text

        def append_log(self, text: str, style: str = "") -> None:
            log = self.query_one("#left", LogWidget)
            if style:
                from rich.text import Text
                log.write(Text(text, style=style))
            else:
                log.write(text)

        def set_diff(self, text: str) -> None:
            panel = self.query_one("#right", LogWidget)
            panel.clear()
            panel.write(text or "(keine Änderung)")

        def request_confirmation(self, request: ConfirmRequest) -> None:
            self._pending = request
            prompt_input = self.query_one("#prompt", Input)
            prompt_input.placeholder = request.prompt
            self.append_log(f"\n{request.prompt}\n", "bold " + NEON_VIOLET)

        def on_input_submitted(self, event) -> None:  # noqa: ANN001 - Textual-Event-Objekt
            event.input.value = ""
            if self._pending is not None:
                request, self._pending = self._pending, None
                request.answer = event.value.strip().lower() or "n"
                self.query_one("#prompt", Input).placeholder = "Nachricht an Pandora Code …"
                request.event.set()
                return
            text = event.value.strip()
            if text:
                self.submit_prompt(text)

        def submit_prompt(self, text: str) -> None:
            self.append_log(f"\n> {text}\n", "bold " + CYAN)
            self.run_worker(lambda: self._run_turn(text), thread=True, exclusive=True)

        def _run_turn(self, text: str) -> None:
            try:
                self.agent.run_turn(text)
            except Exception as err:  # Fehler landen im Log statt die App abzuschießen
                self.call_from_thread(self.append_log, f"\nFehler: {err}\n", "bold red")
            finally:
                self.call_from_thread(self.query_one("#status", Static).update, self._status_text())

    def launch_tui(agent, first_prompt: str | None = None) -> None:
        PandoraTuiApp(agent, first_prompt).run()

else:  # pragma: no cover - nur ohne installiertes Textual relevant

    def launch_tui(agent, first_prompt: str | None = None) -> None:
        raise RuntimeError(INSTALL_HINT)
