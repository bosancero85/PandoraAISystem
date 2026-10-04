"""Auto-Fix & Continuous Quality Loop: der Agent korrigiert sich nach jeder Änderung selbst.

Zwei Mechanismen, beide ohne jede Konfiguration nutzbar (erkennen installierte Programme automatisch):

1. **Lint nach jeder Änderung**: nach jedem erfolgreichen `Write`/`Edit` läuft sofort ein passender Linter
   auf genau diese Datei (Python: `ruff`, sonst `flake8`; JS/TS: `eslint` – jeweils nur wenn installiert).
   Meldet er Probleme, werden sie direkt an das Werkzeug-Ergebnis angehängt – der Agent sieht das im
   selben Zug (ReAct-Schleife) und kann sofort reagieren, ganz ohne Zusatzkonfiguration oder Warteschleife.

2. **Tests vor jedem Stopp**: bevor der Agent seinen Zug für beendet erklärt, UND nur wenn seit dem letzten
   grünen Lauf tatsächlich eine Datei geändert wurde, läuft einmal der erkannte Test-Runner (pytest bzw.
   npm test, je nachdem welche Markerdatei im Projekt liegt). Schlägt er fehl, wird der Stopp blockiert und
   die Fehlerausgabe als neues Problem zurückgegeben – wie ein Stop-Hook. Der Agent arbeitet weiter, bis die
   Tests grün sind oder das eingebaute Limit an Weiterarbeits-Versuchen erreicht ist (agent.MAX_STOP_CONTINUATIONS,
   Standard 3) – kein Risiko einer Endlosschleife.

Ersetzt keine bereits konfigurierten Hooks aus `extensions/hooks.py` (`settings.json` -> `"hooks"`), sondern
verkettet sich davor/dahinter: beide Mechanismen bleiben unabhängig nutzbar.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

LINT_TIMEOUT = 30
TEST_TIMEOUT = 180

# Sprache -> [(Programmname, Befehlsvorlage), ...] in Präferenzreihenfolge; '{file}' = Pfad relativ zum Projekt.
# Das erste tatsächlich installierte Programm gewinnt.
LINTERS: dict[str, list[tuple[str, str]]] = {
    ".py": [("ruff", "ruff check --quiet {file}"), ("flake8", "flake8 {file}")],
    ".js": [("eslint", "eslint {file}")],
    ".jsx": [("eslint", "eslint {file}")],
    ".ts": [("eslint", "eslint {file}")],
    ".tsx": [("eslint", "eslint {file}")],
}
# (Markerdatei im Projekt, Programmname, Befehl) in Präferenzreihenfolge.
TEST_RUNNERS: list[tuple[str, str, str]] = [
    ("pytest.ini", "pytest", "pytest -q"),
    ("pyproject.toml", "pytest", "pytest -q"),
    ("setup.py", "pytest", "pytest -q"),
    ("package.json", "npm", "npm test --silent"),
]


def which(name: str) -> bool:
    return shutil.which(name) is not None


def pick_linter(path: Path) -> tuple[str, str] | None:
    for program, template in LINTERS.get(path.suffix, []):
        if which(program):
            return program, template
    return None


def pick_test_runner(root: Path) -> tuple[str, str] | None:
    for marker, program, command in TEST_RUNNERS:
        if (root / marker).exists() and which(program):
            return program, command
    return None


def run_command(command: str, cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return -1, f"Zeitlimit ({timeout}s) überschritten: {command}"
    except OSError as err:
        return -1, str(err)
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, output.strip()


@dataclass
class AutoFixState:
    enabled: bool = True
    lint_enabled: bool = True
    test_enabled: bool = True
    test_command_override: str | None = None
    dirty: bool = False  # seit dem letzten grünen Testlauf wurde eine Datei geändert
    last_test_ok: bool | None = None  # None = noch nie gelaufen


def lint_file(root: Path, rel_path: str, state: AutoFixState) -> str | None:
    if not (state.enabled and state.lint_enabled):
        return None
    path = root / rel_path
    if not path.is_file():
        return None
    picked = pick_linter(path)
    if not picked:
        return None
    program, template = picked
    code, output = run_command(template.format(file=rel_path), root, LINT_TIMEOUT)
    if code == 0:
        return None
    return f"[Auto-Fix: {program} meldet Probleme in {rel_path}]\n{output or f'(keine Ausgabe, Exit-Code {code})'}"


def run_tests(root: Path, state: AutoFixState) -> str | None:
    if not (state.enabled and state.test_enabled):
        return None
    if state.test_command_override:
        program, command = "Test", state.test_command_override
    else:
        picked = pick_test_runner(root)
        if not picked:
            return None
        program, command = picked
    code, output = run_command(command, root, TEST_TIMEOUT)
    state.last_test_ok = code == 0
    if code == 0:
        return None
    return f"[Auto-Fix] Tests schlagen fehl ({program}):\n{output or f'(keine Ausgabe, Exit-Code {code})'}"


def _relative_changed_path(ctx, args: dict) -> str | None:
    value = args.get("file_path")
    if not value:
        return None
    try:
        path = ctx.resolve(value)
        return str(path.relative_to(ctx.cwd))
    except (ValueError, OSError, Exception):  # außerhalb des Projekts oder ungültiger Pfad -> ignorieren
        return None


class AutoFixHookRunner:
    """Duck-typed wie extensions.hooks.HookRunner (pre_tool/post_tool/user_prompt/stop); verkettet sich vor
    einen bereits vorhandenen HookRunner, statt ihn zu ersetzen (`inner`, None falls keiner installiert ist
    oder die Erweiterung 'hooks' per --disable abgeschaltet wurde)."""

    def __init__(self, agent, state: AutoFixState, inner=None) -> None:
        self.agent = agent
        self.state = state
        self.inner = inner

    @property
    def config(self) -> dict:
        """Durchreichung für extensions/hooks.py's `/hooks`-Befehl (`agent.hooks.config`), damit der nach dem
        Verketten weiterhin die konfigurierten Hooks anzeigen kann, statt nur die von Auto-Fix selbst."""
        return self.inner.config if self.inner is not None else {}

    def pre_tool(self, name: str, args: dict):
        return self.inner.pre_tool(name, args) if self.inner else None

    def user_prompt(self, prompt: str):
        return self.inner.user_prompt(prompt) if self.inner else (None, "")

    def post_tool(self, name: str, args: dict, response: str) -> str:
        feedback: list[str] = []
        if name in ("Write", "Edit") and not response.startswith("Fehler"):
            rel = _relative_changed_path(self.agent.ctx, args)
            if rel:
                self.state.dirty = True
                note = lint_file(self.agent.ctx.cwd, rel, self.state)
                if note:
                    feedback.append(note)
        if self.inner:
            inner_feedback = self.inner.post_tool(name, args, response)
            if inner_feedback:
                feedback.append(inner_feedback)
        return "\n".join(feedback)

    def stop(self, active: bool):
        if self.inner:
            reason = self.inner.stop(active)
            if reason is not None:
                return reason
        if not self.state.dirty:
            return None  # diese Runde wurde keine Datei geändert -> nichts zu testen
        note = run_tests(self.agent.ctx.cwd, self.state)
        if note is None:
            self.state.dirty = False  # grün (oder kein Runner gefunden) -> bis zur nächsten Änderung Ruhe
        return note  # bleibt 'dirty', bis die Tests grün sind -> nächster Stopp-Versuch prüft erneut


def install(agent, settings) -> None:
    state = AutoFixState(
        enabled=bool(getattr(settings, "auto_fix", True)),
        lint_enabled=bool(getattr(settings, "auto_fix_lint", True)),
        test_enabled=bool(getattr(settings, "auto_fix_test", True)),
        test_command_override=getattr(settings, "auto_fix_test_command", None),
    )
    agent.hooks = AutoFixHookRunner(agent, state, inner=getattr(agent, "hooks", None))

    def autofix_command(arg: str, agent, ui) -> str | None:
        choice = arg.strip().lower()
        toggles = {
            "an": ("enabled", True), "on": ("enabled", True), "aus": ("enabled", False), "off": ("enabled", False),
            "lint-an": ("lint_enabled", True), "lint-aus": ("lint_enabled", False),
            "test-an": ("test_enabled", True), "test-aus": ("test_enabled", False),
        }
        if choice:
            if choice not in toggles:
                ui.error("Nutzung: /autofix [an|aus|lint-an|lint-aus|test-an|test-aus]")
                return None
            attr, value = toggles[choice]
            setattr(state, attr, value)
        linters = sorted({program for entries in LINTERS.values() for program, _ in entries if which(program)})
        runner = pick_test_runner(agent.ctx.cwd)
        lines = [
            f"Auto-Fix: {'an' if state.enabled else 'aus'} "
            f"(Lint: {'an' if state.lint_enabled else 'aus'}, Tests: {'an' if state.test_enabled else 'aus'})",
            f"  Verfügbare Linter: {', '.join(linters) or 'keiner gefunden'}",
            f"  Erkannter Test-Runner: {state.test_command_override or (runner[1] if runner else 'keiner erkannt')}",
        ]
        if state.last_test_ok is not None:
            lines.append(f"  Letzter Testlauf: {'grün ✓' if state.last_test_ok else 'rot ✗'}")
        ui.info("\n".join(lines))
        return None

    agent.register_command(
        "autofix", autofix_command,
        "/autofix [an|aus|lint-an|lint-aus|test-an|test-aus]  Lint nach Änderungen & Testlauf vor jedem Stopp",
    )
