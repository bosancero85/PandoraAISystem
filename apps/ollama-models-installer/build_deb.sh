#!/usr/bin/env bash
# ============================================================
#  Build-Skript: Ollama Modell Installer -> .deb-Paket
#  Ergebnis: dist/ollama-modell-installer_<Version>_all.deb
#
#  Ziel: Raspberry Pi 4B (arm64/armhf) und Acer Aspire 5930G
#        (Kali Linux, amd64) - ebenso jedes andere Debian/Ubuntu.
#
#  Das Paket ist "Architecture: all": reiner Python-Code plus die mitgelieferten
#  reinen Python-Bibliotheken (customtkinter, darkdetect, packaging). Ein
#  einziges .deb laeuft deshalb auf beiden Geraeten - es muss nur einmal
#  gebaut werden (auf einem der beiden oder einem beliebigen Debian-Rechner).
#
#  Voraussetzungen zum Bauen:
#    sudo apt install python3 python3-pip dpkg-dev python3-pil
#  Voraussetzungen zum Ausfuehren (werden per apt automatisch mitinstalliert):
#    python3, python3-tk
#
#  Aufruf:
#    ./build_deb.sh                       Version 1.0.0
#    ./build_deb.sh -v 1.2.0              eigene Version
#    ./build_deb.sh --wheels ./wheels     ohne Internet (vorab geladene Wheels)
#
#  Installation:
#    sudo apt install ./dist/ollama-modell-installer_1.0.0_all.deb
# ============================================================
set -euo pipefail

PKG_NAME="ollama-modell-installer"
APP_TITLE="Ollama Modell Installer"
ENTRY="ollama_model_installer.py"
INSTALL_DIR="/usr/lib/${PKG_NAME}"
VERSION="1.0.0"
MAINTAINER="${MAINTAINER:-Aki_SystemDown <noreply@localhost>}"
WHEELS_DIR=""

info()  { echo "[INFO] $*"; }
fail()  { echo; echo "[FEHLER] $*" >&2; echo "[ABBRUCH] Build nicht erfolgreich." >&2; exit 1; }

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--version) [[ $# -ge 2 ]] || fail "$1 braucht einen Wert."; VERSION="$2"; shift 2 ;;
        --wheels)     [[ $# -ge 2 ]] || fail "$1 braucht einen Ordner."; WHEELS_DIR="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *)            fail "Unbekannte Option: $1 (siehe --help)" ;;
    esac
done

[[ "$VERSION" =~ ^[0-9][A-Za-z0-9.+~-]*$ ]] || fail "Ungueltige Version '$VERSION' (muss mit einer Ziffer beginnen)."

cd "$(dirname "$0")"
ROOT="$(pwd)"

echo
echo "==== ${APP_TITLE} - Debian-Paket (${VERSION}) ===="
echo

# --- Voraussetzungen pruefen ---
[[ -f "$ENTRY" ]] || fail "$ENTRY wurde nicht gefunden."
command -v dpkg-deb >/dev/null 2>&1 || fail "dpkg-deb fehlt. Installation: sudo apt install dpkg-dev"
command -v python3  >/dev/null 2>&1 || fail "python3 fehlt. Installation: sudo apt install python3"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Python 3.9 oder neuer wird benoetigt."
python3 -m pip --version >/dev/null 2>&1 || fail "pip fehlt. Installation: sudo apt install python3-pip"
[[ -z "$WHEELS_DIR" || -d "$WHEELS_DIR" ]] || fail "Wheel-Ordner '$WHEELS_DIR' existiert nicht."

BUILD_DIR="$ROOT/build/deb"
PKG_ROOT="$BUILD_DIR/pkgroot"
TOOLS_DIR="$BUILD_DIR/tools"
APP_DIR="$PKG_ROOT$INSTALL_DIR"
VENDOR_DIR="$APP_DIR/vendor"
OUT_DIR="$ROOT/dist"
DEB_FILE="$OUT_DIR/${PKG_NAME}_${VERSION}_all.deb"

PIP_COMMON=(--disable-pip-version-check --no-compile)
if [[ -n "$WHEELS_DIR" ]]; then
    PIP_COMMON+=(--no-index --find-links "$WHEELS_DIR")
fi

rm -rf "$BUILD_DIR"
mkdir -p "$APP_DIR" "$VENDOR_DIR" "$TOOLS_DIR" "$OUT_DIR" "$PKG_ROOT/DEBIAN"

# --- Python-Bibliotheken mitliefern (rein Python -> architekturunabhaengig) ---
info "Lade Laufzeit-Bibliotheken (requirements-runtime.txt) ..."
python3 -m pip install "${PIP_COMMON[@]}" --target "$VENDOR_DIR" -r requirements-runtime.txt \
    || fail "Installation der Bibliotheken fehlgeschlagen (Internet? sonst --wheels nutzen)."
rm -rf "$VENDOR_DIR/bin"
find "$VENDOR_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

# --- Programmdateien ---
info "Kopiere Programmdateien ..."
install -m 644 "$ENTRY" ollama_library.py platform_support.py ollama_model_installer_icon_256.png "$APP_DIR/"

# --- Icons (hicolor-Theme) ---
info "Erzeuge Icons ..."
ICON_PYTHONPATH=""
if ! python3 -c 'import PIL' >/dev/null 2>&1; then
    info "Pillow fehlt - installiere es voruebergehend (nur fuer die Icon-Erzeugung) ..."
    python3 -m pip install "${PIP_COMMON[@]}" --target "$TOOLS_DIR" "pillow>=10.0" \
        || fail "Pillow nicht verfuegbar. Installation: sudo apt install python3-pil"
    ICON_PYTHONPATH="$TOOLS_DIR"
fi
ICON_SIZES=(16 24 32 48 64 128 256 512)
ICON_TMP="$BUILD_DIR/icons"
PYTHONPATH="$ICON_PYTHONPATH" python3 make_icons.py png "$ICON_TMP" "${ICON_SIZES[@]}" \
    || fail "Icon-Erzeugung fehlgeschlagen."
for size in "${ICON_SIZES[@]}"; do
    dest="$PKG_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dest"
    install -m 644 "$ICON_TMP/icon_${size}.png" "$dest/${PKG_NAME}.png"
done
rm -rf "$ICON_TMP"

# --- Starter, Menue-Eintrag, Dokumentation ---
info "Erzeuge Starter und Menue-Eintrag ..."
mkdir -p "$PKG_ROOT/usr/bin" "$PKG_ROOT/usr/share/applications" "$PKG_ROOT/usr/share/doc/${PKG_NAME}"

cat > "$PKG_ROOT/usr/bin/${PKG_NAME}" <<EOF
#!/bin/sh
# Starter fuer ${APP_TITLE}
APP_DIR="${INSTALL_DIR}"
PYTHONPATH="\$APP_DIR/vendor\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec /usr/bin/python3 "\$APP_DIR/${ENTRY}" "\$@"
EOF
chmod 755 "$PKG_ROOT/usr/bin/${PKG_NAME}"

cat > "$PKG_ROOT/usr/share/applications/${PKG_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_TITLE}
GenericName=Ollama Model Manager
Comment=Ollama-Modelle per Oberflaeche installieren
Exec=${PKG_NAME}
Icon=${PKG_NAME}
Terminal=false
Categories=Utility;Development;
Keywords=ollama;llm;ki;modelle;pandora;
StartupWMClass=OllamaModelInstaller
EOF

install -m 644 README.md "$PKG_ROOT/usr/share/doc/${PKG_NAME}/README.md"
install -m 644 LICENCE   "$PKG_ROOT/usr/share/doc/${PKG_NAME}/copyright"

# --- Paket-Metadaten ---
chmod -R u+rwX,go+rX,go-w "$PKG_ROOT"
find "$PKG_ROOT" -type d -exec chmod 755 {} +
find "$PKG_ROOT" -type f -exec chmod 644 {} +
chmod 755 "$PKG_ROOT/usr/bin/${PKG_NAME}"

INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$PKG_ROOT" | cut -f1)"

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-tk
Recommends: fonts-dejavu-core
Installed-Size: ${INSTALLED_SIZE}
Maintainer: ${MAINTAINER}
Description: Grafischer Installer fuer Ollama-Modelle
 Oberflaeche (CustomTkinter) zum Installieren von Ollama-Modellen:
 kuratierte Pandora-Subagenten-Modelle sowie die komplette Ollama-Bibliothek
 mit Suche, Kategorie-Filter, Groessenauswahl und Batch-Installation.
 Ollama selbst (https://ollama.com/download) muss separat installiert sein.
EOF

cat > "$PKG_ROOT/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
if [ "\$1" = "configure" ]; then
    python3 -m compileall -q ${INSTALL_DIR} >/dev/null 2>&1 || true
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
    fi
fi
exit 0
EOF

cat > "$PKG_ROOT/DEBIAN/postrm" <<EOF
#!/bin/sh
set -e
if [ "\$1" = "remove" ] || [ "\$1" = "purge" ]; then
    # beim Start erzeugte __pycache__-Ordner gehoeren nicht zum Paket
    rm -rf ${INSTALL_DIR}
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
    fi
fi
exit 0
EOF
chmod 755 "$PKG_ROOT/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/postrm"

# --- Vorab-Pruefungen ---
info "Pruefe Quellcode ..."
for f in "$APP_DIR/$ENTRY" "$APP_DIR/ollama_library.py" "$APP_DIR/platform_support.py"; do
    python3 -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$f" \
        || fail "Syntaxfehler in $f"
done
if python3 -c 'import tkinter' >/dev/null 2>&1; then
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$APP_DIR:$VENDOR_DIR" \
        python3 -c 'import customtkinter, ollama_library, platform_support' \
        || fail "Mitgelieferte Bibliotheken lassen sich nicht importieren."
else
    info "python3-tk ist hier nicht installiert - Import-Test uebersprungen."
fi

# --- Paket bauen (xz: auch von aelteren dpkg-Versionen lesbar) ---
info "Baue ${DEB_FILE##*/} ..."
rm -f "$DEB_FILE"
dpkg-deb --root-owner-group -Zxz --build "$PKG_ROOT" "$DEB_FILE" >/dev/null \
    || fail "dpkg-deb ist fehlgeschlagen."
[[ -f "$DEB_FILE" ]] || fail "$DEB_FILE wurde nicht erzeugt."

if command -v lintian >/dev/null 2>&1; then
    info "lintian-Hinweise (unverbindlich):"
    lintian --no-tag-display-limit "$DEB_FILE" || true
fi

echo
dpkg-deb --info "$DEB_FILE" | sed -n '1,14p'
echo
echo "[ERFOLG] Fertig: dist/${DEB_FILE##*/}"
echo
echo "Installation (auf Raspberry Pi und Acer, loest python3-tk automatisch auf):"
echo "    sudo apt install ./dist/${DEB_FILE##*/}"
echo "Start: Menue -> \"${APP_TITLE}\"  oder  ${PKG_NAME}"
echo "Entfernen: sudo apt remove ${PKG_NAME}"
