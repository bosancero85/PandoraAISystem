"""Kommandozeile und interaktive Schleife von Pandora® 🦙 Code."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .agent import MEMORY_FILE, Agent
from .banner import PinnedBanner
from .config import load_settings
from .doctor import run_doctor, sudo_warning
from .extensions import MODULES, install_all
from .llm.models import ModelRegistry
from .llm.router import TaskRouter
from .ollama_client import OllamaClient, OllamaError
from .permissions import MODES, Permissions
from .prompts import active_prompt_path, ensure_default_prompt, install_playbook, load_user_prompt
from .tools import ToolContext, ToolError
from .ui import UI

PREFERRED_MODELS = ("qwen3-coder", "qwen2.5-coder", "qwen3", "llama3.1", "llama3.2", "mistral")
EXIT = object()

HELP = """Befehle (Überblick – Details zu einem einzelnen Befehl: /help <befehl>, z. B. /help sandbox):

Allgemein
  /help [befehl]        diese Übersicht, oder Details zu einem Befehl
  /about                was Pandora Code ist und kann
  /clear                Gespräch zurücksetzen
  /compact              Gespräch zusammenfassen (spart Kontext)
  /cost                 Token-Verbrauch dieser Sitzung
  /exit                 beenden (oder Strg+D)
  !befehl               Shell-Befehl direkt ausführen
  Zeile mit \\ am Ende  mehrzeilige Eingabe

Modell & Automatisierung
  /model [name]         Modell anzeigen oder wechseln (fehlt es, wird automatisch ersetzt; pinnt den Router)
  /models               installierte Ollama-Modelle, Rollen-Zuordnung (Hot Reload)
  /router [an|aus]      Smart Model Router anzeigen/umschalten (fast/general/strong nach Aufgabe)
  /permissions [modus]  ask | accept-edits | plan | yolo

Projekt & Sitzung
  /init                 PANDORA.md (Projekt-Notizen) erstellen lassen
  /prompt               zeigt, welche Prompt-Datei gilt (editierbar, wirkt sofort)
  /playbook             legt playbook/ mit den 6 Vorlagen im Arbeitsverzeichnis an"""

# Längere Erklärung + Beispiel für /help <befehl>. Fehlt ein Befehl hier, zeigt /help stattdessen dessen
# kurze Beschreibung aus der Übersicht bzw. der eigene help_text einer Erweiterung – nie eine leere Antwort.
DETAILS: dict[str, str] = {
    "help": "/help [befehl]\nOhne Argument: die vollständige Befehlsübersicht.\nMit Argument: diese "
            "ausführlichere Erklärung zu genau einem Befehl (z. B. /help model).",
    "about": "/about\nZeigt Version, Marke, Kernfähigkeiten im Überblick und die aktuelle Ollama-Adresse "
             "dieser Sitzung.",
    "clear": "/clear\nSetzt das Gespräch zurück (Verlauf, gelesene Dateien, Todo-Liste). Modell, Modus und "
             "Erweiterungen bleiben unverändert.",
    "compact": "/compact\nFasst das bisherige Gespräch zusammen und ersetzt den Verlauf durch diese "
               "Zusammenfassung – nützlich, wenn das Kontextfenster eng wird, ohne komplett neu anzufangen.",
    "cost": "/cost\nZeigt die in dieser Sitzung verbrauchten Token (Eingabe/Ausgabe). Rein informativ – "
            "lokales Ollama verursacht keine Kosten, nur Rechenzeit.",
    "exit": "/exit (auch: /quit, /q, Strg+D)\nBeendet Pandora Code.",
    "model": "/model [name]\nOhne Argument: zeigt das aktuelle Modell.\nMit Namen: wechselt darauf, WENN es "
              "installiert ist (sonst Fehlermeldung mit 'ollama pull ...' – kein stiller Ersatz bei "
              "ausdrücklichem Wunsch). Pinnt danach das Modell: der Smart Model Router (/router) mischt sich "
              "erst nach /router an wieder ein.\nBeispiel: /model qwen2.5-coder:14b",
    "models": "/models\nListet alle installierten Ollama-Modelle (live abgerufen, Hot Reload) mit Größe, "
              "Tool-Fähigkeit und der aktuellen fast/general/strong/tiny-Rollenzuordnung.",
    "router": "/router [an|aus]\nOhne Argument: zeigt, ob der Smart Model Router aktiv ist. 'an' aktiviert "
              "ihn (setzt auch eine per /model gesetzte Pinnung zurück), 'aus' deaktiviert ihn (aktuelles "
              "Modell bleibt). Der Router wählt sonst pro Nachricht automatisch fast/general/strong nach "
              "Aufgabenkomplexität.",
    "permissions": "/permissions [modus]\nOhne Argument: zeigt alle Modi mit Erklärung, aktueller Modus "
                   "markiert.\nMit Modus: wechselt sofort. Modi: ask (jede Änderung bestätigen, Standard), "
                   "accept-edits (Dateiänderungen automatisch, Bash weiter mit Rückfrage), plan (nur Lesen, "
                   "keine Änderungen), yolo (nichts wird erfragt – mit Bedacht einsetzen).\n"
                   "Beispiel: /permissions accept-edits",
    "init": "/init\nLässt den Agenten das Projekt analysieren (Struktur, Sprache, Build-/Test-Befehle, "
            "Konventionen) und eine PANDORA.md schreiben, die künftige Sitzungen als Kontext nutzen.",
    "prompt": "/prompt\nZeigt, welche System-Prompt-Datei gerade gilt (Projekt-Prompt .pandora/prompt.md hat "
              "Vorrang vor dem Benutzer-Prompt). Die Datei ist normaler Text/Markdown und kann mit einem "
              "Editor angepasst werden; Änderungen wirken ab der nächsten Nachricht, kein Neustart nötig.",
    "skills": "/skills [suchbegriff]\nOhne Argument: Anzahl gefundener Skills nach Quelle (eigene "
              "~/.pandora/skills bzw. .pandora/skills, die werkzeugübergreifende ~/.agents/skills bzw. "
              ".agents/skills-Konvention – von Tools wie 'agent-reach install' oder 'browser-use skill "
              "install' selbst befüllt –, sowie skills/ installierter Plugins). Mit Suchbegriff: passende "
              "Skills mit Beschreibung. Die Werkzeuge SkillSearch/SkillLoad nutzen dasselbe – der Agent "
              "sucht selbst und lädt bei Bedarf eine volle Anleitung nach (progressiv, kein automatisches "
              "Einspeisen aller Skills in den Kontext).\nBeispiel: /skills PDF ausfüllen",
    "plugin": "/plugin [list|install <quelle>|reload <name>|remove <name>]\nPlugin-System, kompatibel zum "
              "von Claude Code etablierten .claude-plugin-Format (Marketplace, Agents, Hooks, Commands, "
              "MCP) – darüber installierbare Sammlungen wie ECC (github.com/affaan-m/ECC) funktionieren "
              "direkt. 'install' klont/verknüpft die Quelle und aktiviert sie SOFORT (Hot Reload, kein "
              "Neustart nötig); fragt vorher immer erst nach, besonders deutlich bei eigenem Python-Code "
              "im Plugin. 'reload' liest ein installiertes Plugin neu ein (z. B. nach lokalem Bearbeiten). "
              "'<name>@<url>' installiert gezielt ein Plugin aus einem Marketplace-Repository.\n"
              "Beispiel: /plugin install https://github.com/affaan-m/ECC",
    "playbook": "/playbook\nLegt einen Ordner playbook/ mit sechs Vorlagen im Arbeitsverzeichnis an (z. B. "
                "für ein Projekt-Interview). Vorhandene Dateien werden nicht überschrieben.",
}


ABOUT_TEMPLATE = """Pandora® 🦙 Code {version}
Teil der AKI_SystemDown® / Pandora® Produktreihe.

Lokaler, KI-gestützter Coding-Agent fürs Terminal – Nachbau des Claude-Code-Bedienkonzepts, läuft komplett
über eine lokale Ollama-Instanz. Kein Cloud-Zwang: Modell, Code und Dateien bleiben auf diesem Rechner; nur
die optionale Websuche (WebSearch/WebFetch) verlässt ihn, und auch die bevorzugt über eine selbst gehostete
SearXNG-Instanz statt einen externen Dienst.

Kernfähigkeiten:
  - Dateien lesen/durchsuchen/ändern (Read/Write/Edit/Glob/Grep), Bash – wahlweise in einer Firejail-/
    Docker-Sandbox statt direkt auf dem Host (/sandbox)
  - Smart Model Router: wählt je Nachricht automatisch fast/general/strong unter den installierten
    Ollama-Modellen, mit Hot-Reload-Fallback, wenn eins fehlt (/router, /models)
  - AST-Code-Graph (CodeSymbols/CodeDef/CodeCallers) und lokales Vektor-RAG (CodeSearch) für echtes
    Codeverständnis statt reiner Text-Suche (/graph, /rag)
  - Auto-Fix-Loop: lintet nach jeder Änderung, testet vor jedem Stopp, bis es grün ist (/autofix)
  - WebSearch/WebFetch für aktuelle Dokumentation jenseits des Modell-Trainingsstands (/websearch)
  - Sub-Agenten (Task), Plan-Modus, Hooks und MCP-Anbindung für größere/wiederkehrende Aufgaben
  - Optionale vollständige Terminal-Oberfläche mit Textual (pandora code --tui)

Diese Sitzung: Modell {model}, Modus {mode}, Ollama unter {host}.
Benötigt Python 3.9+; getestet unter Linux (Kali, Raspberry Pi 4B).

/help zeigt alle Befehle, /help <befehl> Details zu einem einzelnen."""


def about_text(agent: Agent) -> str:
    return ABOUT_TEMPLATE.format(
        version=__version__, model=agent.model, mode=agent.perms.mode, host=agent.client.host,
    )


def help_detail(agent: Agent, name: str) -> str:
    """Text für '/help <befehl>': lange Erklärung aus DETAILS, sonst die kurze Zeile aus der Übersicht
    (Kernbefehle) bzw. der eigene help_text einer Erweiterung – nie eine leere Antwort für einen
    tatsächlich existierenden Befehl."""
    name = name.strip().lstrip("/").lower()
    if name in DETAILS:
        return DETAILS[name]
    if name in agent.commands:
        _, text = agent.commands[name]
        return f"/{text}" if text else f"/{name}\n(keine ausführliche Hilfe hinterlegt)"
    for line in HELP.splitlines():
        if line.strip().startswith(f"/{name} ") or line.strip() == f"/{name}":
            return line.strip()
    return f"Unbekannter Befehl '/{name}'. /help zeigt alle Befehle."


INIT_PROMPT = (
    f"Analysiere dieses Projekt (Struktur, Sprache, Build-/Test-Befehle, Konventionen) und schreibe eine "
    f"knappe {MEMORY_FILE} in das Arbeitsverzeichnis, die künftigen Sitzungen als Kontext dient."
)


def ask_trust(cwd: Path, description: str) -> bool:
    """Projekt-Konfiguration startet Programme (Hooks, MCP) – nur nach ausdrücklicher Bestätigung laden."""
    print(f"\n⚠ Die Projekt-Konfiguration in {cwd} würde diese Programme starten:\n{description}")
    try:
        answer = input("Diesem Stand vertrauen? [j/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in ("j", "ja", "y", "yes")


def help_text(agent: Agent) -> str:
    extra = [f"  {text}" for _, text in agent.commands.values() if text]
    section = "\n\nErweiterungen\n" + "\n".join(extra) if extra else ""
    return HELP + section


def pick_model(models: list[str]) -> str | None:
    for preferred in PREFERRED_MODELS:
        for model in models:
            if model.startswith(preferred):
                return model
    return models[0] if models else None


def is_installed(model: str, models: list[str]) -> bool:
    return model in models or f"{model}:latest" in models


def status_line(agent: Agent) -> str:
    return f"Pandora® 🦙 Code v{__version__} · {agent.model} · Modus: {agent.perms.mode} · {agent.ctx.cwd}"


def read_input() -> str:
    lines: list[str] = []
    prompt = "\n> "
    while True:
        line = input(prompt)
        if line.endswith("\\"):
            lines.append(line[:-1])
            prompt = "  "
            continue
        lines.append(line)
        return "\n".join(lines)


def handle_command(line: str, agent: Agent, banner: PinnedBanner, ui: UI):
    """Gibt EXIT, einen Prompt (str) für den Agenten oder None zurück."""
    command, _, arg = line[1:].partition(" ")
    command, arg = command.lower(), arg.strip()
    if command in ("exit", "quit", "q"):
        return EXIT
    if command == "help":
        ui.info(help_detail(agent, arg) if arg else help_text(agent))
    elif command == "about":
        ui.info(about_text(agent))
    elif command == "clear":
        agent.clear()
        banner.clear_body()
    elif command == "compact":
        ui.info("Komprimiere …")
        agent.compact()
        ui.info("Gespräch zusammengefasst.")
    elif command == "cost":
        ui.info(f"Tokens – Eingabe: {agent.tokens_in}, Ausgabe: {agent.tokens_out} (lokal, keine Kosten)")
    elif command == "models":
        ui.info(agent.registry.describe(agent.model) if agent.registry else
                ("\n".join(agent.client.list_models()) or "Keine Modelle installiert."))
    elif command == "model":
        installed = agent.registry.refresh(force=True) if agent.registry else agent.client.list_models()
        if not arg:
            ui.info(f"Aktuelles Modell: {agent.model}"
                    + (" (Router pausiert – /router an setzt die automatische Wahl fort)" if agent.auto_route_pinned else ""))
        elif is_installed(arg, installed):
            agent.model = arg if arg in installed else f"{arg}:latest"
            agent.auto_route_pinned = True  # von Hand gewählt: Router mischt sich nicht mehr ein
            banner.update_status(status_line(agent))
        else:
            ui.error(f"Modell '{arg}' ist nicht installiert (ollama pull {arg}).")
    elif command == "router":
        if not agent.router:
            ui.error("Kein Router verfügbar (keine Ollama-Verbindung beim Start?).")
        elif not arg:
            state = "aus (Router selbst deaktiviert)" if not agent.router.enabled else (
                "pausiert (Modell manuell per /model gesetzt)" if agent.auto_route_pinned else "an")
            ui.info(f"Router: {state}")
        elif arg.lower() in ("an", "on", "ein"):
            agent.router.enabled = True
            agent.auto_route_pinned = False
            ui.info("Router aktiviert – wählt ab der nächsten Nachricht wieder automatisch das Modell.")
        elif arg.lower() in ("aus", "off"):
            agent.router.enabled = False
            ui.info("Router deaktiviert. Aktuelles Modell bleibt, bis du /model oder /router an nutzt.")
        else:
            ui.error("Nutzung: /router [an|aus]")
    elif command == "permissions":
        if not arg:
            ui.info("\n".join(f"{'*' if m == agent.perms.mode else ' '} {m}: {d}" for m, d in MODES.items()))
        else:
            try:
                agent.perms.set_mode(arg)
                banner.update_status(status_line(agent))
            except ValueError as err:
                ui.error(str(err))
    elif command == "init":
        return INIT_PROMPT
    elif command == "prompt":
        path = active_prompt_path(agent.ctx.cwd)
        ui.info(f"Aktiver Prompt: {path}" if path else "Kein Prompt gefunden (wird beim nächsten Start angelegt).")
        ui.info("Datei mit einem Editor ändern – die Änderung gilt ab der nächsten Nachricht. "
                "Projekt-Prompt: .pandora/prompt.md (hat Vorrang).")
    elif command == "playbook":
        try:
            created, skipped = install_playbook(agent.ctx.cwd)
        except OSError as err:
            ui.error(f"playbook/ konnte nicht angelegt werden: {err}")
        else:
            ui.info(f"playbook/: {len(created)} angelegt" + (f", {len(skipped)} vorhanden (nicht überschrieben)" if skipped else "")
                    + ". Beginne mit dem Interview: schreib z. B. \"Starte das Projekt-Interview\".")
    elif command in agent.commands:  # Befehle der Erweiterungen (/plan, /image, /hooks, /mcp, /agents)
        handler, _ = agent.commands[command]
        return handler(arg, agent, ui)
    else:
        ui.error(f"Unbekannter Befehl '/{command}'. /help zeigt alle Befehle.")
    return None


def run_shell(line: str, agent: Agent, ui: UI) -> None:
    try:
        ui.info(agent.tools["Bash"].run(agent.ctx, {"command": line[1:].strip()}))
    except ToolError as err:
        ui.error(str(err))


def repl(agent: Agent, banner: PinnedBanner, ui: UI, first_prompt: str | None) -> None:
    try:
        import readline  # noqa: F401  (aktiviert Zeilenbearbeitung und Verlauf für input())
    except ImportError:
        pass
    pending = first_prompt
    while True:
        banner.ensure()
        if pending:
            text, pending = pending, None
            ui.info(f"\n> {text}")
        else:
            try:
                text = read_input()
            except EOFError:
                break
            except KeyboardInterrupt:
                ui.info("\n(Zum Beenden Strg+D oder /exit)")
                continue
        text = text.strip()
        if not text:
            continue
        try:
            if text.startswith("/"):
                result = handle_command(text, agent, banner, ui)
                if result is EXIT:
                    break
                if result is None:
                    continue
                text = result
            elif text.startswith("!"):
                run_shell(text, agent, ui)
                continue
            agent.run_turn(text)
        except KeyboardInterrupt:
            ui.info("\n⏹ Abgebrochen.")
        except OllamaError as err:
            ui.error(f"✗ {err}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pandora-code", description="Pandora® 🦙 Code – lokaler Coding-Agent für das Terminal (Ollama)"
    )
    parser.add_argument("prompt", nargs="?", help="Startprompt für die interaktive Sitzung")
    parser.add_argument("-p", "--print", dest="print_mode", action="store_true",
                        help="Antwort ausgeben und beenden (nicht interaktiv, liest ggf. von stdin)")
    parser.add_argument("-m", "--model", help="Ollama-Modell (Standard: $PANDORA_MODEL, settings.json oder automatische Wahl)")
    parser.add_argument("--host", help="Ollama-Adresse (Standard: settings.json, $OLLAMA_HOST oder 127.0.0.1:11434)")
    parser.add_argument("--cwd", help="Arbeitsverzeichnis (Standard: aktuelles Verzeichnis)")
    parser.add_argument("--mode", choices=list(MODES), default="ask", help="Berechtigungsmodus")
    parser.add_argument("--yolo", action="store_true", help="Kurzform für --mode yolo")
    parser.add_argument("--disable", action="append", default=[], metavar="ERWEITERUNG", choices=list(MODULES),
                        help=f"Erweiterung nicht laden ({', '.join(MODULES)}); mehrfach angebbar, auch $PANDORA_DISABLE")
    parser.add_argument("--doctor", action="store_true", help="Ollama-Verbindung und Rechte diagnostizieren und beenden")
    parser.add_argument("--no-router", action="store_true",
                        help="Smart Model Router abschalten (immer nur ein Modell nutzen, siehe /router)")
    parser.add_argument("--sandbox", choices=("auto", "firejail", "docker", "off"),
                        help="Sandbox-Backend für Bash-Befehle (Standard: auto, siehe /sandbox)")
    parser.add_argument("--tui", action="store_true",
                        help="Vollständige Terminal-Oberfläche (Textual) statt einfacher Konsole – "
                             "benötigt 'pip install pandora-code[tui]'")
    parser.add_argument("--version", action="version", version=f"Pandora® 🦙 Code {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd()
    if not cwd.is_dir():
        print(f"✗ Kein Verzeichnis: {cwd}", file=sys.stderr)
        return 2

    # Im Modus -p kann nicht nachgefragt werden: neue/geänderte Projekt-Hooks und -MCP-Server bleiben aus.
    settings = load_settings(cwd, (lambda _cwd, _description: False) if args.print_mode else ask_trust)
    # Vorrang Host: --host > "host" in ~/.pandora/settings.json > $OLLAMA_HOST > 127.0.0.1:11434
    client = OllamaClient(args.host or settings.host)
    if args.doctor:
        report, healthy = run_doctor(args.host or settings.host)
        print(report)
        return 0 if healthy else 1
    warning = sudo_warning()
    if warning:
        print(warning, file=sys.stderr)
    try:
        models = client.list_models()
    except OllamaError as err:
        print(f"✗ {err}", file=sys.stderr)
        return 1
    registry = ModelRegistry(client, roles=settings.models)
    registry.seed(models)
    # Vorrang Modell: --model > $PANDORA_MODEL > "model" in ~/.pandora/settings.json > automatische Wahl.
    # Ein AUSDRÜCKLICH genanntes Modell muss installiert sein (klare Fehlermeldung statt stiller Ersatz);
    # nur die automatische Standardwahl (kein Modell angegeben) nutzt die Registry für die beste Wahl.
    # Subagenten und Laufzeit-Ausfälle (Modell während der Sitzung entfernt) wechseln über die Registry
    # dagegen automatisch auf ein installiertes Modell (Hot Reload, siehe agent.py / extensions/subagents.py).
    requested = args.model or os.environ.get("PANDORA_MODEL") or settings.model
    model = requested or registry.best("general") or pick_model(models)
    if not model:
        print("✗ Kein Modell installiert. Beispiel: ollama pull qwen2.5-coder:7b", file=sys.stderr)
        return 1
    if requested and not is_installed(model, models):
        print(f"✗ Modell '{model}' ist nicht installiert (ollama pull {model}).", file=sys.stderr)
        return 1

    ui = UI()
    perms = Permissions("yolo" if args.yolo else args.mode)
    ensure_default_prompt()
    router = TaskRouter(enabled=settings.router and not args.no_router)
    if args.sandbox:
        settings.sandbox = args.sandbox
    agent = Agent(client, model, ToolContext(cwd), perms, ui, prompt_loader=lambda: load_user_prompt(cwd),
                  registry=registry, router=router)
    disabled = set(args.disable) | {n.strip() for n in os.environ.get("PANDORA_DISABLE", "").split(",") if n.strip()}

    try:
        install_all(agent, settings, disabled)
        if args.print_mode:
            prompt = args.prompt or ("" if sys.stdin.isatty() else sys.stdin.read())
            if not prompt.strip():
                print("✗ Im Modus -p wird ein Prompt (Argument oder stdin) benötigt.", file=sys.stderr)
                return 2
            try:
                agent.run_turn(prompt)
            except OllamaError as err:
                print(f"✗ {err}", file=sys.stderr)
                return 1
            return 0

        if args.tui:
            from .ui.tui import INSTALL_HINT, TEXTUAL_AVAILABLE, launch_tui
            if not TEXTUAL_AVAILABLE:
                print(f"✗ {INSTALL_HINT}", file=sys.stderr)
                return 1
            launch_tui(agent, args.prompt)
            return 0

        banner = PinnedBanner(status_line(agent))
        perms.listeners.append(lambda: banner.update_status(status_line(agent)))  # z. B. nach Plan-Freigabe
        banner.start()
        try:
            repl(agent, banner, ui, args.prompt)
        finally:
            banner.stop()
        return 0
    finally:
        agent.close()


def pandora_entry() -> None:
    """Startbefehl `pandora code` (und `pandora`): ein führendes 'code' wird verworfen."""
    argv = sys.argv[1:]
    if argv and argv[0].lower() == "code":
        argv = argv[1:]
    raise SystemExit(main(argv))


def pandora_code_entry() -> None:
    """Startbefehl `pandora-code`."""
    raise SystemExit(main())
