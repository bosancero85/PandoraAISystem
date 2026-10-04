"""Ordner-Logik: Startordner der App und Vorbelegung der Ordnerauswahl."""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """Ordner der .exe (oder des Projekts, wenn aus dem Quellcode gestartet)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def has_html(folder: str) -> bool:
    try:
        return any(n.lower().endswith((".html", ".htm")) for n in os.listdir(folder))
    except OSError:
        return False


def initial_folder(saved: str, base: str) -> str:
    """Liegt die App neben einer HTML-Datei, wird genau dieser Ordner ausgeliefert.

    Sonst gilt der zuletzt benutzte Ordner, und als letzter Ausweg der Ordner der App.
    """
    if has_html(base):
        return base
    if saved and os.path.isdir(saved):
        return saved
    return base
