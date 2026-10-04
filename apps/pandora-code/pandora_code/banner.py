"""Pandora® 🦙 Code – ASCII-Banner, das immer ganz oben stehen bleibt.

Technik: Der Banner wird in die obersten Zeilen des Terminals gezeichnet und
danach per ANSI-Scroll-Region (DECSTBM) vom Scrollen ausgenommen. Alles Weitere
(Eingabe, Antworten, Tool-Ausgaben) scrollt nur noch unterhalb des Banners.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys

ESC = "\x1b"

BRAND = """
=====================================================================

     ██████╗  █████╗ ███╗   ██╗██████╗  ██████╗ ██████╗  █████╗ 
     ██╔══██╗██╔══██╗████╗  ██║██╔══██╗██╔═══██╗██╔══██╗██╔══██╗
     ██████╔╝███████║██╔██╗ ██║██║  ██║██║   ██║██████╔╝███████║
     ██╔═══╝ ██╔══██║██║╚██╗██║██║  ██║██║   ██║██╔══██╗██╔══██║
     ██║     ██║  ██║██║ ╚████║██████╔╝╚██████╔╝██║  ██║██║  ██║
     ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  

                         ░█▀▀░█▀█░█▀▄░█▀▀
                         ░█░░░█░█░█░█░█▀▀
                         ░▀▀▀░▀▀▀░▀▀░░▀▀▀

=====================================================================
"""


def _enable_vt() -> None:
    """Aktiviert ANSI-Sequenzen in Windows-Konsolen (Windows Terminal, neue conhost)."""
    from .ui import enable_windows_vt
    enable_windows_vt()


def ASCII_BRANDING() -> None:
    """Original-Funktion aus pandora_code_ascci_banner.py (jetzt mit import os)."""
    os.system("cls" if os.name == "nt" else "clear")
    print(BRAND)


class PinnedBanner:
    """Zeichnet den Banner oben und hält ihn dort fest."""

    MIN_FREE_ROWS = 10  # so viele Zeilen sollen unter dem Banner mindestens frei bleiben

    def __init__(self, status: str = "") -> None:
        self.brand_lines = [line.rstrip() for line in BRAND.strip("\n").splitlines()]
        self.status = status
        self.pinned = False
        self._size = (0, 0)

    # -- Hilfsfunktionen ---------------------------------------------------
    @property
    def height(self) -> int:
        return len(self.brand_lines) + 1  # + Statuszeile

    @property
    def width(self) -> int:
        return max(len(line) for line in self.brand_lines)

    def _term(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def _can_pin(self, cols: int, rows: int) -> bool:
        return sys.stdout.isatty() and cols >= self.width and rows >= self.height + self.MIN_FREE_ROWS

    def _status_line(self, cols: int) -> str:
        text = self.status
        return text if len(text) < cols else text[: max(cols - 2, 0)] + "…"

    def _paint(self, cols: int) -> None:
        write = sys.stdout.write
        for row, line in enumerate(self.brand_lines, start=1):
            write(f"{ESC}[{row};1H{ESC}[2K{line}")
        write(f"{ESC}[{self.height};1H{ESC}[2K{self._status_line(cols)}")

    # -- Öffentliche API ---------------------------------------------------
    def start(self) -> None:
        _enable_vt()
        cols, rows = self._term()
        if not self._can_pin(cols, rows):
            # Kein Terminal oder zu klein: Banner einmal normal ausgeben.
            print("\n".join(self.brand_lines))
            print(self.status)
            print()
            return
        self.pinned = True
        self._size = (cols, rows)
        atexit.register(self.stop)
        sys.stdout.write(f"{ESC}[2J{ESC}[H")
        self._paint(cols)
        sys.stdout.write(f"{ESC}[{self.height + 1};{rows}r")  # Scroll-Region unter dem Banner
        sys.stdout.write(f"{ESC}[{self.height + 1};1H")
        sys.stdout.flush()

    def update_status(self, status: str) -> None:
        """Ändert die Statuszeile (Modell, Modus) ohne die Cursor-Position zu verlieren."""
        self.status = status
        if not self.pinned:
            return
        cols, _ = self._term()
        sys.stdout.write(f"{ESC}7")
        self._paint(cols)
        sys.stdout.write(f"{ESC}8")
        sys.stdout.flush()

    def ensure(self) -> None:
        """Nach Größenänderung des Fensters neu zeichnen (vor jeder Eingabe aufrufen)."""
        if not self.pinned:
            return
        size = self._term()
        if size == self._size:
            return
        cols, rows = size
        if not self._can_pin(cols, rows):
            self.stop()
            return
        self._size = size
        self._paint(cols)
        sys.stdout.write(f"{ESC}[{self.height + 1};{rows}r{ESC}[{rows};1H")
        sys.stdout.flush()

    def clear_body(self) -> None:
        """Löscht nur den Bereich unter dem Banner (für /clear)."""
        if self.pinned:
            sys.stdout.write(f"{ESC}[{self.height + 1};1H{ESC}[0J")
        elif sys.stdout.isatty():
            sys.stdout.write(f"{ESC}[2J{ESC}[H")
        sys.stdout.flush()

    def stop(self) -> None:
        """Hebt die Scroll-Region auf und setzt den Cursor ans Ende."""
        if not self.pinned:
            return
        self.pinned = False
        _, rows = self._term()
        sys.stdout.write(f"{ESC}[r{ESC}[{rows};1H\n")
        sys.stdout.flush()
