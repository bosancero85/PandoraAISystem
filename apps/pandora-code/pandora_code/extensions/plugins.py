"""Plugin-System mit Hot Reload – kompatibel zum von Claude Code etablierten `.claude-plugin`-Format, damit
das bestehende Ökosystem (z. B. ECC, github.com/affaan-m/ECC, oder jede eigene Claude-Code-Plugin-Sammlung)
auch in Pandora Code installierbar ist, ohne dass Autoren dafür extra etwas für Pandora bauen müssten.

    /plugin install <git-url-oder-pfad>       klont/verknüpft, aktiviert SOFORT (kein Neustart nötig)
    /plugin install <name>@<marketplace-url>  Plugin 'name' aus einer .claude-plugin/marketplace.json
    /plugin reload <name>                     liest ein installiertes Plugin neu ein (lokale Entwicklung)
    /plugin remove <name>
    /plugin [list]                            installierte Plugins mit ihren Bestandteilen anzeigen

Format eines Plugins (siehe code.claude.com/docs/en/plugins-reference):
    <plugin>/.claude-plugin/plugin.json   Manifest: "name" (Pflicht), description, version, author;
                                           optional abweichende Pfade für commands/agents/hooks/skills
    <plugin>/commands/*.md                 eigene Slash-Befehle (Markdown; $ARGUMENTS wird ersetzt)
    <plugin>/agents/*.md                   Subagenten – nutzt denselben Loader wie ~/.pandora/agents/
    <plugin>/hooks/hooks.json               Hook-Konfiguration – wird LIVE in den laufenden HookRunner gemerged.
                                            Pandoras eigener Matcher (hooks.py) vergleicht nur den Werkzeug-
                                            namen per Regex/Pipe-Alternation (z. B. "Bash|Edit"); nutzt ein
                                            Plugin stattdessen eine reichhaltigere Ausdruckssyntax wie bei ECC
                                            ('tool == "Edit" && tool_input.file_path matches "..."'), wird das
                                            erkannt und beim Installieren deutlich gewarnt – ein solcher Hook
                                            lädt zwar, feuert aber vermutlich nie.
    <plugin>/.mcp.json                      MCP-Server – werden LIVE verbunden (gleiches Format wie Pandoras
                                            eigene .mcp.json, siehe extensions/mcp.py)
    <plugin>/skills/*/SKILL.md              progressiv durchsuchbar/ladbar über die Werkzeuge SkillSearch/
                                            SkillLoad bzw. den Befehl /skills (siehe extensions/skills.py
                                            und pandora_code/skills.py) – NICHT automatisch in den
                                            System-Prompt eingespeist (bei hunderten Skills, z. B.
                                            Anthropic-Cybersecurity-Skills mit 818, würde das sofort das
                                            Kontextfenster lokaler Modelle sprengen).
    <plugin>/pandora_plugin.py              optional, Pandora-natives Python-Plugin: wird wie eine eingebaute
                                            Erweiterung geladen (install(agent, settings)) – läuft mit vollem
                                            Zugriff, deshalb mit eigener, deutlicherer Sicherheitsabfrage.

"Hot Reload" heißt hier konkret: eine Installation (oder /plugin reload) wirkt sofort in der laufenden
Sitzung – Agenten/Commands/Hooks/MCP-Server stehen im nächsten Zug zur Verfügung, ganz ohne Neustart von
Pandora Code. Es gibt bewusst KEINEN automatischen Hintergrund-Dateiwächter (das wäre bei einem CLI-Chat
eher verwirrend als hilfreich, siehe README) – das explizite /plugin reload ist der vorhersehbarere Weg.

Sicherheit: Klonen und (bei pandora_plugin.py) AUSFÜHREN von Code aus einer beliebigen Quelle ist
gleichwertig zu einer Software-Installation. /plugin install fragt deshalb immer erst nach, genau wie
Bash/Write das schon tun – nichts läuft ungefragt.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import home_dir
from ..tools import Tool, ToolContext, ToolError, schema
from .mcp import CONNECT_DEADLINE, McpServer, make_tool, safe_name

CLONE_TIMEOUT = 60
MANIFEST_REL = Path(".claude-plugin/plugin.json")
# Zweite, gleichwertige Stelle: der offene "Agent Plugins"-Standard (agent-plugins.org) legt sein Manifest
# direkt ins Repo-Wurzelverzeichnis statt unter .claude-plugin/ (Beispiel: K-Dense-AI/scientific-agent-skills).
MANIFEST_FALLBACK_REL = Path("plugin.json")
MARKETPLACE_REL = Path(".claude-plugin/marketplace.json")
COMPONENT_DEFAULTS = {"commands": "commands", "agents": "agents", "skills": "skills"}
HOOKS_DEFAULT = Path("hooks/hooks.json")
MCP_DEFAULT = Path(".mcp.json")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def plugins_root() -> Path:
    return home_dir() / "plugins"


# -- Quelle auflösen: Git-URL klonen ODER lokalen Pfad verknüpfen (für Plugin-Entwicklung ohne Kopieren) --
def _looks_like_local_path(source: str) -> bool:
    """Ein BLOSSER Pfad (kein Schema) bedeutet 'nutze dieses Arbeitsverzeichnis direkt, live bearbeitbar'
    (Symlink, keine Git-Historie nötig) – typisch beim lokalen Entwickeln eines Plugins. Ein 'file://'-URL
    ist dagegen ein ausdrückliches Git-Fernarchiv-Schema (git kann es nativ klonen) und bekommt bewusst die
    GIT-Semantik (eigenständige, von der Quelle unabhängige Kopie) statt eines Symlinks – wer eine Live-
    Verknüpfung will, gibt einfach den Pfad ohne 'file://' an."""
    return source.startswith(("/", "./", "../", "~")) or (len(source) > 1 and source[1] == ":")


def fetch_source(source: str, dest: Path) -> str:
    """Bringt die Plugin-Quelle nach `dest` und gibt zurück, wie ('git' oder 'lokal (verknüpft)')."""
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    if _looks_like_local_path(source):
        local = Path(source).expanduser().resolve()
        if not local.is_dir():
            raise ToolError(f"Lokaler Pfad nicht gefunden: {local}")
        try:
            dest.symlink_to(local, target_is_directory=True)
        except OSError:  # z. B. Windows ohne Entwicklermodus/Admin-Rechte -> Fallback aufs Kopieren
            shutil.copytree(local, dest)
            return "lokal (kopiert)"
        return "lokal (verknüpft)"
    if not shutil.which("git"):
        raise ToolError("'git' wurde nicht gefunden – zum Installieren aus einem Repository wird es gebraucht.")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", source, str(dest)],
        capture_output=True, text=True, timeout=CLONE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise ToolError(f"git clone fehlgeschlagen: {proc.stderr.strip() or proc.stdout.strip()}")
    return "git"


# -- Manifest & Marketplace -------------------------------------------------------------------------------
def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_manifest(plugin_dir: Path) -> dict:
    """Liest das Plugin-Manifest – zuerst Claude Codes eigener Pfad (.claude-plugin/plugin.json), sonst der
    offene Agent-Plugins-Standard (plugin.json direkt im Wurzelverzeichnis). Ohne beides: {"name": Ordnername}."""
    return (read_json(plugin_dir / MANIFEST_REL) or read_json(plugin_dir / MANIFEST_FALLBACK_REL)
            or {"name": plugin_dir.name})


def resolve_marketplace_entry(repo_dir: Path, name: str) -> Path:
    """Findet das Plugin `name` innerhalb einer .claude-plugin/marketplace.json (z. B. das ECC-Muster
    '/plugin install ecc@ecc', wo dieselbe Quelle sowohl Marktplatz als auch das eine Plugin ist)."""
    data = read_json(repo_dir / MARKETPLACE_REL)
    if not data:
        raise ToolError(f"Keine {MARKETPLACE_REL} gefunden – '{name}@...' setzt eine Marktplatz-Quelle voraus.")
    for entry in data.get("plugins") or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            source = entry.get("source")
            return (repo_dir / source).resolve() if source else repo_dir
    raise ToolError(f"Plugin '{name}' nicht in {MARKETPLACE_REL} gefunden.")


@dataclass
class Resolved:
    """Pfade der einzelnen Bestandteile, nach Manifest-Overrides oder Standardverzeichnissen aufgelöst."""
    commands: list[Path] = field(default_factory=list)
    agents: list[Path] = field(default_factory=list)
    skills: list[Path] = field(default_factory=list)
    hooks_file: Path | None = None
    mcp_file: Path | None = None
    python_plugin: Path | None = None


def _as_list(value, base: Path) -> list[Path]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [(base / str(v)).resolve() for v in values]


def resolve_components(plugin_dir: Path, manifest: dict) -> Resolved:
    out = Resolved()
    for field_name, attr in (("commands", "commands"), ("agents", "agents"), ("skills", "skills")):
        override = manifest.get(field_name)
        paths = _as_list(override, plugin_dir) if override is not None else [plugin_dir / COMPONENT_DEFAULTS[field_name]]
        setattr(out, attr, [p for p in paths if p.is_dir()])
    hooks_override = manifest.get("hooks")
    hooks_path = plugin_dir / hooks_override if isinstance(hooks_override, str) else plugin_dir / HOOKS_DEFAULT
    out.hooks_file = hooks_path if hooks_path.is_file() else None
    mcp_override = manifest.get("mcpServers")
    mcp_path = plugin_dir / mcp_override if isinstance(mcp_override, str) else plugin_dir / MCP_DEFAULT
    out.mcp_file = mcp_path if mcp_path.is_file() else None
    python_plugin = plugin_dir / "pandora_plugin.py"
    out.python_plugin = python_plugin if python_plugin.is_file() else None
    return out


@dataclass
class PluginRecord:
    name: str
    dir: Path
    source: str
    manifest: dict
    components: Resolved
    commands_registered: list[str] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)


# -- Live-Anwendung der Bestandteile ------------------------------------------------------------------
def _all_plugin_dirs() -> list[Path]:
    root = plugins_root()
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith("_staging_")]


def agent_dirs() -> tuple[Path, ...]:
    """Agenten-Verzeichnisse aller installierten Plugins – von subagents.load_agents() konsultiert, damit
    Plugin-Agenten ohne jede Extra-Verdrahtung denselben Hot-Reload-Mechanismus nutzen wie von Hand
    angelegte Dateien in ~/.pandora/agents/."""
    return tuple(d for p in _all_plugin_dirs() for d in resolve_components(p, read_manifest(p)).agents)


def skill_dirs() -> tuple[Path, ...]:
    """Skill-Verzeichnisse aller installierten Plugins – von skills.discover_skills() konsultiert (siehe
    pandora_code/skills.py), analog zu agent_dirs()."""
    return tuple(d for p in _all_plugin_dirs() for d in resolve_components(p, read_manifest(p)).skills)


def _unwrap_hook_config(hooks_obj) -> dict | None:
    """Findet das echte, veränderbare HookRunner.config-Dict – auch wenn andere Erweiterungen (z. B.
    auto_fix.py) sich mit einem eigenen Wrapper davorgehängt haben (deren .config ist eine schreibgeschützte
    Durchreichung, siehe deren Docstring); folgt der .inner-Kette bis zum echten HookRunner."""
    seen = set()
    while hooks_obj is not None and id(hooks_obj) not in seen:
        seen.add(id(hooks_obj))
        config = hooks_obj.__dict__.get("config") if hasattr(hooks_obj, "__dict__") else None
        if isinstance(config, dict):
            return config
        hooks_obj = getattr(hooks_obj, "inner", None)
    return None


_SIMPLE_MATCHER = re.compile(r"^[A-Za-z0-9_|.*]*$")


def _is_complex_matcher(matcher: str) -> bool:
    """Pandoras eigener Matcher (extensions/hooks.py) prüft nur den WERKZEUG-NAMEN per Regex/Pipe-Alternation
    (z. B. 'Bash|Edit'). Manche Plugins (z. B. ECC) nutzen stattdessen eine reichhaltigere Ausdruckssyntax
    wie 'tool == \"Edit\" && tool_input.file_path matches \"\\.ts$\"' – das wertet Pandora NICHT aus, der
    Hook würde lautlos nie feuern. Diese Heuristik erkennt solche Fälle, damit /plugin install ehrlich warnt
    statt einen funktionslosen Hook stillschweigend als 'aktiv' zu melden."""
    return not _SIMPLE_MATCHER.match(matcher or "*")


def merge_hooks_live(agent, hooks_config: dict) -> tuple[bool, list[str]]:
    """Gibt (gemerged?, Liste der Events mit einem zu komplexen Matcher) zurück."""
    target = _unwrap_hook_config(getattr(agent, "hooks", None))
    if target is None:
        return False, []
    complex_events: list[str] = []
    for event, groups in (hooks_config or {}).items():
        if not isinstance(groups, list):
            continue
        target.setdefault(event, []).extend(groups)
        if any(_is_complex_matcher(str(g.get("matcher", ""))) for g in groups if isinstance(g, dict)):
            complex_events.append(event)
    return True, complex_events


def connect_mcp_servers_live(agent, mcp_config: dict) -> tuple[int, int]:
    """Verbindet die in `mcp_config` ("mcpServers": {...}, gleiche Form wie Pandoras eigene .mcp.json)
    beschriebenen Server sofort und registriert ihre Werkzeuge – siehe extensions/mcp.py für dasselbe
    Vorgehen beim normalen Start."""
    servers = [McpServer(name, cfg, agent.ctx.cwd) for name, cfg in (mcp_config.get("mcpServers") or {}).items()]
    if not servers:
        return 0, 0
    threads = [threading.Thread(target=_connect_one, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    deadline = time.monotonic() + CONNECT_DEADLINE
    for server, t in zip(servers, threads):
        t.join(max(deadline - time.monotonic(), 0.1))
        if t.is_alive():
            server.error = "Zeitüberschreitung beim Verbinden"
    tool_count = 0
    connected_count = 0
    for server in servers:
        if server.error or not server.connected:
            agent.notice(f"Plugin-MCP-Server '{server.name}': {server.error or 'nicht verbunden'}", error=True)
            server.close()
            continue
        agent.closers.append(server.close)
        agent.mcp_servers.append(server)
        for spec in server.tool_specs:
            agent.add_tool(make_tool(server, spec))
            tool_count += 1
        connected_count += 1
    return connected_count, tool_count


def _connect_one(server: McpServer) -> None:
    try:
        server.connect()
    except Exception as err:
        server.error = str(err)


def register_commands_live(agent, command_dirs: list[Path], plugin_name: str) -> list[str]:
    registered: list[str] = []
    for folder in command_dirs:
        for path in sorted(folder.rglob("*.md")):
            slug = path.stem.lower()
            if not NAME_RE.match(slug):
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if body.startswith("---"):
                _, _, body = body.partition("---\n")
                _, _, body = body.partition("---\n")
            template = body.strip()

            def handler(arg: str, agent, ui, _template=template) -> str | None:
                return _template.replace("$ARGUMENTS", arg) if arg else _template

            agent.register_command(slug, handler, f"/{slug}  (Plugin '{plugin_name}')")
            registered.append(slug)
    return registered


def apply_plugin(agent, plugin_dir: Path, source: str, *, confirm) -> PluginRecord:
    manifest = read_manifest(plugin_dir)
    name = str(manifest.get("name") or plugin_dir.name)
    components = resolve_components(plugin_dir, manifest)
    record = PluginRecord(name, plugin_dir, source, manifest, components)

    if components.hooks_file:
        hooks_config = read_json(components.hooks_file) or {}
        merged, complex_events = merge_hooks_live(agent, hooks_config)
        if merged:
            agent.notice(f"Plugin '{name}': Hooks aktiv.")
        if complex_events:
            agent.notice(
                f"Plugin '{name}': Hooks für {', '.join(complex_events)} nutzen eine Matcher-Ausdruckssyntax "
                "(z. B. 'tool == \"Edit\" && ...'), die Pandoras Hook-Matcher nicht auswertet – diese Hooks "
                "werden geladen, aber vermutlich NIE feuern. Nur einfache Werkzeugnamen/Regex (z. B. "
                "'Bash|Edit') funktionieren.", error=True,
            )
    if components.mcp_file:
        mcp_config = read_json(components.mcp_file) or {}
        connected, tools = connect_mcp_servers_live(agent, mcp_config)
        if connected:
            agent.notice(f"Plugin '{name}': {connected} MCP-Server verbunden, {tools} Werkzeuge.")
    if components.commands:
        record.commands_registered = register_commands_live(agent, components.commands, name)
    if components.agents:
        agent.notice(f"Plugin '{name}': {len(components.agents and list(components.agents[0].glob('*.md')))} "
                     f"Agent(en) verfügbar (Task-Werkzeug, Hot Reload).")
    if components.skills:
        count = sum(1 for _ in components.skills[0].glob("*/SKILL.md"))
        agent.notice(f"Plugin '{name}': {count} Skill(s) durchsuchbar über SkillSearch/SkillLoad bzw. /skills "
                     "(nicht automatisch im Kontext – bei vielen Skills würde das das Kontextfenster sprengen).")
    if components.python_plugin:
        if not confirm(f"⚠ Plugin '{name}' enthält eigenen Python-Code ({components.python_plugin.name}), der "
                       "mit vollem Zugriff ausgeführt wird – wie eine eingebaute Erweiterung. Wirklich laden?"):
            agent.notice(f"Plugin '{name}': pandora_plugin.py NICHT geladen (abgelehnt).", error=True)
        else:
            _load_python_plugin(agent, components.python_plugin, name)
    return record


def _load_python_plugin(agent, path: Path, name: str) -> None:
    try:
        spec = importlib.util.spec_from_file_location(f"pandora_plugin_{safe_name(name)}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "install"):
            module.install(agent, agent.settings if hasattr(agent, "settings") else None)
        agent.notice(f"Plugin '{name}': pandora_plugin.py geladen.")
    except Exception as err:
        agent.notice(f"Plugin '{name}': pandora_plugin.py fehlgeschlagen ({type(err).__name__}: {err}).", error=True)


# -- Installation / Verwaltung --------------------------------------------------------------------------
def install_plugin(agent, spec: str, *, confirm) -> PluginRecord:
    name_hint, _, source = spec.partition("@")
    source = source or name_hint
    is_marketplace_form = bool(source) and "@" in spec and source != spec

    if not confirm(f"⚠ Lädt (und ggf. führt) Code von '{source}' aus. Nur von vertrauenswürdiger Quelle "
                   "installieren. Fortfahren?"):
        raise ToolError("Installation abgebrochen.")

    staging = plugins_root() / f"_staging_{safe_name(name_hint or source)}"
    plugins_root().mkdir(parents=True, exist_ok=True)
    kind = fetch_source(source, staging)
    try:
        plugin_dir = resolve_marketplace_entry(staging, name_hint) if is_marketplace_form else staging
        manifest = read_manifest(plugin_dir)
        final_name = str(manifest.get("name") or name_hint or source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
        if not NAME_RE.match(final_name):
            raise ToolError(f"Ungültiger Plugin-Name: '{final_name}'")
        dest = plugins_root() / final_name
        if plugin_dir == staging:
            if dest.exists() or dest.is_symlink():
                shutil.rmtree(dest) if dest.is_dir() and not dest.is_symlink() else dest.unlink()
            staging.rename(dest)
        else:  # Marktplatz-Unterordner: den relevanten Teil an seinen endgültigen Platz kopieren
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(plugin_dir, dest)
            shutil.rmtree(staging)
        agent.notice(f"Plugin '{final_name}' installiert ({kind}): {dest}")
        return apply_plugin(agent, dest, source, confirm=confirm)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def reload_plugin(agent, name: str, *, confirm) -> PluginRecord:
    plugin_dir = plugins_root() / name
    if not plugin_dir.is_dir():
        raise ToolError(f"Plugin '{name}' ist nicht installiert.")
    return apply_plugin(agent, plugin_dir, name, confirm=confirm)


def remove_plugin(name: str) -> None:
    plugin_dir = plugins_root() / name
    if not plugin_dir.exists() and not plugin_dir.is_symlink():
        raise ToolError(f"Plugin '{name}' ist nicht installiert.")
    if plugin_dir.is_symlink() or plugin_dir.is_file():
        plugin_dir.unlink()
    else:
        shutil.rmtree(plugin_dir)


def list_plugins() -> list[tuple[str, Resolved, dict]]:
    root = plugins_root()
    if not root.is_dir():
        return []
    out = []
    for plugin_dir in sorted(root.iterdir()):
        if plugin_dir.name.startswith("_staging_") or not plugin_dir.is_dir():
            continue
        manifest = read_manifest(plugin_dir)
        out.append((manifest.get("name") or plugin_dir.name, resolve_components(plugin_dir, manifest), manifest))
    return out


# -- Werkzeug-/Befehl-Verdrahtung ------------------------------------------------------------------------
def install(agent, settings) -> None:
    def confirm(prompt: str) -> bool:
        answer = agent.perms.ask(prompt) if getattr(agent, "perms", None) else "n"
        return str(answer).strip().lower() in ("j", "ja", "y", "yes", "immer", "always")

    def plugin_command(arg: str, agent, ui) -> str | None:
        parts = arg.split(maxsplit=1)
        action = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""
        try:
            if action in ("list", ""):
                entries = list_plugins()
                if not entries:
                    ui.info("Keine Plugins installiert. /plugin install <url-oder-pfad>")
                    return None
                lines = []
                for name, comp, manifest in entries:
                    bits = []
                    if comp.commands:
                        bits.append(f"{sum(len(list(d.glob('*.md'))) for d in comp.commands)} Befehle")
                    if comp.agents:
                        bits.append(f"{sum(len(list(d.glob('*.md'))) for d in comp.agents)} Agenten")
                    if comp.hooks_file:
                        bits.append("Hooks")
                    if comp.mcp_file:
                        bits.append("MCP")
                    if comp.skills:
                        bits.append(f"{sum(len(list(d.glob('*/SKILL.md'))) for d in comp.skills)} Skills (inaktiv)")
                    if comp.python_plugin:
                        bits.append("Python")
                    desc = manifest.get("description", "")
                    lines.append(f"{name}: {', '.join(bits) or 'keine Bestandteile erkannt'}" +
                                 (f" – {desc}" if desc else ""))
                ui.info("\n".join(lines))
            elif action == "install":
                if not rest:
                    raise ToolError("Nutzung: /plugin install <git-url-oder-pfad>[@<marktplatz-url>]")
                install_plugin(agent, rest, confirm=confirm)
            elif action == "reload":
                if not rest:
                    raise ToolError("Nutzung: /plugin reload <name>")
                reload_plugin(agent, rest, confirm=confirm)
                ui.info(f"Plugin '{rest}' neu geladen.")
            elif action == "remove":
                if not rest:
                    raise ToolError("Nutzung: /plugin remove <name>")
                remove_plugin(rest)
                ui.info(f"Plugin '{rest}' entfernt.")
            else:
                ui.error("Nutzung: /plugin [list|install <quelle>|reload <name>|remove <name>]")
        except ToolError as err:
            ui.error(str(err))
        return None

    agent.register_command(
        "plugin", plugin_command,
        "/plugin [list|install <quelle>|reload <name>|remove <name>]  Plugins verwalten (Hot Reload, "
        "kompatibel zum .claude-plugin-Format)",
    )
