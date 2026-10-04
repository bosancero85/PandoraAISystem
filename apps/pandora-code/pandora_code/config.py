"""Einstellungen laden: Benutzer (~/.pandora) und Projekt – Projektdateien nur nach Vertrauensabfrage.

Hooks und MCP-Server starten Programme. Eine aus dem Internet geklonte Projektkonfiguration darf das
nicht stillschweigend tun. Deshalb wird der Inhalt der Projektdateien beim ersten Mal (und bei jeder
Änderung) angezeigt und muss bestätigt werden; die Bestätigung gilt für genau diesen Datei-Stand.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .llm.models import ROLES

HOOK_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop")
# Lokal statt aus extensions.sandbox importiert, um config.py nicht an ein Erweiterungsmodul zu koppeln.
_SANDBOX_BACKENDS = ("auto", "firejail", "docker", "off")
PROJECT_FILES = (".pandora/settings.json", ".mcp.json")  # .mcp.json ist mit Claude-Code-Projekten kompatibel


def home_dir() -> Path:
    return Path(os.environ.get("PANDORA_HOME") or Path.home() / ".pandora")


@dataclass
class Settings:
    hooks: dict[str, list] = field(default_factory=dict)
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)
    model: str | None = None  # nur aus Benutzer-Einstellungen (~/.pandora), nie aus Projektdateien
    host: str | None = None
    models: dict[str, str] = field(default_factory=dict)  # Rollen-Vorgaben, z. B. {"fast": "qwen2.5-coder:7b"}
    router: bool = True  # Smart Model Router: automatische fast/general/strong-Wahl nach Aufgabenkomplexität
    embed_model: str | None = None  # nur aus Benutzer-Einstellungen; überschreibt die Auto-Erkennung (Vektor-RAG)
    sandbox: str = "auto"  # "auto" | "firejail" | "docker" | "off" – siehe extensions/sandbox.py
    sandbox_network: bool = False
    sandbox_image: str | None = None
    sandbox_container: str | None = None
    sandbox_workdir: str | None = None
    auto_fix: bool = True  # Auto-Fix & Continuous Quality Loop: siehe extensions/auto_fix.py
    auto_fix_lint: bool = True
    auto_fix_test: bool = True
    auto_fix_test_command: str | None = None  # überschreibt die automatische Test-Runner-Erkennung
    web_search: bool = True  # WebSearch/WebFetch: siehe extensions/web_search.py
    searxng_url: str | None = None  # explizite lokale SearXNG-Instanz; sonst Auto-Erkennung + DuckDuckGo-Fallback
    web_js_render: bool = False  # WebFetch standardmäßig mit Playwright rendern (falls installiert)


def _read_json(path: Path, settings: Settings) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        settings.notices.append(f"Konfiguration {path} ungültig: {err}")
        return {}
    if not isinstance(data, dict):
        settings.notices.append(f"Konfiguration {path} ungültig: Objekt erwartet")
        return {}
    return data


def _merge(settings: Settings, data: dict) -> None:
    for key in ("model", "host"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            setattr(settings, key, value.strip())
    embed_model = data.get("embedModel")
    if isinstance(embed_model, str) and embed_model.strip():
        settings.embed_model = embed_model.strip()
    if isinstance(data.get("sandbox"), str) and data["sandbox"].strip() in _SANDBOX_BACKENDS:
        settings.sandbox = data["sandbox"].strip()
    if isinstance(data.get("sandboxNetwork"), bool):
        settings.sandbox_network = data["sandboxNetwork"]
    for json_key, attr in (("sandboxImage", "sandbox_image"), ("sandboxContainer", "sandbox_container"),
                           ("sandboxWorkdir", "sandbox_workdir"), ("autoFixTestCommand", "auto_fix_test_command")):
        value = data.get(json_key)
        if isinstance(value, str) and value.strip():
            setattr(settings, attr, value.strip())
    for json_key, attr in (("autoFix", "auto_fix"), ("autoFixLint", "auto_fix_lint"), ("autoFixTest", "auto_fix_test"),
                           ("webSearch", "web_search"), ("webJsRender", "web_js_render")):
        if isinstance(data.get(json_key), bool):
            setattr(settings, attr, data[json_key])
    if isinstance(data.get("searxngUrl"), str) and data["searxngUrl"].strip():
        settings.searxng_url = data["searxngUrl"].strip()
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in hooks.items():
            if event in HOOK_EVENTS and isinstance(groups, list):
                settings.hooks.setdefault(event, []).extend(groups)
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        settings.mcp_servers.update({str(n): c for n, c in servers.items() if isinstance(c, dict)})
    models = data.get("models")  # z. B. "models": {"fast": "qwen2.5-coder:7b", "strong": "qwen2.5-coder:14b"}
    if isinstance(models, dict):
        for role, name in models.items():
            if role in ROLES and isinstance(name, str) and name.strip():
                settings.models[role] = name.strip()
    if isinstance(data.get("router"), bool):
        settings.router = data["router"]


def describe(settings: Settings) -> str:
    """Menschenlesbare Liste aller Programme, die diese Konfiguration starten würde."""
    lines: list[str] = []
    for event, groups in settings.hooks.items():
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and hook.get("command"):
                    lines.append(f"  Hook {event} [{group.get('matcher') or '*'}]: {hook['command']}")
    for name, cfg in settings.mcp_servers.items():
        target = cfg.get("url") or " ".join([str(cfg.get("command", "?")), *map(str, cfg.get("args") or [])])
        lines.append(f"  MCP-Server {name}: {target}")
    return "\n".join(lines) or "  (keine ausführbaren Einträge)"


def _trust_store() -> Path:
    return home_dir() / "trusted.json"


def _load_trusted() -> dict:
    try:
        data = json.loads(_trust_store().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(cwd: Path, digest: str) -> None:
    trusted = _load_trusted()
    trusted[str(cwd)] = digest
    try:
        _trust_store().parent.mkdir(parents=True, exist_ok=True)
        _trust_store().write_text(json.dumps(trusted, indent=2), encoding="utf-8")
    except OSError:
        pass  # nicht speichern zu können ist nur lästig (Rückfrage beim nächsten Start)


def load_settings(cwd: Path, trust: Callable[[Path, str], bool]) -> Settings:
    """trust(cwd, beschreibung) -> bool wird nur aufgerufen, wenn Projektdateien neu oder geändert sind."""
    settings = Settings()
    user = home_dir()
    for name in ("settings.json", "mcp.json"):
        _merge(settings, _read_json(user / name, settings))

    files = [cwd / rel for rel in PROJECT_FILES if (cwd / rel).is_file()]
    if not files:
        return settings
    project = Settings()
    digest = hashlib.sha256()
    for path in files:
        _merge(project, _read_json(path, project))
        digest.update(path.read_bytes())
    settings.notices.extend(project.notices)
    if not project.hooks and not project.mcp_servers:
        return settings
    if _load_trusted().get(str(cwd)) == digest.hexdigest() or trust(cwd, describe(project)):
        _remember(cwd, digest.hexdigest())
        _merge(settings, {"hooks": project.hooks, "mcpServers": project.mcp_servers})
    else:
        settings.notices.append("Projekt-Konfiguration (Hooks/MCP) ignoriert – nicht als vertrauenswürdig bestätigt.")
    return settings
