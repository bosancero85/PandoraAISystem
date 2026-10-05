"""Editierbarer Zusatz-Prompt (prompt.md) und das Playbook-Verzeichnis.

Der Prompt liegt als Textdatei vor und wird bei jeder Anfrage neu gelesen – Änderungen wirken sofort.
Reihenfolge: Projekt (.pandora/prompt.md) vor Benutzer (~/.pandora/prompt.md). Beim ersten Start wird die
Benutzer-Datei mit dem Standardtext angelegt; wer sie löscht, bekommt sie beim nächsten Start neu.
"""
from __future__ import annotations

from pathlib import Path

from .config import home_dir

PROMPT_FILE = "prompt.md"
PLAYBOOK_DIR = "playbook"
MAX_PROMPT_CHARS = 12000
TEMPLATE_DIR = Path(__file__).parent / "playbook_template"

DEFAULT_PROMPT = """\
Ab jetzt bist du ein kompromissloser, strukturierter Projekt-Assistent. Deine Hauptaufgabe ist es, Aufgaben nicht \
nach Gefühl zu beenden, sondern sie mathematisch präzise abzuarbeiten. Für jedes Projekt, jede komplexe Aufgabe und \
jeden Code-Block gilt ab sofort folgende strikte Routine:

1. PROJEKT-START: Bevor du mit der eigentlichen Arbeit beginnst oder Text/Code generierst, erstellst du eine \
detaillierte, nummerierte Checkliste aller notwendigen Teilschritte (inklusive Qualitätskontrolle, Tests und \
Formatierung).
2. STATUS-ANZEIGE: Zeige diese Checkliste dem Nutzer an. Alle Punkte stehen initial auf [ ] (Offen).
3. SYSTEMATISCHE ABARBEITUNG: Du bearbeitest die Liste strikt von oben nach unten. Du darfst niemals Schritte \
überspringen oder zusammenfassen. Den aktuellen Stand hältst du in playbook/session_handoff.md fest.
4. KEINE VORZEITIGEN ABHAKUNGEN: Ein Schritt gilt erst als [X] (Erledigt), wenn das Ergebnis vollständig generiert, \
überprüft und fehlerfrei ist. "Gut genug" oder "Den Rest kann der Nutzer machen" ist strikt untersagt.
5. ZWISCHENSTAND: Zeige nach jedem größeren Arbeitsschritt den aktuellen Status der Checkliste an, damit der \
Fortschritt transparent bleibt.
6. ABSCHLUSS: Erst wenn ALLE Punkte der Checkliste auf [X] stehen, erklärst du das Projekt für beendet. Fertige \
ein GitHub-Repo mit LICENSE, README.de.md und .gitignore.

Wenn du diese Routine verwaltest, antworte im ersten Schritt immer so:
"Projekt verstanden. Hier ist die verbindliche Checkliste, die ich nun Schritt für Schritt abarbeite: ..."

PLAYBOOK: Existiert im Arbeitsverzeichnis der Ordner playbook/, halte dich zusätzlich an playbook/playbook.md und \
die dort genannten Dateien (ablage.md, fertige_definition.md, interview.md, project.toml, session_handoff.md). \
Führe die Checkliste mit dem Werkzeug TodoWrite.
"""


def prompt_candidates(cwd: Path) -> list[Path]:
    return [cwd / ".pandora" / PROMPT_FILE, home_dir() / PROMPT_FILE]


def active_prompt_path(cwd: Path) -> Path | None:
    return next((p for p in prompt_candidates(cwd) if p.is_file()), None)


def ensure_default_prompt() -> Path | None:
    """Legt ~/.pandora/prompt.md mit dem Standardtext an, falls sie fehlt. Nie überschreiben."""
    path = home_dir() / PROMPT_FILE
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_PROMPT, encoding="utf-8")
    except OSError:
        return None
    return path


def load_user_prompt(cwd: Path) -> str:
    path = active_prompt_path(cwd)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[:MAX_PROMPT_CHARS]
    except OSError:
        return ""


def install_playbook(cwd: Path) -> tuple[list[str], list[str]]:
    """Kopiert die Playbook-Vorlage nach <cwd>/playbook/. Vorhandene Dateien bleiben unberührt.

    Gibt (neu angelegt, übersprungen) zurück.
    """
    target = cwd / PLAYBOOK_DIR
    created: list[str] = []
    skipped: list[str] = []
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(TEMPLATE_DIR.iterdir()):
        if not source.is_file():
            continue
        destination = target / source.name
        if destination.exists():
            skipped.append(source.name)
            continue
        destination.write_bytes(source.read_bytes())
        created.append(source.name)
    return created, skipped
