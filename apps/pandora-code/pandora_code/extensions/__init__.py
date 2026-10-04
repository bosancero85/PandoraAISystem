"""Erweiterungen: jedes Modul stellt install(agent, settings) bereit.

Bewusst ohne Importe auf Modulebene, damit die Module einzeln (und vom Agenten) importiert werden
können, ohne Importzyklen zu erzeugen.
"""
from __future__ import annotations

import importlib

MODULES = ("hooks", "auto_fix", "plan", "vision", "subagents", "mcp", "ast_graph", "vector_rag", "sandbox",
           "web_search", "plugins", "skills")


def install_all(agent, settings, disabled: set[str] | frozenset[str] = frozenset()) -> None:
    for note in settings.notices:
        agent.notice(note, error=True)
    for name in MODULES:
        if name in disabled:
            continue
        try:
            importlib.import_module(f"{__name__}.{name}").install(agent, settings)
        except Exception as err:  # eine kaputte Erweiterung darf den Start nicht verhindern
            agent.notice(f"Erweiterung '{name}' konnte nicht geladen werden: {type(err).__name__}: {err}", error=True)
