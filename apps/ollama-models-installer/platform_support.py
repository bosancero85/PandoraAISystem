# Plattform-Helfer fuer den Ollama Modell Installer (Windows / Linux / macOS)
#
# Reine Logik ohne GUI-Abhaengigkeit beim Import (tkinter wird nur bei Bedarf
# geladen), damit sie sich ohne Display testen laesst.

import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Fensterklasse (X11 WM_CLASS) - muss zu StartupWMClass in der .desktop-Datei passen
APP_CLASS = "OllamaModelInstaller"

ICON_ICO = "ollama_model_installer_icon.ico"
ICON_PNG_SMALL = "ollama_model_installer_icon_256.png"

# Monospace-Schriften je Plattform (erste vorhandene gewinnt)
_MONO_CANDIDATES = {
    "win": ["Consolas", "Cascadia Mono", "Courier New"],
    "mac": ["Menlo", "SF Mono", "Monaco", "Courier"],
    "linux": ["DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono", "monospace"],
}


def _platform_key():
    if IS_WINDOWS:
        return "win"
    if IS_MACOS:
        return "mac"
    return "linux"


def default_mono_font():
    """Bevorzugte Monospace-Schrift der aktuellen Plattform (ohne Tk-Abfrage)."""
    return _MONO_CANDIDATES[_platform_key()][0]


def pick_mono_font(root):
    """Erste installierte Monospace-Schrift; benoetigt ein existierendes Tk-Fenster."""
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families(root))
    except Exception:
        return default_mono_font()
    for name in _MONO_CANDIDATES[_platform_key()]:
        if name in available:
            return name
    return default_mono_font()


def no_window_kwargs():
    """Zusatz-Argumente fuer subprocess.run/Popen.

    Unter Windows verhindern sie das Aufblitzen eines Konsolenfensters.
    CREATE_NO_WINDOW allein reicht in manchen Umgebungen nicht aus (z. B. wenn
    ein per winget/App-Alias installiertes ollama.exe selbst einen Shim-Prozess
    startet); zusaetzlich STARTUPINFO mit SW_HIDE deckt diesen Fall ab.
    Auf Linux/macOS gibt es diese Argumente nicht -> leeres Dict.
    """
    if not IS_WINDOWS:
        return {}
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = si
    return kwargs


def _ollama_candidates():
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        paths = []
        for env in ("LOCALAPPDATA", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                paths.append(os.path.join(base, "Programs", "Ollama", "ollama.exe"))
                paths.append(os.path.join(base, "Ollama", "ollama.exe"))
        return paths
    if IS_MACOS:
        return [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama",
            os.path.join(home, "Applications", "Ollama.app", "Contents", "Resources", "ollama"),
        ]
    return [
        "/usr/local/bin/ollama",
        "/usr/bin/ollama",
        "/snap/bin/ollama",
        os.path.join(home, ".local", "bin", "ollama"),
    ]


def find_ollama():
    """Pfad zur ollama-Programmdatei oder None.

    Wichtig fuer macOS: Eine per Finder/Dock gestartete .app erbt nicht den
    PATH der Shell (nur /usr/bin:/bin:/usr/sbin:/sbin), `ollama` wird dort
    ueber PATH allein nicht gefunden - deshalb die bekannten Ablageorte.
    """
    found = shutil.which("ollama")
    if found:
        return found
    for path in _ollama_candidates():
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def ollama_command(*args):
    """Kommandozeile fuer subprocess: vollstaendiger Pfad, sonst nackter Name."""
    return [find_ollama() or "ollama", *args]


def resource_path(name):
    """Pfad zu einer Begleitdatei - im Quellordner, in der .deb-Installation
    und im PyInstaller-Bundle (sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def apply_window_icon(window):
    """Setzt das Fenster-/Dock-Icon; Fehler sind nie fatal."""
    try:
        if IS_WINDOWS:
            ico = resource_path(ICON_ICO)
            if os.path.exists(ico):
                window.iconbitmap(ico)
                # CustomTkinter ueberschreibt das Icon nach ca. 200 ms -> erneut setzen
                window.after(300, lambda: _safe_iconbitmap(window, ico))
            return
        png = resource_path(ICON_PNG_SMALL)
        if os.path.exists(png):
            import tkinter as tk
            image = tk.PhotoImage(file=png)
            window.iconphoto(True, image)
            window._app_icon_ref = image  # Referenz halten, sonst raeumt Python das Bild ab
    except Exception:
        pass


def _safe_iconbitmap(window, ico):
    try:
        window.iconbitmap(ico)
    except Exception:
        pass
