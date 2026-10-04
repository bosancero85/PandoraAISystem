#!/usr/bin/env bash
# ============================================================
#  Build-Skript: Ollama Modell Installer -> macOS-App
#  Ergebnis: dist/OllamaModelInstaller.app  (optional: .dmg)
#
#  Aufruf (auf einem Mac - PyInstaller kann nicht cross-kompilieren):
#    ./build_mac.sh                 App fuer die eigene Architektur
#    ./build_mac.sh --dmg           zusaetzlich ein .dmg mit Applications-Link
#    ./build_mac.sh --universal2    Intel + Apple Silicon in einer App
#                                   (braucht ein universal2-Python, z. B. python.org)
#    ./build_mac.sh -v 1.2.0        Versionsnummer der App
#
#  Voraussetzungen:
#    - Python 3.9+ MIT Tk 8.6 (python.org-Installer, oder: brew install python-tk)
#      Das Apple-Python der Command Line Tools bringt nur das veraltete Tk 8.5 mit.
#    - Ollama fuer macOS (https://ollama.com/download) - nur zur Laufzeit
#
#  Icon: ollama_model_installer_icon.icns im Projektordner wird verwendet;
#  fehlt sie, wird sie aus ollama_model_installer_icon.png erzeugt
#  (iconutil, sonst Pillow).
# ============================================================
set -euo pipefail

APP_NAME="OllamaModelInstaller"
DISPLAY_NAME="Ollama Modell Installer"
BUNDLE_ID="${BUNDLE_ID:-de.pandora.ollamamodellinstaller}"
ENTRY="ollama_model_installer.py"
ICON_PNG="ollama_model_installer_icon.png"
ICON_ICNS="ollama_model_installer_icon.icns"
ICON_SMALL="ollama_model_installer_icon_256.png"
VENV_DIR=".venv-macos"
VERSION="1.0.0"
MAKE_DMG=0
UNIVERSAL2=0

info() { echo "[INFO] $*"; }
fail() { echo; echo "[FEHLER] $*" >&2; echo "[ABBRUCH] Build nicht erfolgreich." >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dmg)        MAKE_DMG=1; shift ;;
        --universal2) UNIVERSAL2=1; shift ;;
        -v|--version) [[ $# -ge 2 ]] || fail "$1 braucht einen Wert."; VERSION="$2"; shift 2 ;;
        -h|--help)    sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            fail "Unbekannte Option: $1 (siehe --help)" ;;
    esac
done

cd "$(dirname "$0")"
ROOT="$(pwd)"

echo
echo "==== ${APP_NAME} - macOS-Build (${VERSION}) ===="
echo

# --- Voraussetzungen ---
[[ "$(uname -s)" == "Darwin" ]] || fail "Dieses Skript laeuft nur unter macOS. (Linux: build_deb.sh, Windows: build.bat)"
[[ -f "$ENTRY" ]] || fail "$ENTRY wurde nicht gefunden."
[[ -f "$ICON_SMALL" ]] || fail "$ICON_SMALL fehlt (Fenster-Icon)."

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || fail "Python nicht gefunden. Installation: https://www.python.org/downloads/macos/ oder 'brew install python python-tk'."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Python 3.9 oder neuer wird benoetigt (gefunden: $("$PY" -V 2>&1))."
"$PY" -c 'import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' >/dev/null 2>&1 \
    || fail "Python hat kein Tk 8.6 (tkinter fehlt oder ist zu alt). Loesung: python.org-Installer verwenden oder 'brew install python-tk'."

if [[ $UNIVERSAL2 -eq 1 ]]; then
    file "$("$PY" -c 'import sys; print(sys.executable)')" | grep -q "universal binary" \
        || fail "--universal2 braucht ein universal2-Python (python.org-Installer). Ohne die Option baut das Skript fuer $(uname -m)."
fi

# --- Virtuelle Umgebung ---
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    info "Erstelle virtuelle Umgebung in $VENV_DIR ..."
    "$PY" -m venv "$VENV_DIR" || fail "Virtuelle Umgebung konnte nicht erstellt werden."
fi
VPY="$VENV_DIR/bin/python"

info "Installiere Abhaengigkeiten ..."
"$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$VPY" -m pip install --upgrade -r requirements.txt || fail "Installation der Abhaengigkeiten fehlgeschlagen."
"$VPY" -c "import sys, PyInstaller; print('[INFO] Python', sys.version.split()[0], '| PyInstaller', PyInstaller.__version__)"

# --- Icon (.icns) bei Bedarf erzeugen ---
if [[ -f "$ICON_ICNS" ]]; then
    ICNS_PATH="$ROOT/$ICON_ICNS"
    info "Verwende vorhandenes Icon $ICON_ICNS"
else
    [[ -f "$ICON_PNG" ]] || fail "Weder $ICON_ICNS noch $ICON_PNG gefunden."
    info "Erzeuge $ICON_ICNS aus $ICON_PNG ..."
    ICON_BUILD="$ROOT/build/macos-icon"
    rm -rf "$ICON_BUILD"; mkdir -p "$ICON_BUILD"
    ICNS_PATH="$ICON_BUILD/$ICON_ICNS"
    if command -v iconutil >/dev/null 2>&1 \
       && "$VPY" make_icons.py iconset "$ICON_BUILD/app.iconset" \
       && iconutil -c icns "$ICON_BUILD/app.iconset" -o "$ICNS_PATH" 2>/dev/null; then
        :
    else
        info "iconutil nicht nutzbar - verwende Pillow-Fallback."
        "$VPY" make_icons.py icns "$ICNS_PATH" || fail "Icon-Konvertierung fehlgeschlagen."
    fi
    [[ -s "$ICNS_PATH" ]] || fail "Icon-Konvertierung fehlgeschlagen."
fi

# --- App bauen (.app-Bundle, onedir - onefile+windowed ist unter macOS veraltet) ---
info "Baue ${APP_NAME}.app mit PyInstaller ..."
PYI_ARGS=(--noconfirm --clean --windowed
    --name "$APP_NAME"
    --icon "$ICNS_PATH"
    --osx-bundle-identifier "$BUNDLE_ID"
    --collect-all customtkinter
    --add-data "${ICON_SMALL}:."
)
if [[ $UNIVERSAL2 -eq 1 ]]; then
    PYI_ARGS+=(--target-architecture universal2)
fi
"$VPY" -m PyInstaller "${PYI_ARGS[@]}" "$ENTRY" || fail "PyInstaller-Build fehlgeschlagen."

APP_PATH="dist/${APP_NAME}.app"
[[ -d "$APP_PATH" ]] || fail "$APP_PATH wurde nicht erzeugt."

# --- Anzeigename und Version in die Info.plist ---
PLIST="$APP_PATH/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
if [[ -x "$PB" && -f "$PLIST" ]]; then
    "$PB" -c "Set :CFBundleDisplayName $DISPLAY_NAME" "$PLIST" 2>/dev/null \
        || "$PB" -c "Add :CFBundleDisplayName string $DISPLAY_NAME" "$PLIST"
    "$PB" -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null \
        || "$PB" -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST"
    "$PB" -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null \
        || "$PB" -c "Add :CFBundleVersion string $VERSION" "$PLIST"
fi

# --- Ad-hoc-Signatur (Apple Silicon startet nur signierte Programme; Plist-Aenderung invalidiert die alte) ---
if command -v codesign >/dev/null 2>&1; then
    info "Signiere ad hoc ..."
    codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 \
        || info "Ad-hoc-Signatur nicht moeglich - App kann trotzdem laufen."
fi

# --- Optional: .dmg ---
if [[ $MAKE_DMG -eq 1 ]]; then
    command -v hdiutil >/dev/null 2>&1 || fail "hdiutil nicht gefunden."
    DMG_PATH="dist/${APP_NAME}-${VERSION}.dmg"
    STAGE="$ROOT/build/dmg-stage"
    info "Erzeuge $DMG_PATH ..."
    rm -rf "$STAGE" "$DMG_PATH"; mkdir -p "$STAGE"
    cp -R "$APP_PATH" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    hdiutil create -volname "$DISPLAY_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG_PATH" >/dev/null \
        || fail "hdiutil ist fehlgeschlagen."
    rm -rf "$STAGE"
fi

echo
echo "[ERFOLG] Fertig: $APP_PATH"
if [[ $MAKE_DMG -eq 1 ]]; then echo "         und $DMG_PATH"; fi
echo
echo "Start:      open \"$APP_PATH\""
echo "Installieren: App in den Ordner \"Programme\" ziehen."
echo "Hinweis:    Die App ist nicht notarisiert. Auf einem anderen Mac erst per Rechtsklick -> \"Oeffnen\" starten"
echo "            oder:  xattr -dr com.apple.quarantine \"$APP_PATH\""
