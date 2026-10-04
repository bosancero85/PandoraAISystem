"""Modell-Registry: fragt die installierten Ollama-Modelle live ab (Hot Reload) und wählt Ersatz.

Wozu: Subagenten und der Router dürfen nie ein Modell anfordern, das nicht installiert ist oder keine
Werkzeuge (Tool-Calls) versteht. Fehlt es, wird automatisch auf das passendste vorhandene Modell gewechselt.

Rollen (auch als `model:` in Agent-Dateien verwendbar):
  fast    schnelles Modell (~7B) für Suche, Dateien, einfache Tool-Calls
  general Standard (~14B) – bevorzugt das Modell des Hauptagenten
  strong  größtes verfügbares Modell für Architektur, Refactoring, Debugging
  tiny    kleinstes Modell ohne Werkzeuge (Zusammenfassungen, Kurztexte)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..ollama_client import OllamaClient, OllamaError

ROLES = ("fast", "general", "strong", "tiny")
ROLE_TARGET_SIZE = {"fast": 7.0, "general": 14.0, "tiny": 0.0}  # strong = so groß wie möglich

# Modellfamilien, deren Ollama-Version Tool-Calls unterstützt (Stand: gängige Familien; Rest wird zur Laufzeit gelernt).
TOOL_FAMILIES = {
    "qwen2.5", "qwen2.5-coder", "qwen3", "qwen3-coder", "qwq", "llama3.1", "llama3.2", "llama3.3", "llama4",
    "mistral", "mistral-nemo", "mistral-small", "mixtral", "command-r", "command-r-plus", "firefunction-v2",
    "granite3-dense", "granite3.1-dense", "granite3.2", "granite3.3", "nemotron-mini", "nemotron", "smollm2",
    "hermes3", "phi4-mini", "gpt-oss", "devstral", "magistral", "cogito", "athene-v2", "aya-expanse",
}
# Standardgröße in Milliarden Parametern, wenn der Tag (z. B. ":latest") sie nicht verrät.
FAMILY_DEFAULT_SIZE = {
    "qwen2.5": 7.0, "qwen2.5-coder": 7.0, "qwen3": 8.0, "qwen3-coder": 30.0, "llama3.1": 8.0, "llama3.2": 3.0,
    "llama3.3": 70.0, "llama3": 8.0, "mistral": 7.0, "mistral-nemo": 12.0, "gemma2": 9.0, "gemma": 7.0,
    "gemma3": 4.0, "phi3": 3.8, "phi4": 14.0, "phi4-mini": 3.8, "deepseek-r1": 7.0, "deepseek-coder": 6.7,
    "codellama": 7.0, "tinyllama": 1.1, "smollm2": 1.7, "gpt-oss": 20.0,
}
_SIZE = re.compile(r"(\d+(?:\.\d+)?)b(?![a-z0-9])")
_MISSING = ("not found", "try pulling", "does not exist")


@dataclass(frozen=True)
class ModelInfo:
    name: str
    family: str
    size_b: float | None
    tools: bool
    coder: bool

    @property
    def size_label(self) -> str:
        return f"{self.size_b:g}B" if self.size_b else "?"


def family_of(name: str) -> tuple[str, str]:
    """('qwen2.5-coder', '14b') aus 'qwen2.5-coder:14b' (Namespace wie 'hf.co/user/' wird entfernt)."""
    base, _, tag = name.strip().lower().partition(":")
    return base.rsplit("/", 1)[-1], tag or "latest"


def parse_model(name: str) -> ModelInfo:
    base, tag = family_of(name)
    match = _SIZE.search(tag) or _SIZE.search(base)
    if match:
        size: float | None = float(match.group(1))
    elif "mini" in tag and base == "phi3":
        size = 3.8
    else:
        size = FAMILY_DEFAULT_SIZE.get(base)
    coder = any(hint in base for hint in ("coder", "code", "devstral"))
    return ModelInfo(name, base, size, base in TOOL_FAMILIES, coder)


@dataclass
class Resolution:
    model: str
    switched: bool = False  # ein ausdrücklich gewünschtes Modell wurde ersetzt
    reason: str = ""


def is_missing_model_error(err: Exception) -> bool:
    return any(key in str(err).lower() for key in _MISSING)


def is_no_tools_error(err: Exception) -> bool:
    return "does not support tools" in str(err).lower()


@dataclass
class ModelRegistry:
    client: OllamaClient
    ttl: float = 5.0  # Sekunden, in denen eine abgerufene Liste als aktuell gilt
    roles: dict[str, str] = field(default_factory=dict)  # feste Zuordnung aus settings.json ("models": {...})
    _models: list[str] = field(default_factory=list)
    _at: float = 0.0
    _loaded: bool = False
    no_tools: set[str] = field(default_factory=set)  # zur Laufzeit gelernt: Modell lehnt Tools ab

    def seed(self, models: list[str]) -> None:
        """Übernimmt eine bereits abgerufene Liste (z. B. den Verbindungstest beim Start) ohne neue Anfrage."""
        self._models = list(models)
        self._loaded = True
        self._at = time.monotonic()

    # -- Hot Reload ---------------------------------------------------------------
    def refresh(self, force: bool = False) -> list[str]:
        """Installierte Modelle abrufen; bei Fehlern bleibt die letzte bekannte Liste erhalten."""
        now = time.monotonic()
        if force or not self._loaded or now - self._at >= self.ttl:
            try:
                self._models = list(self.client.list_models())
                self._loaded = True
                self._at = now
            except (OllamaError, AttributeError, OSError):
                pass
        return list(self._models)

    # -- Abfragen ---------------------------------------------------------------------
    def supports_tools(self, name: str) -> bool:
        return name not in self.no_tools and parse_model(name).tools

    def mark_no_tools(self, name: str) -> None:
        self.no_tools.add(name)

    def match(self, wanted: str, installed: list[str] | None = None) -> str | None:
        """Findet das installierte Modell zu einem Namen: exakt, ':latest' oder nur Familie ('qwen2.5-coder')."""
        installed = self.refresh() if installed is None else installed
        wanted = wanted.strip()
        for candidate in (wanted, f"{wanted}:latest"):
            if candidate in installed:
                return candidate
        if ":" not in wanted:
            family = [m for m in installed if family_of(m)[0] == wanted.lower()]
            if family:
                return max(family, key=lambda m: parse_model(m).size_b or 0)
        return None

    def candidates(self, need_tools: bool, exclude=()) -> list[str]:
        return [
            m for m in self.refresh()
            if m not in exclude and (not need_tools or self.supports_tools(m))
        ]

    def best(self, role: str, need_tools: bool = True, exclude=()) -> str | None:
        pool = self.candidates(need_tools, exclude)
        if not pool:
            return None

        def score(model: str):
            info = parse_model(model)
            size = info.size_b or 7.0
            if role == "strong":
                return (size, info.coder)
            return (-abs(size - ROLE_TARGET_SIZE.get(role, 14.0)), info.coder, -size)

        return max(pool, key=score)

    def role_assignment(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for role in ROLES:
            override = self.roles.get(role)
            found = self.match(override) if override else None
            out[role] = found or self.best(role, need_tools=role != "tiny")
        return out

    # -- Auswahl mit Ersatz -----------------------------------------------------------
    def resolve(self, wanted: str | None = None, role: str = "general", need_tools: bool = True,
                prefer: str | None = None, exclude=()) -> Resolution:
        """Liefert ein installiertes, werkzeugfähiges Modell; wechselt automatisch, wenn das gewünschte fehlt."""
        installed = self.refresh()
        wanted = (wanted or "").strip() or None
        if wanted and wanted.lower() in ROLES:  # `model: fast` in einer Agent-Datei
            role, wanted = wanted.lower(), None
        elif wanted and wanted.lower() == "auto":
            wanted = None
        role = role if role in ROLES else "general"
        if not installed:
            if not self._loaded:  # Server nicht erreichbar: nichts verändern, der Chat meldet den echten Fehler
                return Resolution(wanted or prefer or "", False, "Modellliste nicht abrufbar")
            return Resolution("", False, "keine Ollama-Modelle installiert (ollama pull ...)")

        def usable(model: str | None) -> bool:
            return bool(model) and model in installed and model not in exclude and (
                not need_tools or self.supports_tools(model))

        reason = ""
        if wanted:
            found = self.match(wanted, installed)
            if usable(found):
                return Resolution(found)  # type: ignore[arg-type]
            reason = f"'{wanted}' nicht installiert" if not found else f"'{found}' unterstützt keine Werkzeuge"
        override = self.match(self.roles[role], installed) if self.roles.get(role) else None
        if usable(override):
            return Resolution(override, bool(wanted), reason)  # type: ignore[arg-type]
        if role == "general" and usable(prefer):
            return Resolution(prefer, bool(wanted), reason)  # type: ignore[arg-type]
        choice = self.best(role, need_tools, exclude)
        if choice:
            return Resolution(choice, bool(wanted), reason)
        # Nichts Werkzeugfähiges vorhanden: bestes Bemühen mit einem beliebigen Modell.
        rest = [m for m in installed if m not in exclude]
        fallback = prefer if prefer in rest else (rest[0] if rest else (prefer or wanted or ""))
        return Resolution(fallback, bool(wanted), (reason + "; " if reason else "") + "kein werkzeugfähiges Modell installiert")

    # -- Anzeige ---------------------------------------------------------------------------
    def describe(self, current: str | None = None) -> str:
        installed = self.refresh(force=True)
        if not installed:
            return "Keine Modelle installiert (ollama pull qwen2.5-coder:7b)."
        lines = ["Installierte Modelle (live abgerufen):"]
        for name in installed:
            info = parse_model(name)
            tools = "Werkzeuge ✓" if self.supports_tools(name) else "Werkzeuge ✗"
            kind = "Code" if info.coder else ""
            mark = "*" if name == current else " "
            lines.append(f"{mark} {name:<26} {info.size_label:>6}  {tools}  {kind}".rstrip())
        assign = self.role_assignment()
        lines.append("Rollen: " + " · ".join(f"{r} → {assign[r] or '-'}" for r in ("strong", "general", "fast", "tiny")))
        lines.append("Fehlt ein Modell, wechseln Subagenten automatisch auf das passendste vorhandene.")
        return "\n".join(lines)
