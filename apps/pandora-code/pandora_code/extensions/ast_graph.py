"""AST-Code-Graph-Engine: strukturelles Verständnis der Codebasis statt reiner Text-/Grep-Suche.

Beantwortet gezielte Fragen wie "Zeige mir alle Aufrufer von Funktion X" oder "Finde die Klassendefinition
von Y" unabhängig von Formatierung oder Kommentaren – Grep findet auch Treffer in Strings/Kommentaren und
kennt den Unterschied zwischen Definition und Aufruf nicht; der Graph schon.

Backends je Datei:
- Python (.py): das eingebaute `ast`-Modul – exakt, ohne zusätzliche Abhängigkeit.
- JavaScript/TypeScript, C/C++, Lua u. a.: Tree-sitter, WENN installiert (optionale Abhängigkeit,
  `pip install pandora-code[ast]` bzw. `tree_sitter` + `tree-sitter-languages`). Ohne Tree-sitter greift ein
  regelbasierter Regex-Fallback (deutlich als 'ungefähr' gekennzeichnet) – die Engine funktioniert also auch
  ganz ohne zusätzliche Pakete, degradiert aber in der Genauigkeit für Nicht-Python-Sprachen.

Der Graph wird pro Sitzung einmal aufgebaut (lazy, beim ersten Werkzeugaufruf) und über `/graph` neu
aufgebaut; das hält es auf einem Raspberry Pi 4B schnell, auch bei mehreren aufeinanderfolgenden Anfragen.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..tools import Tool, ToolContext, ToolError, schema

try:
    from tree_sitter_languages import get_parser as _ts_get_parser  # type: ignore
    TREE_SITTER_AVAILABLE = True
except Exception:  # pragma: no cover - hängt von optionaler Installation ab
    TREE_SITTER_AVAILABLE = False

MAX_FILES = 4000  # Sicherung gegen Ausufern in Monorepos auf schwacher Hardware (Pi 4B)
MAX_FILE_BYTES = 1_500_000  # größere generierte Dateien (Bundles, Lockfiles) werden ausgelassen
EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env", "dist", "build", ".mypy_cache",
    ".pytest_cache", ".idea", ".vscode", "site-packages", "vendor", "target", ".tox", ".ruff_cache",
}

LANGUAGE_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".lua": "lua",
}
TS_LANGUAGE_NAME = {"javascript": "javascript", "typescript": "typescript", "c": "c", "cpp": "cpp", "lua": "lua"}

_KEYWORDS_NOT_CALLS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "new", "in", "of", "else",
    "do", "try", "sizeof", "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast",
}


@dataclass
class Symbol:
    kind: str  # "function" | "method" | "class"
    name: str
    qualname: str
    file: str
    line: int
    signature: str = ""
    backend: str = "ast"  # "ast" (Python) | "tree-sitter" | "regex" (ungefähr)


@dataclass
class CallSite:
    callee: str  # Name, wie er am Aufrufort steht (self.foo() -> "foo", obj.bar() -> "bar")
    caller_qualname: str | None  # umgebende Funktion/Methode, None = Modulebene
    file: str
    line: int
    backend: str = "ast"


@dataclass
class FileIndex:
    mtime: float
    language: str
    backend: str
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    error: str | None = None


@dataclass
class CodeGraph:
    root: Path
    files: dict[Path, FileIndex] = field(default_factory=dict)
    truncated: bool = False

    # -- Aufbau --------------------------------------------------------------------------
    def _iter_source_files(self):
        count = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix not in LANGUAGE_BY_EXT:
                continue
            if any(part in EXCLUDE_DIRS for part in path.relative_to(self.root).parts[:-1]):
                continue
            if count >= MAX_FILES:
                self.truncated = True
                return
            count += 1
            yield path

    def build(self) -> None:
        self.files.clear()
        self.truncated = False
        for path in self._iter_source_files():
            self._index_file(path)

    def refresh(self) -> tuple[int, int]:
        """Indiziert neue/geänderte Dateien nach; gibt (neu/geändert, gesamt) zurück."""
        seen: set[Path] = set()
        changed = 0
        for path in self._iter_source_files():
            seen.add(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            existing = self.files.get(path)
            if existing is None or existing.mtime != mtime:
                self._index_file(path)
                changed += 1
        for stale in set(self.files) - seen:
            del self.files[stale]
        return changed, len(self.files)

    def _index_file(self, path: Path) -> None:
        language = LANGUAGE_BY_EXT[path.suffix]
        try:
            mtime = path.stat().st_mtime
            if path.stat().st_size > MAX_FILE_BYTES:
                self.files[path] = FileIndex(mtime, language, "übersprungen", error="Datei zu groß")
                return
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            self.files[path] = FileIndex(0.0, language, "-", error=str(err))
            return
        rel = str(path.relative_to(self.root))
        if language == "python":
            symbols, calls, error = _index_python(text, rel)
            backend = "ast"
        elif TREE_SITTER_AVAILABLE:
            symbols, calls, error = _index_tree_sitter(text, rel, language)
            backend = "tree-sitter"
            if error:  # Grammatik nicht verfügbar/fehlgeschlagen -> auf Regex ausweichen
                symbols, calls, error = _index_regex(text, rel, language)
                backend = "regex"
        else:
            symbols, calls, error = _index_regex(text, rel, language)
            backend = "regex"
        self.files[path] = FileIndex(mtime, language, backend, symbols, calls, error)

    # -- Abfragen ---------------------------------------------------------------------
    def all_symbols(self):
        for info in self.files.values():
            yield from info.symbols

    def all_calls(self):
        for info in self.files.values():
            yield from info.calls

    def find_definitions(self, name: str) -> list[Symbol]:
        name_l = name.lower()
        exact = [s for s in self.all_symbols() if s.name == name or s.qualname == name]
        if exact:
            return exact
        return [s for s in self.all_symbols() if name_l in s.name.lower()]

    def find_callers(self, name: str) -> list[CallSite]:
        return [c for c in self.all_calls() if c.callee == name]

    def summary(self) -> str:
        if not self.files:
            return "Codebasis noch nicht indiziert. Führe /graph aus oder nutze CodeSymbols/CodeDef/CodeCallers."
        by_lang: dict[str, int] = {}
        by_backend: dict[str, int] = {}
        errors = 0
        for info in self.files.values():
            by_lang[info.language] = by_lang.get(info.language, 0) + 1
            by_backend[info.backend] = by_backend.get(info.backend, 0) + 1
            errors += 1 if info.error else 0
        lines = [f"Code-Graph: {len(self.files)} Datei(en), {sum(1 for _ in self.all_symbols())} Symbol(e)"]
        lines.append("  Sprachen: " + ", ".join(f"{lang} ({n})" for lang, n in sorted(by_lang.items())))
        lines.append("  Backends: " + ", ".join(f"{b} ({n})" for b, n in sorted(by_backend.items())))
        if not TREE_SITTER_AVAILABLE and any(lang != "python" for lang in by_lang):
            lines.append("  Hinweis: tree_sitter_languages nicht installiert -> Nicht-Python-Dateien nur per "
                          "Regex-Näherung (weniger präzise). Installierbar mit: pip install pandora-code[ast]")
        if errors:
            lines.append(f"  {errors} Datei(en) mit Lesefehler übersprungen")
        if self.truncated:
            lines.append(f"  Abgeschnitten bei {MAX_FILES} Dateien (sehr großes Repository)")
        return "\n".join(lines)


# -- Python-Backend (ast, exakt) ---------------------------------------------------------------
class _PyVisitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.symbols: list[Symbol] = []
        self.calls: list[CallSite] = []
        self._stack: list[str] = []  # Qualname-Pfad, z. B. ["ClassName", "method_name"]
        self._class_depth: list[bool] = []  # parallel zu _stack: ist die Ebene eine Klasse?

    def _qual(self, name: str) -> str:
        return ".".join([*self._stack, name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qual = self._qual(node.name)
        self.symbols.append(Symbol("class", node.name, qual, self.rel, node.lineno))
        self._stack.append(node.name)
        self._class_depth.append(True)
        self.generic_visit(node)
        self._stack.pop()
        self._class_depth.pop()

    def _function(self, node) -> None:
        in_class = bool(self._class_depth and self._class_depth[-1])
        qual = self._qual(node.name)
        args = [a.arg for a in node.args.args]
        if in_class and args and args[0] in ("self", "cls"):
            args = args[1:]
        signature = f"({', '.join(args)})"
        self.symbols.append(Symbol("method" if in_class else "function", node.name, qual, self.rel,
                                    node.lineno, signature))
        self._stack.append(node.name)
        self._class_depth.append(False)
        self.generic_visit(node)
        self._stack.pop()
        self._class_depth.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            callee = func.id
        elif isinstance(func, ast.Attribute):
            callee = func.attr
        else:
            callee = None
        if callee:
            caller = ".".join(self._stack) or None
            self.calls.append(CallSite(callee, caller, self.rel, node.lineno))
        self.generic_visit(node)


def _index_python(text: str, rel: str) -> tuple[list[Symbol], list[CallSite], str | None]:
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as err:
        return [], [], f"Syntaxfehler: {err}"
    visitor = _PyVisitor(rel)
    visitor.visit(tree)
    return visitor.symbols, visitor.calls, None


# -- Tree-sitter-Backend (optional) -----------------------------------------------------------
# Erfasst Funktions-/Klassendefinitionen und Aufrufe über generische Tree-sitter-Knotennamen, die über
# die gängigen Grammatiken hinweg stabil sind. Schlägt eine Sprache/Version fehl, wird pro Datei sauber
# auf den Regex-Fallback ausgewichen (kein Absturz).
_TS_DEF_TYPES = {
    "function_definition": "function", "function_declaration": "function", "method_definition": "method",
    "class_definition": "class", "class_declaration": "class", "class_specifier": "class",
    "struct_specifier": "class", "local_function": "function",
}
_TS_CALL_TYPES = {"call_expression": "member", "call": "member"}


def _ts_node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _index_tree_sitter(text: str, rel: str, language: str) -> tuple[list[Symbol], list[CallSite], str | None]:
    ts_lang = TS_LANGUAGE_NAME.get(language)
    if not ts_lang:
        return [], [], "Sprache ohne Tree-sitter-Zuordnung"
    try:
        parser = _ts_get_parser(ts_lang)
        source = text.encode("utf-8")
        tree = parser.parse(source)
    except Exception as err:  # Grammatik fehlt/inkompatibel -> Aufrufer weicht auf Regex aus
        return [], [], f"Tree-sitter fehlgeschlagen: {err}"

    symbols: list[Symbol] = []
    calls: list[CallSite] = []
    stack: list[str] = []

    def name_of(node):
        for child in node.children:
            if child.type in ("identifier", "field_identifier", "type_identifier", "property_identifier"):
                return _ts_node_text(child, source)
        return None

    def walk(node) -> None:
        kind = _TS_DEF_TYPES.get(node.type)
        if kind:
            name = name_of(node) or "?"
            qual = ".".join([*stack, name])
            symbols.append(Symbol(kind, name, qual, rel, node.start_point[0] + 1, backend="tree-sitter"))
            stack.append(name)
            for child in node.children:
                walk(child)
            stack.pop()
            return
        if node.type in _TS_CALL_TYPES:
            callee = None
            target = node.children[0] if node.children else None
            if target is not None:
                if target.type in ("identifier",):
                    callee = _ts_node_text(target, source)
                elif target.type in ("member_expression", "field_expression"):
                    callee = name_of(target)
            if callee:
                calls.append(CallSite(callee, ".".join(stack) or None, rel, node.start_point[0] + 1,
                                       backend="tree-sitter"))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return symbols, calls, None


# -- Regex-Fallback (ohne jede Abhängigkeit, als "ungefähr" markiert) --------------------------
_REGEX_DEFS = {
    "javascript": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\(", re.M), "function"),
        (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.M), "function"),
    ],
    "typescript": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*[<(]", re.M), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), "class"),
        (re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.M), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::[^=]+)?=>", re.M), "function"),
    ],
    "c": [
        (re.compile(r"^\s*(?:[\w][\w\s\*&:<>,]*[\s\*&])(\w+)\s*\([^;{]*\)\s*\{", re.M), "function"),
        (re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M), "class"),
    ],
    "cpp": [
        (re.compile(r"^\s*(?:[\w][\w\s\*&:<>,]*[\s\*&])(\w+)\s*\([^;{]*\)\s*(?:const\s*)?\{", re.M), "function"),
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M), "class"),
        (re.compile(r"^\s*struct\s+([A-Za-z_]\w*)", re.M), "class"),
    ],
    "lua": [
        (re.compile(r"^\s*(?:local\s+)?function\s+([\w][\w.:]*)\s*\(", re.M), "function"),
    ],
}
_CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")


def _index_regex(text: str, rel: str, language: str) -> tuple[list[Symbol], list[CallSite], str | None]:
    symbols: list[Symbol] = []
    for pattern, kind in _REGEX_DEFS.get(language, []):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            name = match.group(1).rsplit(".", 1)[-1].rsplit(":", 1)[-1]  # Lua "Obj.method" -> "method"
            symbols.append(Symbol(kind, name, name, rel, line, backend="regex"))
    defined_names = {s.name for s in symbols}
    calls: list[CallSite] = []
    for match in _CALL_RE.finditer(text):
        name = match.group(1)
        if name in _KEYWORDS_NOT_CALLS or name in defined_names and False:
            continue
        line = text.count("\n", 0, match.start()) + 1
        calls.append(CallSite(name, None, rel, line, backend="regex"))  # Regex kennt den umgebenden Scope nicht
    return symbols, calls, None


# -- Werkzeuge -------------------------------------------------------------------------------
def _graph_for(agent) -> CodeGraph:
    graph: CodeGraph | None = getattr(agent, "code_graph", None)
    if graph is None or graph.root != agent.ctx.cwd:
        graph = CodeGraph(agent.ctx.cwd)
        agent.code_graph = graph
    if not graph.files:
        graph.build()
    return graph


def _format_symbols(symbols: list[Symbol], limit: int = 60) -> str:
    if not symbols:
        return "Keine Treffer."
    lines = []
    for s in symbols[:limit]:
        mark = "" if s.backend != "regex" else " (Regex-Näherung)"
        sig = s.signature or ""
        lines.append(f"{s.kind:<8} {s.qualname}{sig}  —  {s.file}:{s.line}{mark}")
    if len(symbols) > limit:
        lines.append(f"… und {len(symbols) - limit} weitere")
    return "\n".join(lines)


def _format_calls(calls: list[CallSite], limit: int = 80) -> str:
    if not calls:
        return "Keine Aufrufer gefunden (oder nur per Objekt-Attribut mit anderem Namen aufgerufen)."
    lines = []
    for c in calls[:limit]:
        where = f"in {c.caller_qualname}()" if c.caller_qualname else "auf Modulebene"
        mark = "" if c.backend != "regex" else " (Regex-Näherung, Kontext unbekannt)"
        lines.append(f"{c.file}:{c.line}  {where}{mark}")
    if len(calls) > limit:
        lines.append(f"… und {len(calls) - limit} weitere")
    return "\n".join(lines)


def install(agent, settings) -> None:
    agent.code_graph = None  # lazy: erst beim ersten Werkzeugaufruf/​/graph aufgebaut

    def code_symbols(ctx: ToolContext, args: dict) -> str:
        graph = _graph_for(agent)
        query = str(args.get("query") or "").strip()
        kind = str(args.get("kind") or "").strip().lower()
        symbols = list(graph.all_symbols())
        if query:
            symbols = [s for s in symbols if query.lower() in s.name.lower()]
        if kind:
            symbols = [s for s in symbols if s.kind == kind]
        symbols.sort(key=lambda s: (s.file, s.line))
        return _format_symbols(symbols)

    def code_def(ctx: ToolContext, args: dict) -> str:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ToolError("'name' fehlt.")
        graph = _graph_for(agent)
        return _format_symbols(sorted(graph.find_definitions(name), key=lambda s: (s.file, s.line)))

    def code_callers(ctx: ToolContext, args: dict) -> str:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ToolError("'name' fehlt.")
        graph = _graph_for(agent)
        return _format_calls(sorted(graph.find_callers(name), key=lambda c: (c.file, c.line)))

    agent.add_tool(Tool(
        "CodeSymbols",
        "List functions/methods/classes found by the AST code graph (exact for Python via the `ast` module; "
        "Tree-sitter or a regex approximation for JS/TS/C/C++/Lua). Optional 'query' filters by substring, "
        "'kind' by function|method|class. Prefer this over Grep to see real definitions, not text matches.",
        schema({"query": {"type": "string", "description": "Substring filter on the name (optional)"},
                "kind": {"type": "string", "enum": ["function", "method", "class"], "description": "Optional filter"}},
               ()),
        code_symbols,
    ))
    agent.add_tool(Tool(
        "CodeDef",
        "Find the definition(s) of a function, method or class by name across the indexed codebase (file and "
        "line). Use this instead of Grep when asked 'where is X defined' / 'finde die Klassendefinition von Y'.",
        schema({"name": {"type": "string", "description": "Function/method/class name"}}, ("name",)),
        code_def,
    ))
    agent.add_tool(Tool(
        "CodeCallers",
        "Find all call sites of a function/method name across the indexed codebase, with the enclosing "
        "function where known (Python only) and file:line. Use this for 'who calls X' / 'zeige alle Aufrufer "
        "von X'. Matches by name (not full type resolution), so it can include same-named methods on "
        "unrelated classes.",
        schema({"name": {"type": "string", "description": "Function/method name as it appears at the call site"}},
               ("name",)),
        code_callers,
    ))

    def graph_command(arg: str, agent, ui) -> str | None:
        graph = getattr(agent, "code_graph", None) or CodeGraph(agent.ctx.cwd)
        agent.code_graph = graph
        if arg.strip().lower() in ("neu", "rebuild", "refresh", ""):
            if arg.strip().lower() in ("neu", "rebuild"):
                graph.build()
            elif not graph.files:
                graph.build()
            else:
                changed, total = graph.refresh()
                ui.info(f"{changed} von {total} Datei(en) neu eingelesen (geändert/neu).")
        ui.info(graph.summary())
        return None

    agent.register_command(
        "graph", graph_command,
        "/graph [neu]  Code-Graph-Status (Sprachen/Backends); ohne Argument nur neue/geänderte Dateien nachladen",
    )
