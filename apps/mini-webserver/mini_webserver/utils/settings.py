"""Einstellungen (Ordner, Port, HTTPS, Ollama-Adresse) als JSON-Datei."""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULTS = {"folder": "", "port": 8080, "https": True, "upstream": "http://127.0.0.1:11434"}


def settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "MiniWebserver", "settings.json")


def cert_dir() -> str:
    """Hier liegen CA und Server-Zertifikat (neben den Einstellungen)."""
    return os.path.join(os.path.dirname(settings_path()), "cert")


def load(path: Optional[str] = None) -> dict:
    data = dict(DEFAULTS)
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return data
    if isinstance(raw, dict):
        if isinstance(raw.get("folder"), str):
            data["folder"] = raw["folder"]
        port = raw.get("port")
        if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            data["port"] = port
        if isinstance(raw.get("https"), bool):
            data["https"] = raw["https"]
        if isinstance(raw.get("upstream"), str):
            data["upstream"] = raw["upstream"]
    return data


def save(data: dict, path: Optional[str] = None) -> bool:
    target = path or settings_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False
