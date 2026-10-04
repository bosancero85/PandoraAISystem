"""Berechtigungen: Änderungen und Shell-Befehle nur nach Rückfrage (wie bei Claude Code)."""
from __future__ import annotations

from typing import Callable

from .tools import Tool

MODES = {
    "ask": "Vor jeder Änderung und jedem Bash-Befehl fragen",
    "accept-edits": "Write/Edit automatisch erlauben, Bash weiter fragen",
    "plan": "Nur lesen und planen – Änderungen und Bash sind gesperrt",
    "yolo": "Alles automatisch erlauben (Vorsicht!)",
}
AUTO_EDIT_TOOLS = {"Write", "Edit"}


class Permissions:
    def __init__(
        self,
        mode: str = "ask",
        ask: Callable[[str], str] = input,
        show: Callable[[str], None] = print,
    ) -> None:
        self.ask = ask
        self.show = show
        self.always: set[str] = set()
        self.mode = "ask"
        self.previous = "ask"  # Modus vor dem letzten Wechsel (für /plan off)
        self.listeners: list[Callable[[], None]] = []
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unbekannter Modus '{mode}'. Erlaubt: {', '.join(MODES)}")
        if mode != self.mode:
            self.previous = self.mode
        self.mode = mode
        for listener in self.listeners:
            listener()

    def allowed(self, tool: Tool, preview: str) -> bool:
        if not tool.mutating:
            return True
        if self.mode == "plan":  # Plan-Modus geht vor jeder Freigabe, auch vor "immer erlauben"
            return False
        if self.mode == "yolo" or tool.name in self.always:
            return True
        if self.mode == "accept-edits" and tool.name in AUTO_EDIT_TOOLS:
            return True
        self.show(preview)
        while True:
            try:
                answer = self.ask(f"{tool.name} erlauben? [j]a / [i]mmer / [n]ein: ").strip().lower()
            except EOFError:
                return False
            if answer in ("j", "ja", "y", "yes"):
                return True
            if answer in ("i", "immer", "a", "always"):
                self.always.add(tool.name)
                return True
            if answer in ("", "n", "nein", "no"):
                return False
