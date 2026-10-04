"""Sandbox-Engine: schottet Bash-Befehle des Agenten vom Host-System ab (Firejail oder Docker).

Ersetzt zur Laufzeit die Ausführungslogik des Werkzeugs `Bash` (Schema, Beschreibung fürs Modell und die
Rückfrage-Logik aus permissions.py bleiben unverändert) – der Agent kann so "mutig testen" (rm, Build-
Skripte, Paketinstallationen), ohne das Host-System zu gefährden.

Backends, automatisch erkannt (Rangfolge bei `"sandbox": "auto"`, Standard):
1. **Firejail** – leichtgewichtig, kein Daemon, nutzt weiterhin das Host-Dateisystem/die Host-Toolchain.
   Auf Kali wichtig: apt-installierte Pentest-Werkzeuge bleiben ohne Neuinstallation in einem Image nutzbar.
   Sperrt u. a. Root-Rechte-Erweiterung (`--noroot`), neue Capabilities (`--nonewprivs`) und standardmäßig
   Netzwerkzugriff (`--net=none`).
2. **Docker** – vollständige Container-Isolation, aber nur automatisch aktiv, wenn zusätzlich ein laufender
   Container (`sandboxContainer`) oder ein Image (`sandboxImage`) in den Einstellungen angegeben ist; ohne
   eigenes, vorbereitetes Image/Container fehlen typischerweise die auf dem Host installierten Werkzeuge.
3. Kein Backend gefunden/konfiguriert -> Befehl läuft wie bisher direkt auf dem Host (mit `/sandbox`
   jederzeit einsehbar, kein stiller Rückfall).

`/sandbox [auto|firejail|docker|off]` zeigt Status oder wechselt zur Laufzeit. Einstellungen (`settings.json`):
`"sandbox"`, `"sandboxNetwork"` (bool), `"sandboxImage"`, `"sandboxContainer"`, `"sandboxWorkdir"`.
"""
from __future__ import annotations

import dataclasses
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass

from ..tools import ToolContext, ToolError, as_int, clip

BACKENDS = ("auto", "firejail", "docker", "off")
DOCKER_DAEMON_TIMEOUT = 3  # Sekunden – 'docker info' soll eine einzelne Bash-Anfrage nicht spürbar verzögern
DETECT_TTL = 30.0  # Sekunden: wie lange die Backend-Erkennung zwischengespeichert wird (Hot-Reload-freundlich)


@dataclass
class SandboxConfig:
    backend: str = "auto"
    network: bool = False
    image: str | None = None
    container: str | None = None
    workdir: str | None = None


def which(name: str) -> bool:
    return shutil.which(name) is not None


def docker_daemon_ok() -> bool:
    if not which("docker"):
        return False
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=DOCKER_DAEMON_TIMEOUT)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect() -> dict[str, bool]:
    """Welche Backends grundsätzlich nutzbar wären (Programm gefunden bzw. Daemon erreichbar).
    Als eigene Funktion, damit Tests sie durch eine feste Zuordnung ersetzen können, ohne echte
    Programme zu benötigen."""
    return {"firejail": which("firejail"), "docker": docker_daemon_ok()}


def _firejail_missing_hint() -> str:
    """Firejail ist Linux-only (nutzt Kernel-Namespaces/seccomp) – unter macOS/Windows gibt es dafür kein
    Äquivalent zum Nachinstallieren; dort ist Docker (sandboxContainer/sandboxImage) die einzige Option."""
    system = platform.system()
    if system == "Linux":
        return "firejail nicht installiert (z. B. apt install firejail, dnf install firejail)"
    return f"firejail gibt es nicht für {system} (Linux-only) – nutze stattdessen sandboxContainer/sandboxImage mit Docker"


def resolve(cfg: SandboxConfig, available: dict[str, bool] | None = None) -> tuple[str, str]:
    """Liefert (tatsächliches Backend, menschenlesbare Begründung)."""
    available = detect() if available is None else available
    if cfg.backend == "off":
        return "none", "Sandbox manuell deaktiviert (/sandbox off)"
    if cfg.backend == "firejail":
        if available.get("firejail"):
            return "firejail", "manuell gewählt"
        return "none", _firejail_missing_hint()
    if cfg.backend == "docker":
        if not available.get("docker"):
            return "none", "Docker-Daemon nicht erreichbar (läuft der Docker-Dienst?)"
        if not (cfg.container or cfg.image):
            return "none", "Docker gewählt, aber weder sandboxContainer noch sandboxImage konfiguriert"
        return "docker", "manuell gewählt"
    if cfg.backend != "auto":
        return "none", f"unbekanntes Sandbox-Backend '{cfg.backend}'"
    if available.get("firejail"):
        return "firejail", "auto: firejail gefunden (isoliert, nutzt weiter die Host-Toolchain)"
    if available.get("docker") and (cfg.container or cfg.image):
        return "docker", "auto: Docker-Daemon erreichbar und sandboxContainer/-Image konfiguriert"
    hint = "firejail installieren" if platform.system() == "Linux" else "sandboxContainer/-Image mit Docker setzen"
    return "none", f"kein Sandbox-Backend verfügbar ({hint})"


def build_argv(backend: str, command: str, cfg: SandboxConfig, cwd) -> list[str]:
    if backend == "firejail":
        flags = ["firejail", "--quiet", "--noprofile", "--nonewprivs", "--noroot", "--private-tmp", "--seccomp"]
        if not cfg.network:
            flags.append("--net=none")
        return [*flags, "bash", "-c", command]
    if backend == "docker":
        if cfg.container:
            workdir = cfg.workdir or str(cwd)
            return ["docker", "exec", "-w", workdir, cfg.container, "bash", "-c", command]
        workdir = cfg.workdir or "/workspace"
        net = [] if cfg.network else ["--network", "none"]
        return ["docker", "run", "--rm", "-v", f"{cwd}:{workdir}", "-w", workdir, *net,
                str(cfg.image), "bash", "-c", command]
    raise ValueError(f"Kein Argv für Backend '{backend}'")


@dataclass
class SandboxState:
    """Cacht die (ggf. langsame `docker info`-) Erkennung kurz, statt sie bei jedem Bash-Aufruf neu zu
    prüfen – ähnlich dem Hot-Reload-Cache der ModelRegistry aus Punkt 7."""
    cfg: SandboxConfig
    ttl: float = DETECT_TTL
    _cached: tuple[str, str] | None = None
    _at: float = 0.0

    def current(self) -> tuple[str, str]:
        now = time.monotonic()
        if self._cached is None or now - self._at >= self.ttl:
            self._cached = resolve(self.cfg)
            self._at = now
        return self._cached

    def invalidate(self) -> None:
        self._cached = None


def install(agent, settings) -> None:
    cfg = SandboxConfig(
        backend=getattr(settings, "sandbox", "auto") or "auto",
        network=bool(getattr(settings, "sandbox_network", False)),
        image=getattr(settings, "sandbox_image", None),
        container=getattr(settings, "sandbox_container", None),
        workdir=getattr(settings, "sandbox_workdir", None),
    )
    state = SandboxState(cfg)
    original = agent.tools.get("Bash")
    if original is None:  # Bash-Werkzeug fehlt (z. B. bewusst entfernt) -> Sandbox hat nichts zu umhüllen
        return

    def sandboxed_run(ctx: ToolContext, args: dict) -> str:
        command = args.get("command")
        if not command:
            raise ToolError("'command' fehlt.")
        backend, _ = state.current()
        if backend == "none":
            return original.run(ctx, args)  # unverändertes Host-Verhalten, inkl. bisherigem Zeitlimit-Text
        timeout = min(max(as_int(args.get("timeout"), 120), 1), 600)
        argv = build_argv(backend, str(command), cfg, ctx.cwd)
        try:
            proc = subprocess.run(
                argv, cwd=ctx.cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return f"Abbruch: Zeitlimit von {timeout}s überschritten. [Sandbox: {backend}]"
        except OSError as err:
            state.invalidate()  # Backend evtl. gerade verschwunden (z. B. Docker-Daemon gestoppt) -> neu prüfen
            return f"Fehler: Sandbox-Backend '{backend}' fehlgeschlagen ({err}). Siehe /sandbox."
        output = proc.stdout or ""
        if proc.stderr:
            output += ("\n" if output else "") + "[stderr]\n" + proc.stderr
        return clip(output.strip() or "(keine Ausgabe)") + f"\n[Exit-Code {proc.returncode}] [Sandbox: {backend}]"

    agent.add_tool(dataclasses.replace(
        original,
        run=sandboxed_run,
        description=original.description + " Runs inside an isolated sandbox (Firejail/Docker) when one is "
                                             "available on this system; check /sandbox for the active backend.",
    ))

    def sandbox_command(arg: str, agent, ui) -> str | None:
        choice = arg.strip().lower()
        if choice:
            if choice not in BACKENDS:
                ui.error(f"Nutzung: /sandbox [{'|'.join(BACKENDS)}]")
                return None
            cfg.backend = choice
            state.invalidate()
        backend, reason = state.current()
        available = detect()
        lines = [
            f"Sandbox: {backend} ({reason})",
            f"  Erkannt: firejail={'ja' if available['firejail'] else 'nein'}, "
            f"docker={'ja, Daemon erreichbar' if available['docker'] else 'nein/nicht erreichbar'}",
            f"  Netzwerk in der Sandbox: {'erlaubt' if cfg.network else 'gesperrt'} "
            "(Einstellung 'sandboxNetwork' in settings.json)",
        ]
        if backend == "docker" or cfg.backend == "docker":
            lines.append(f"  Docker: container={cfg.container or '-'}, image={cfg.image or '-'}, "
                         f"workdir={cfg.workdir or '(Standard)'}")
        ui.info("\n".join(lines))
        return None

    agent.register_command(
        "sandbox", sandbox_command,
        f"/sandbox [{'|'.join(BACKENDS)}]  aktives Sandbox-Backend für Bash anzeigen oder wechseln",
    )
