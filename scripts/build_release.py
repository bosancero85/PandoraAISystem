#!/usr/bin/env python3
"""Baut die Release-Pakete von Pandora AI System für das System, auf dem das Skript läuft.

PyInstaller kann nicht für andere Systeme bauen. Deshalb läuft dieses Skript auf jedem Zielsystem
einmal (lokal oder in GitHub Actions) und legt die Dateien mit festen Namen in `release/` ab.
Dieselben Namen stehen in der Landingpage, in der README und in `.github/workflows/release.yml`.

Beispiele:
  python scripts/build_release.py --app all                 alles für dieses System
  python scripts/build_release.py --app webserver --app code
  python scripts/build_release.py --app all --dry-run       nur anzeigen, was gebaut würde
  python scripts/build_release.py --checksums               SHA256SUMS.txt für release/ schreiben
  python scripts/build_release.py --check-assets ordner     prüft, ob alle erwarteten Dateien da sind
  python scripts/build_release.py --list-assets             erwartete Dateinamen ausgeben
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
WORK = ROOT / "build" / "release-work"

APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

OS_TAGS = ("Win", "Mac", "Linux")

# Erwartete Dateien je Werkzeug und System. Einzige Quelle der Wahrheit für Namen.
ASSETS: Dict[str, Dict[str, List[str]]] = {
    "installer": {
        "Win": ["Ollama-Installer-Win.exe"],
        "Mac": ["Ollama-Installer-Mac.dmg"],
        "Linux": ["Ollama-Installer-Linux.AppImage"],
    },
    "webserver": {
        "Win": ["MiniWebserver-Win.exe"],
        "Mac": ["MiniWebserver-Mac.dmg"],
        "Linux": ["MiniWebserver-Linux.AppImage"],
    },
    "code": {
        "Win": ["pandora-code-Win.exe"],
        "Mac": ["pandora-code-Mac.tar.gz"],
        "Linux": ["pandora-code-Linux", "pandora-code-Linux.deb"],
    },
    # Das Web-Paket ist für alle Systeme gleich und wird nur im Linux-Durchlauf gebaut.
    "chat": {"Win": [], "Mac": [], "Linux": ["Ollama-Browser-Chat-Web.zip"]},
}
APP_ORDER = ("installer", "webserver", "code", "chat")


class BuildError(Exception):
    pass


def current_os() -> str:
    if sys.platform.startswith("win"):
        return "Win"
    if sys.platform == "darwin":
        return "Mac"
    if sys.platform.startswith("linux"):
        return "Linux"
    raise BuildError("Nicht unterstütztes System: %s" % sys.platform)


def expected_assets(os_tags=OS_TAGS, apps=APP_ORDER) -> List[str]:
    return [name for app in apps for tag in os_tags for name in ASSETS[app][tag]]


@dataclass
class Step:
    """Ein Arbeitsschritt: entweder ein Befehl oder eine Python-Funktion."""
    desc: str
    cmd: Optional[List[str]] = None
    cwd: Optional[Path] = None
    func: Optional[Callable[[], None]] = None
    env: Dict[str, str] = field(default_factory=dict)

    def show(self) -> str:
        if self.cmd:
            return "$ %s%s" % ("(cd %s) " % self.cwd.relative_to(ROOT) if self.cwd and self.cwd != ROOT else "", " ".join(_quote(c) for c in self.cmd))
        return "  %s" % self.desc

    def run(self) -> None:
        if self.func:
            self.func()
            return
        env = dict(os.environ)
        env.update(self.env)
        result = subprocess.run(self.cmd, cwd=str(self.cwd or ROOT), env=env)
        if result.returncode != 0:
            raise BuildError("Befehl fehlgeschlagen (Code %d): %s" % (result.returncode, " ".join(self.cmd)))


def _quote(text: str) -> str:
    text = str(text)
    return '"%s"' % text if (" " in text or ";" in text) else text


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


# ----------------------------------------------------------------------------------------------
# Hilfsfunktionen für Schritte
# ----------------------------------------------------------------------------------------------
def pyinstaller(name: str, entry: Path, app_dir: Path, work: Path, extra: List[str]) -> Step:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--name", name, "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
           "--specpath", str(work), "--paths", str(app_dir)] + extra + [str(entry)]
    return Step("PyInstaller: %s" % name, cmd=cmd, cwd=app_dir)


def add_data(src: Path, dest: str = ".") -> List[str]:
    return ["--add-data", "%s%s%s" % (src, os.pathsep, dest)]


def copy_to_release(src: Path, name: str) -> Step:
    def _copy() -> None:
        if not src.exists():
            raise BuildError("Erwartete Datei wurde nicht gebaut: %s" % src)
        RELEASE.mkdir(parents=True, exist_ok=True)
        target = RELEASE / name
        shutil.copy2(src, target)
        if not name.endswith((".exe", ".dmg", ".zip", ".gz", ".deb")):
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Step("kopiere %s -> release/%s" % (_rel(src), name), func=_copy)


def make_dmg(app_bundle: Path, volume: str, name: str) -> Step:
    RELEASE.mkdir(parents=True, exist_ok=True)
    return Step("DMG erstellen", cmd=["hdiutil", "create", "-volname", volume, "-srcfolder", str(app_bundle),
                                       "-ov", "-format", "UDZO", str(RELEASE / name)])


def make_appimage(binary: Path, work: Path, app_id: str, display: str, icon_png: Path, name: str) -> Step:
    """AppDir zusammenstellen und mit appimagetool zu einer .AppImage packen."""
    def _build() -> None:
        appdir = work / "AppDir"
        if appdir.exists():
            shutil.rmtree(appdir)
        (appdir / "usr" / "bin").mkdir(parents=True)
        shutil.copy2(binary, appdir / "usr" / "bin" / binary.name)
        shutil.copy2(icon_png, appdir / (app_id + ".png"))
        shutil.copy2(icon_png, appdir / ".DirIcon")
        run = appdir / "AppRun"
        run.write_text('#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/bin/%s" "$@"\n' % binary.name, encoding="utf-8")
        run.chmod(0o755)
        (appdir / (app_id + ".desktop")).write_text(
            "[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nIcon=%s\nCategories=Utility;\n" % (display, binary.name, app_id), encoding="utf-8")
        tool = os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool")
        if not tool:
            tool_path = work / "appimagetool-x86_64.AppImage"
            if not tool_path.exists():
                print("  lade appimagetool ...")
                urllib.request.urlretrieve(APPIMAGETOOL_URL, tool_path)
            tool_path.chmod(0o755)
            tool = str(tool_path)
        RELEASE.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
        result = subprocess.run([tool, str(appdir), str(RELEASE / name)], env=env)
        if result.returncode != 0:
            raise BuildError("appimagetool ist fehlgeschlagen (Code %d)" % result.returncode)
    return Step("AppImage zusammenstellen: %s" % name, func=_build)


# ----------------------------------------------------------------------------------------------
# Pläne je Werkzeug
# ----------------------------------------------------------------------------------------------
def plan_installer(os_tag: str) -> List[Step]:
    app = ROOT / "apps" / "ollama-models-installer"
    work = WORK / "installer"
    ico, png, png256 = (app / ("ollama_model_installer_icon" + s) for s in (".ico", ".png", "_256.png"))
    entry = app / "ollama_model_installer.py"
    data = add_data(ico) + add_data(png) + add_data(png256)
    common = ["--collect-all", "customtkinter"]
    if os_tag == "Win":
        return [pyinstaller("Ollama-Installer-Win", entry, app, work,
                            ["--onefile", "--windowed", "--icon", str(ico)] + common + data),
                copy_to_release(work / "dist" / "Ollama-Installer-Win.exe", "Ollama-Installer-Win.exe")]
    if os_tag == "Mac":
        return [pyinstaller("Ollama-Installer", entry, app, work, ["--windowed", "--icon", str(png256)] + common + data),
                make_dmg(work / "dist" / "Ollama-Installer.app", "Ollama Installer", "Ollama-Installer-Mac.dmg")]
    return [pyinstaller("Ollama-Installer", entry, app, work, ["--onefile"] + common + data),
            make_appimage(work / "dist" / "Ollama-Installer", work, "ollama-installer", "Ollama Installer", png256,
                          "Ollama-Installer-Linux.AppImage")]


def plan_webserver(os_tag: str) -> List[Step]:
    app = ROOT / "apps" / "mini-webserver"
    work = WORK / "webserver"
    entry = app / "main.py"
    ico, png = app / "assets" / "icon.ico", work / "icon.png"
    common = ["--collect-all", "customtkinter"]
    make_ico = Step("Symbol erzeugen (.ico)", cmd=[sys.executable, "-m", "mini_webserver.utils.icon", str(ico)], cwd=app)
    make_png = Step("Symbol erzeugen (.png)", cmd=[sys.executable, "-m", "mini_webserver.utils.icon", str(png)], cwd=app)
    if os_tag == "Win":
        return [make_ico, pyinstaller("MiniWebserver-Win", entry, app, work,
                                      ["--onefile", "--noconsole", "--icon", str(ico), "--hidden-import", "pystray._win32"] + common),
                copy_to_release(work / "dist" / "MiniWebserver-Win.exe", "MiniWebserver-Win.exe")]
    if os_tag == "Mac":
        return [make_png, pyinstaller("MiniWebserver", entry, app, work,
                                      ["--windowed", "--icon", str(png), "--hidden-import", "pystray._darwin"] + common),
                make_dmg(work / "dist" / "MiniWebserver.app", "Mini Webserver", "MiniWebserver-Mac.dmg")]
    return [make_png, pyinstaller("MiniWebserver", entry, app, work,
                                  ["--onefile", "--hidden-import", "pystray._xorg"] + common),
            make_appimage(work / "dist" / "MiniWebserver", work, "mini-webserver", "Mini Webserver", png,
                          "MiniWebserver-Linux.AppImage")]


def plan_code(os_tag: str) -> List[Step]:
    app = ROOT / "apps" / "pandora-code"
    work = WORK / "code"
    entry = app / "pandora_code_bundle.py"
    # Die Erweiterungen werden zur Laufzeit per importlib geladen, PyInstaller findet sie nicht von selbst.
    common = ["--onefile", "--console", "--collect-submodules", "pandora_code", "--collect-data", "pandora_code"]
    if os_tag == "Win":
        return [pyinstaller("pandora-code-Win", entry, app, work, common),
                copy_to_release(work / "dist" / "pandora-code-Win.exe", "pandora-code-Win.exe")]
    if os_tag == "Mac":
        def _tar() -> None:
            binary = work / "dist" / "pandora-code"
            if not binary.exists():
                raise BuildError("Erwartete Datei wurde nicht gebaut: %s" % binary)
            RELEASE.mkdir(parents=True, exist_ok=True)
            with tarfile.open(RELEASE / "pandora-code-Mac.tar.gz", "w:gz") as tar:
                tar.add(binary, arcname="pandora-code")
        return [pyinstaller("pandora-code", entry, app, work, common), Step("tar.gz packen", func=_tar)]
    deb_dir = app / "dist"

    def _deb() -> None:
        debs = sorted(deb_dir.glob("pandora-code_*_all.deb"), key=lambda p: p.stat().st_mtime)
        if not debs:
            raise BuildError("Kein .deb in %s gefunden" % deb_dir)
        RELEASE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(debs[-1], RELEASE / "pandora-code-Linux.deb")
    return [pyinstaller("pandora-code-Linux", entry, app, work, common),
            copy_to_release(work / "dist" / "pandora-code-Linux", "pandora-code-Linux"),
            Step("Debian-Paket bauen", cmd=["bash", "build_deb.sh"], cwd=app),
            Step("kopiere .deb -> release/pandora-code-Linux.deb", func=_deb)]


CHAT_EXCLUDE_DIRS = {"tests", "playbook", ".git", "node_modules", "__pycache__"}


def chat_zip_files(app: Path) -> List[Path]:
    files = []
    for path in sorted(app.rglob("*")):
        rel = path.relative_to(app)
        if path.is_file() and not (set(rel.parts[:-1]) & CHAT_EXCLUDE_DIRS) and path.suffix != ".pyc":
            files.append(path)
    return files


def plan_chat(os_tag: str) -> List[Step]:
    app = ROOT / "apps" / "ollama-browser-chat"

    def _zip() -> None:
        RELEASE.mkdir(parents=True, exist_ok=True)
        target = RELEASE / "Ollama-Browser-Chat-Web.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in chat_zip_files(app):
                zf.write(path, "Ollama-Browser-Chat/" + path.relative_to(app).as_posix())
    return [Step("Web-Paket packen: Ollama-Browser-Chat-Web.zip", func=_zip)]


PLANNERS = {"installer": plan_installer, "webserver": plan_webserver, "code": plan_code, "chat": plan_chat}


def make_plan(apps: List[str], os_tag: str) -> List[Step]:
    steps: List[Step] = []
    for app in apps:
        steps.append(Step("== %s (%s) ==" % (app, os_tag), func=lambda: None))
        steps.extend(PLANNERS[app](os_tag))
    return steps


# ----------------------------------------------------------------------------------------------
# Prüfsummen und Vollständigkeit
# ----------------------------------------------------------------------------------------------
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(folder: Path) -> Path:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    if not files:
        raise BuildError("Keine Dateien in %s" % folder)
    out = folder / "SHA256SUMS.txt"
    out.write_text("".join("%s  %s\n" % (sha256(p), p.name) for p in files), encoding="utf-8", newline="\n")
    return out


def missing_assets(folder: Path) -> List[str]:
    return [name for name in expected_assets() if not (folder / name).is_file()]


# ----------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", action="append", choices=list(APP_ORDER) + ["all"], help="Was gebaut wird (mehrfach möglich)")
    ap.add_argument("--os", choices=OS_TAGS, help="Zielsystem (nur mit --dry-run sinnvoll, Standard: dieses System)")
    ap.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ausführen")
    ap.add_argument("--checksums", action="store_true", help="SHA256SUMS.txt in release/ schreiben")
    ap.add_argument("--check-assets", metavar="ORDNER", help="Prüft, ob alle erwarteten Dateien im Ordner liegen")
    ap.add_argument("--list-assets", action="store_true", help="Alle erwarteten Dateinamen ausgeben")
    args = ap.parse_args(argv)

    try:
        if args.list_assets:
            print("\n".join(expected_assets()))
            return 0
        if args.check_assets:
            folder = Path(args.check_assets)
            if not folder.is_dir():
                raise BuildError("Ordner nicht gefunden: %s" % folder)
            missing = missing_assets(folder)
            if missing:
                raise BuildError("Es fehlen %d Datei(en): %s" % (len(missing), ", ".join(missing)))
            print("[OK] Alle %d erwarteten Dateien sind vorhanden." % len(expected_assets()))
            return 0
        if args.checksums:
            out = write_checksums(RELEASE)
            print("[OK] %s geschrieben" % out)
            return 0
        if not args.app:
            ap.error("Bitte --app angeben (zum Beispiel --app all)")
        os_tag = args.os or current_os()
        if args.os and args.os != current_os() and not args.dry_run:
            raise BuildError("PyInstaller baut nur für das eigene System (%s). --os geht nur mit --dry-run." % current_os())
        apps = list(APP_ORDER) if "all" in args.app else [a for a in APP_ORDER if a in args.app]
        steps = make_plan(apps, os_tag)
        for step in steps:
            print(step.show())
            if not args.dry_run:
                step.run()
        if not args.dry_run:
            print("\n[OK] Fertig. Dateien in %s:" % RELEASE)
            for p in sorted(RELEASE.iterdir()):
                print("  %-36s %8.1f MB" % (p.name, p.stat().st_size / 1e6))
        return 0
    except BuildError as exc:
        print("[FEHLER] %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
