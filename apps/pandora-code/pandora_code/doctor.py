"""Diagnose (`pandora code --doctor`): findet die typischen Ursachen für Ollama-Startprobleme."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from .ollama_client import OllamaClient, OllamaError, PERMISSION_HINT


def running_with_sudo() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0 and os.environ.get("SUDO_USER"))


def sudo_warning() -> str | None:
    if running_with_sudo():
        return (
            "⚠ Pandora Code läuft mit sudo (root). Das ist nicht nötig und riskant: Einstellungen landen in "
            "/root/.pandora und der Agent hätte Root-Rechte. Bitte ohne sudo starten: pandora code"
        )
    return None


def _models_dir_report() -> list[str]:
    lines: list[str] = []
    env = os.environ.get("OLLAMA_MODELS")
    candidates = [Path(env)] if env else []
    candidates += [Path("/usr/share/ollama/.ollama/models"), Path.home() / ".ollama" / "models"]
    for path in candidates:
        if path.exists():
            ok = os.access(path, os.R_OK | os.X_OK)
            lines.append(f"  {'✓' if ok else '✗'} {path} ({'lesbar' if ok else 'NICHT lesbar für diesen Benutzer'})")
    if Path("/usr/share/ollama").exists() is False and platform.system() == "Linux":
        lines.append("  ✗ /usr/share/ollama existiert nicht (Ursache des mkdir-Fehlers auf dem Server)")
    return lines


def run_doctor(host: str | None = None) -> tuple[str, bool]:
    """Gibt (Bericht, alles_ok) zurück."""
    out = [f"Pandora Code Diagnose ({platform.system()} {platform.machine()}, Python {sys.version.split()[0]})"]
    ok = True
    warning = sudo_warning()
    if warning:
        out.append(warning)
        ok = False
    client = OllamaClient(host, timeout=15)
    out.append(f"Ollama-Adresse: {client.host}")
    try:
        models = client.list_models()
        out.append(f"  ✓ Server erreichbar, {len(models)} Modell(e): {', '.join(models) or '-'}")
    except OllamaError as err:
        out.append(f"  ✗ {err}")
        ok = False
        models = []
    if models:
        try:
            for _ in client.chat_stream(models[0], [{"role": "user", "content": "ok"}]):
                break
            out.append(f"  ✓ Testanfrage an {models[0]} erfolgreich")
        except OllamaError as err:
            out.append(f"  ✗ Testanfrage an {models[0]} fehlgeschlagen: {err}")
            ok = False
    if shutil.which("ollama") is None:
        out.append("  ! Kommando 'ollama' nicht im PATH (nur relevant, wenn der Server lokal laufen soll)")
    if platform.system() == "Linux" and client.host.startswith(("http://127.", "http://localhost")):
        report = _models_dir_report()
        if report:
            out.append("Ollama-Datenverzeichnisse (lokal):")
            out.extend(report)
    if not ok:
        out.append("\n" + PERMISSION_HINT)
    return "\n".join(out), ok
