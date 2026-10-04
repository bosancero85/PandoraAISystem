"""Terminal-Ausgabe für Pandora® 🦙 Code."""
from __future__ import annotations

import os
import sys

ACCENT = "38;5;196"  # Pandora-Rot
DIM = "2"
BOLD = "1"
ERROR = "31"
MAX_RESULT_LINES = 8


def summarize_args(args: dict, limit: int = 100) -> str:
    if not args:
        return ""
    for key in ("command", "file_path", "pattern", "path"):
        if key in args:
            text = str(args[key])
            break
    else:
        text = ", ".join(f"{k}={v!r}" for k, v in args.items())
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def enable_windows_vt() -> None:
    """Aktiviert ANSI-Sequenzen in Windows-Konsolen (Windows Terminal, neue conhost) – idempotent, daher
    ohne Bedenken mehrfach aufrufbar (z. B. von banner.py UND hier, je nachdem was zuerst läuft)."""
    if os.name == "nt":
        os.system("")


class UI:
    def __init__(self, out=None) -> None:
        self.out = out or sys.stdout
        enable_windows_vt()  # unabhängig vom Banner: greift auch im -p/Print-Modus und in Tests mit eigenem 'out'
        isatty = getattr(self.out, "isatty", lambda: False)
        self.color = bool(isatty()) and not os.environ.get("NO_COLOR")
        self._thinking = False

    def paint(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    # -- Antwort-Streaming ---------------------------------------------------
    def begin_assistant(self) -> None:
        self._thinking = False
        self._write("\n")

    def thinking(self, text: str) -> None:
        self._thinking = True
        self._write(self.paint(DIM, text))

    def stream(self, text: str) -> None:
        if self._thinking:
            self._thinking = False
            self._write("\n\n")
        self._write(text)

    def end_assistant(self) -> None:
        self._write("\n")

    # -- Tools -----------------------------------------------------------------
    def tool_call(self, name: str, args: dict) -> None:
        self._write(f"\n{self.paint(ACCENT, '●')} {self.paint(BOLD, name)}({summarize_args(args)})\n")

    def tool_result(self, result: str) -> None:
        lines = result.splitlines() or [""]
        shown = [("  ⎿ " if i == 0 else "    ") + line[:160] for i, line in enumerate(lines[:MAX_RESULT_LINES])]
        if len(lines) > MAX_RESULT_LINES:
            shown.append(f"    … (+{len(lines) - MAX_RESULT_LINES} Zeilen)")
        self._write(self.paint(DIM, "\n".join(shown)) + "\n")

    # -- Meldungen -------------------------------------------------------------
    def info(self, text: str) -> None:
        self._write(self.paint(DIM, text) + "\n")

    def error(self, text: str) -> None:
        self._write(self.paint(ERROR, text) + "\n")
