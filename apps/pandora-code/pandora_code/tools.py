"""Werkzeuge des Agenten – gleiche Namen und Semantik wie bei Claude Code."""
from __future__ import annotations

import difflib
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .images import IMAGE_EXTENSIONS, ImageError, encode_image

MAX_OUTPUT = 12000  # Zeichen pro Tool-Ergebnis (das Kontextfenster lokaler Modelle ist knapp)
MAX_MATCHES = 200
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".mypy_cache", ".pytest_cache"}


class ToolError(Exception):
    """Erwarteter Fehler; die Meldung geht als Ergebnis an das Modell zurück."""


@dataclass
class ToolContext:
    cwd: Path
    read_files: set[str] = field(default_factory=set)
    todos: list[dict] = field(default_factory=list)
    pending_images: list[str] = field(default_factory=list)  # Base64-Bilder, die als nächste Nachricht ans Modell gehen

    def resolve(self, value: object) -> Path:
        if not value:
            raise ToolError("Pfad fehlt.")
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.cwd / path
        return path.resolve()


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[ToolContext, dict], str]
    mutating: bool = False
    preview: Callable[[ToolContext, dict], str] | None = None
    modes: tuple[str, ...] | None = None  # None = in jedem Berechtigungsmodus sichtbar

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# -- Hilfsfunktionen ---------------------------------------------------------
def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} Zeichen gekürzt]"


def as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "ja")
    return bool(value)


def as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required)}


def compile_glob(pattern: str) -> re.Pattern[str]:
    """Wandelt ein Glob-Muster (mit **, ?, {a,b}) in einen regulären Ausdruck um."""
    if "/" not in pattern:
        pattern = "**/" + pattern
    out, depth, i = "", 0, 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        char = pattern[i]
        if char == "*":
            out += "[^/]*"
        elif char == "?":
            out += "[^/]"
        elif char == "{":
            out += "(?:"
            depth += 1
        elif char == "}" and depth:
            out += ")"
            depth -= 1
        elif char == "," and depth:
            out += "|"
        else:
            out += re.escape(char)
        i += 1
    return re.compile(out + r"\Z")


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def render_todos(todos: list[dict]) -> str:
    marks = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    return "\n".join(f"{marks[t['status']]} {t['content']}" for t in todos) or "(leer)"


def unified_diff(path: Path, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(True), after.splitlines(True), f"{path} (alt)", f"{path} (neu)", n=2
    )
    return "".join(diff) or f"{path}: keine Änderung"


# -- Werkzeuge -----------------------------------------------------------------
def read_tool(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("file_path"))
    if not path.is_file():
        raise ToolError(f"Datei nicht gefunden: {path}")
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        try:
            ctx.pending_images.append(encode_image(path))
        except (ImageError, OSError) as err:
            raise ToolError(f"Bild {path.name}: {err}") from None
        return f"[Bild {path.name} – wird dem Modell als nächste Nachricht angehängt]"
    raw = path.read_bytes()
    if b"\0" in raw[:8192]:
        raise ToolError("Binärdatei – kann nicht als Text gelesen werden.")
    lines = raw.decode("utf-8", "replace").splitlines()
    ctx.read_files.add(str(path))
    offset = max(as_int(args.get("offset"), 0), 0)
    limit = max(as_int(args.get("limit"), 2000), 1)
    chunk = lines[offset : offset + limit]
    if not lines:
        return "(leere Datei)"
    if not chunk:
        return f"(keine Zeilen ab Offset {offset}; die Datei hat {len(lines)} Zeilen)"
    numbered = "\n".join(f"{n:>6}\t{line[:2000]}" for n, line in enumerate(chunk, start=offset + 1))
    return clip(numbered)


def write_tool(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("file_path"))
    content = args.get("content")
    if content is None:
        raise ToolError("'content' fehlt.")
    content = str(content)
    if path.exists() and str(path) not in ctx.read_files:
        raise ToolError("Die Datei existiert bereits – bitte zuerst mit Read lesen.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ctx.read_files.add(str(path))
    return f"{path} geschrieben ({len(content.splitlines())} Zeilen)."


def edit_tool(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("file_path"))
    old, new = args.get("old_string"), args.get("new_string")
    if not old or new is None:
        raise ToolError("'old_string' (nicht leer) und 'new_string' sind Pflicht.")
    old, new = str(old), str(new)
    if old == new:
        raise ToolError("old_string und new_string sind identisch.")
    if not path.is_file():
        raise ToolError(f"Datei nicht gefunden: {path}")
    if str(path) not in ctx.read_files:
        raise ToolError("Bitte die Datei zuerst mit Read lesen.")
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ToolError("old_string nicht gefunden (Whitespace und Einrückung exakt übernehmen).")
    replace_all = as_bool(args.get("replace_all"))
    if count > 1 and not replace_all:
        raise ToolError(f"old_string kommt {count}× vor – mehr Kontext angeben oder replace_all=true setzen.")
    path.write_text(text.replace(old, new) if replace_all else text.replace(old, new, 1), encoding="utf-8")
    return f"{path}: {count if replace_all else 1} Ersetzung(en)."


def preview_write(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("file_path"))
    before = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return unified_diff(path, before, str(args.get("content", "")))


def preview_edit(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("file_path"))
    before = path.read_text(encoding="utf-8", errors="replace")
    old, new = str(args.get("old_string", "")), str(args.get("new_string", ""))
    after = before.replace(old, new) if as_bool(args.get("replace_all")) else before.replace(old, new, 1)
    return unified_diff(path, before, after)


def bash_backend() -> tuple[list[str] | None, str]:
    """Ermittelt, wie das Bash-Werkzeug Befehle tatsächlich ausführt, und eine kurze, für den
    System-Prompt gedachte Beschreibung davon (siehe agent.ENV_BLOCK/describe_shell unten).

    Unter Linux/macOS bleibt es bei der nativen POSIX-Shell (shell=True, unverändert). Unter Windows
    schreiben lokale Coder-Modelle so gut wie immer Bash-Syntax (ls, rm, cat, Pipes wie unter Unix), weil
    ihre Trainingsdaten weit überwiegend POSIX sind – purer 'shell=True' würde dort cmd.exe aufrufen und
    praktisch jeden vom Modell geschriebenen Befehl scheitern lassen. Deshalb wird zuerst nach einer echten
    Bash gesucht (Git Bash oder WSL, beide bringen ein 'bash.exe' im PATH mit, wenn installiert): wird sie
    gefunden, führt das Werkzeug Befehle explizit darüber aus (['bash','-c',command], shell=False), sodass
    normale Bash-Befehle wie gewohnt funktionieren. Ohne gefundene Bash bleibt nur die native cmd.exe übrig
    (shell=True) – der System-Prompt weist das Modell dann ausdrücklich auf Windows-Befehle hin, statt es
    einfach raten zu lassen.
    """
    if platform.system() == "Windows":
        bash = shutil.which("bash")
        if bash:
            return [bash, "-c"], "Bash (Git Bash/WSL gefunden) – normale Bash-Befehle funktionieren."
        return None, ("kein Bash gefunden – das Bash-Werkzeug läuft über cmd.exe: nutze Windows-Befehle "
                      "(dir, del, type, copy, move, ...) oder starte PowerShell ausdrücklich mit "
                      "'powershell -NoProfile -Command \"...\"'.")
    return None, "POSIX-Shell (bash/sh) – normale Unix-Befehle funktionieren."


def describe_shell() -> str:
    """Nur die Beschreibung aus bash_backend(), für den System-Prompt (agent.py)."""
    return bash_backend()[1]


def preview_bash(ctx: ToolContext, args: dict) -> str:
    return f"$ {args.get('command', '')}"


def bash_tool(ctx: ToolContext, args: dict) -> str:
    command = args.get("command")
    if not command:
        raise ToolError("'command' fehlt.")
    timeout = min(max(as_int(args.get("timeout"), 120), 1), 600)
    prefix, _ = bash_backend()
    argv = [*prefix, str(command)] if prefix else str(command)
    try:
        proc = subprocess.run(
            argv,
            shell=prefix is None,
            cwd=ctx.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return f"Abbruch: Zeitlimit von {timeout}s überschritten."
    output = proc.stdout or ""
    if proc.stderr:
        output += ("\n" if output else "") + "[stderr]\n" + proc.stderr
    return clip(output.strip() or "(keine Ausgabe)") + f"\n[Exit-Code {proc.returncode}]"


def glob_tool(ctx: ToolContext, args: dict) -> str:
    pattern = args.get("pattern")
    if not pattern:
        raise ToolError("'pattern' fehlt.")
    root = ctx.resolve(args.get("path") or ".")
    if not root.is_dir():
        raise ToolError(f"Kein Verzeichnis: {root}")
    rx = compile_glob(str(pattern))
    hits = [p for p in iter_files(root) if rx.match(p.relative_to(root).as_posix())]
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    lines = [p.relative_to(root).as_posix() for p in hits[:MAX_MATCHES]]
    if len(hits) > MAX_MATCHES:
        lines.append(f"… und {len(hits) - MAX_MATCHES} weitere")
    return "\n".join(lines) or "Keine Treffer."


def grep_tool(ctx: ToolContext, args: dict) -> str:
    pattern = args.get("pattern")
    if not pattern:
        raise ToolError("'pattern' fehlt.")
    try:
        rx = re.compile(str(pattern), re.IGNORECASE if as_bool(args.get("case_insensitive")) else 0)
    except re.error as err:
        raise ToolError(f"Ungültiger regulärer Ausdruck: {err}") from None
    root = ctx.resolve(args.get("path") or ".")
    file_rx = compile_glob(str(args["glob"])) if args.get("glob") else None
    single = root.is_file()
    results: list[str] = []
    for path in [root] if single else iter_files(root):
        rel = path.name if single else path.relative_to(root).as_posix()
        if file_rx and not file_rx.match(rel):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192] or len(data) > 2_000_000:
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
            if rx.search(line):
                results.append(f"{rel}:{number}:{line[:300]}")
                if len(results) >= MAX_MATCHES:
                    break
        if len(results) >= MAX_MATCHES:
            break
    return clip("\n".join(results)) or "Keine Treffer."


def ls_tool(ctx: ToolContext, args: dict) -> str:
    path = ctx.resolve(args.get("path") or ".")
    if not path.is_dir():
        raise ToolError(f"Kein Verzeichnis: {path}")
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries[:500]) or "(leer)"


def todo_tool(ctx: ToolContext, args: dict) -> str:
    todos = args.get("todos")
    if not isinstance(todos, list):
        raise ToolError("'todos' muss eine Liste sein.")
    clean = []
    for item in todos:
        if not isinstance(item, dict):
            item = {"content": str(item)}
        status = item.get("status")
        clean.append(
            {
                "content": str(item.get("content", "")),
                "status": status if status in ("pending", "in_progress", "completed") else "pending",
            }
        )
    ctx.todos = clean
    return "Todo-Liste aktualisiert:\n" + render_todos(clean)


def build_tools() -> dict[str, Tool]:
    path_prop = {"type": "string", "description": "File path (absolute or relative to the working directory)"}
    tools = [
        Tool(
            "Read",
            "Read a text file. Returns numbered lines. Always read a file before editing it.",
            schema(
                {
                    "file_path": path_prop,
                    "offset": {"type": "integer", "description": "Line to start from (0-based)"},
                    "limit": {"type": "integer", "description": "Maximum number of lines (default 2000)"},
                },
                ("file_path",),
            ),
            read_tool,
        ),
        Tool(
            "Write",
            "Create a file or fully overwrite an existing one (existing files must be read first).",
            schema({"file_path": path_prop, "content": {"type": "string", "description": "Complete file content"}},
                   ("file_path", "content")),
            write_tool,
            mutating=True,
            preview=preview_write,
        ),
        Tool(
            "Edit",
            "Replace an exact string in a file. old_string must be unique unless replace_all is true.",
            schema(
                {
                    "file_path": path_prop,
                    "old_string": {"type": "string", "description": "Exact text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence"},
                },
                ("file_path", "old_string", "new_string"),
            ),
            edit_tool,
            mutating=True,
            preview=preview_edit,
        ),
        Tool(
            "Bash",
            "Run a shell command in the working directory and return stdout, stderr and exit code.",
            schema(
                {
                    "command": {"type": "string", "description": "The command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 600)"},
                },
                ("command",),
            ),
            bash_tool,
            mutating=True,
            preview=preview_bash,
        ),
        Tool(
            "Glob",
            "Find files by glob pattern, e.g. '**/*.py' or 'src/**/*.{js,ts}'. Newest first.",
            schema(
                {"pattern": {"type": "string", "description": "Glob pattern"},
                 "path": {"type": "string", "description": "Directory to search (default: working directory)"}},
                ("pattern",),
            ),
            glob_tool,
        ),
        Tool(
            "Grep",
            "Search file contents with a regular expression. Returns file:line:text.",
            schema(
                {
                    "pattern": {"type": "string", "description": "Regular expression"},
                    "path": {"type": "string", "description": "File or directory (default: working directory)"},
                    "glob": {"type": "string", "description": "Only search files matching this glob, e.g. '*.py'"},
                    "case_insensitive": {"type": "boolean", "description": "Ignore case"},
                },
                ("pattern",),
            ),
            grep_tool,
        ),
        Tool(
            "LS",
            "List the entries of a directory (directories end with '/').",
            schema({"path": {"type": "string", "description": "Directory (default: working directory)"}}),
            ls_tool,
        ),
        Tool(
            "TodoWrite",
            "Create or update the task list for multi-step work. Send the complete list every time.",
            schema(
                {
                    "todos": {
                        "type": "array",
                        "description": "All tasks",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            },
                            "required": ["content", "status"],
                        },
                    }
                },
                ("todos",),
            ),
            todo_tool,
        ),
    ]
    return {tool.name: tool for tool in tools}
