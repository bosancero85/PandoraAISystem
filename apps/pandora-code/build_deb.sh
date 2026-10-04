#!/usr/bin/env bash
# build_deb.sh – baut ein Debian-Paket (.deb) aus Pandora Code.
#
# Pandora Code ist reines Python ohne Pflicht-Abhängigkeiten (siehe pyproject.toml: dependencies = []) –
# es wird nichts kompiliert. Deshalb genügt EIN einziges "Architecture: all"-Paket für BEIDE Zielsysteme:
#   - Raspberry Pi 4B (arm64, Kali Linux)
#   - Acer Aspire 5930g (amd64, Kali Linux)
# Ein architekturabhängiges Paket (je eins für arm64/amd64) wäre hier technisch unnötige Mehrarbeit und
# würde zwei inhaltsgleiche .deb-Dateien erzeugen – das "all"-Paket installiert sich identisch auf beiden.
#
# Verwendung:
#   ./build_deb.sh [version]          # Version optional, sonst aus pandora_code/__init__.py gelesen
# Ergebnis:
#   dist/pandora-code_<version>_all.deb
#
# Installation auf dem Zielsystem (Pi 4B und Acer gleichermaßen):
#   sudo apt install ./pandora-code_<version>_all.deb      # löst die python3-Abhängigkeit automatisch mit
#   # oder:
#   sudo dpkg -i ./pandora-code_*.deb && sudo apt -f install
#
# Danach überall im Terminal nutzbar:
#   pandora code
#   pandora-code --doctor
#
# Zum BAUEN wird nur dpkg-deb gebraucht (Teil von dpkg, auf jedem Debian/Kali-System vorhanden) – kein
# pip, kein venv, keine Internetverbindung. fakeroot/lintian werden genutzt, wenn vorhanden, sind aber
# optional (ohne fakeroot baut dpkg-deb trotzdem korrekt, dank --root-owner-group seit dpkg 1.19.1).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "FEHLER: dpkg-deb wurde nicht gefunden. Dieses Skript baut ein Debian-Paket und braucht dafür" >&2
    echo "        ein Debian-/Kali-/Ubuntu-artiges System (dpkg-deb ist Teil des Pakets 'dpkg')." >&2
    exit 1
fi

PKG_NAME="pandora-code"
ARCH="all"
PY_MIN="3.9"
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    VERSION="$(python3 -c "import re,sys; sys.path.insert(0,'.'); from pandora_code import __version__; print(__version__)")"
fi
echo "==> Baue ${PKG_NAME} ${VERSION} (${ARCH}) für Raspberry Pi 4B und Acer Aspire 5930g (Kali Linux) ..."

BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf "$BUILD_ROOT"' EXIT
chmod 755 "$BUILD_ROOT"   # mktemp -d legt 700 an; ohne diese Korrektur würde das Paketwurzelverzeichnis
                          # mit unpassenden Rechten ins Archiv wandern.

# -- Dateibaum ---------------------------------------------------------------------------------------------
LIB_DIR="$BUILD_ROOT/usr/lib/python3/dist-packages"
BIN_DIR="$BUILD_ROOT/usr/bin"
DOC_DIR="$BUILD_ROOT/usr/share/doc/${PKG_NAME}"
DEBIAN_DIR="$BUILD_ROOT/DEBIAN"
mkdir -p "$LIB_DIR" "$BIN_DIR" "$DOC_DIR" "$DEBIAN_DIR"

# Python-Paket in den Debian-Standardpfad für system-weite Pakete kopieren (python3 findet es dort ohne
# venv/PYTHONPATH-Tricks) – Tests, __pycache__ und Bytecode bleiben draußen.
cp -r pandora_code "$LIB_DIR/"
find "$LIB_DIR/pandora_code" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$LIB_DIR/pandora_code" -name "*.pyc" -delete

# Sofort prüfen, ob das kopierte Paket überhaupt importierbar ist – lieber der Build bricht ab, als ein
# kaputtes .deb auf Aki's Geräte zu bringen.
if ! PYTHONPATH="$LIB_DIR" python3 -c "import pandora_code, pandora_code.cli" 2>/tmp/pandora_build_err; then
    echo "FEHLER: pandora_code lässt sich nach dem Kopieren nicht importieren:" >&2
    cat /tmp/pandora_build_err >&2
    exit 1
fi
rm -f /tmp/pandora_build_err

[ -f README.md ] && cp README.md "$DOC_DIR/"
cat > "$DOC_DIR/changelog.Debian" <<EOF
${PKG_NAME} (${VERSION}) stable; urgency=low

  * Siehe README.md im selben Ordner.

 -- Aki (AKI_SystemDown (R) / Pandora (R))  $(date -R)
EOF
gzip -9nf "$DOC_DIR/changelog.Debian"

# Rechte normalisieren: die Quelldateien in diesem Arbeitsordner können je nach Entstehung (Editor, Tool,
# umask) unterschiedliche, teils zu enge Rechte haben (z. B. 600 = nur für root lesbar). Ohne diese
# Normalisierung könnte 'import pandora_code' nach der Installation für normale Nutzer fehlschlagen – ein
# System-Python-Paket muss für alle lesbar sein. Verzeichnisse 755, Dateien 644; ausführbare Skripte
# (Wrapper, postinst) bekommen ihr +x danach gezielt zurück, siehe unten.
find "$BUILD_ROOT" -type d -exec chmod 755 {} +
find "$BUILD_ROOT" -type f -exec chmod 644 {} +

# -- Start-Skripte: dünne Wrapper, kein venv nötig (reines stdlib-Paket) -----------------------------------
cat > "$BIN_DIR/pandora-code" <<'EOF'
#!/bin/sh
# Startbefehl 'pandora-code' (Bindestrich-Variante). Siehe auch /usr/bin/pandora für 'pandora code'.
exec python3 -m pandora_code "$@"
EOF

cat > "$BIN_DIR/pandora" <<'EOF'
#!/bin/sh
# Startbefehl 'pandora code ...': ein führendes 'code' (beliebige Groß-/Kleinschreibung) wird entfernt,
# genau wie es pandora_code.cli.pandora_entry() auch beim pip-Einstiegspunkt tut. 'pandora --doctor' und
# weitere Optionen funktionieren ebenso direkt, ganz ohne 'code' davor.
case "${1:-}" in
    code|Code|CODE) shift ;;
esac
exec python3 -m pandora_code "$@"
EOF
chmod 755 "$BIN_DIR/pandora-code" "$BIN_DIR/pandora"

# -- DEBIAN/control ------------------------------------------------------------------------------------------
INSTALLED_SIZE="$(cd "$BUILD_ROOT" && du -sk --exclude=DEBIAN . | cut -f1)"
cat > "$DEBIAN_DIR/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: devel
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Depends: python3 (>= ${PY_MIN})
Recommends: firejail, docker.io
Maintainer: Aki (AKI_SystemDown (R) / Pandora (R)) <aki@akisystemdown.local>
Description: Lokaler Coding-Agent fuers Terminal (Ollama)
 Pandora Code ist ein interaktiver Coding-Agent im Terminal, Nachbau des
 Claude-Code-Bedienkonzepts, der vollstaendig ueber eine lokale
 Ollama-Instanz laeuft. Enthaelt einen Smart Model Router, einen
 AST-Code-Graph, lokales Vektor-RAG, eine Sandbox-Engine
 (Firejail/Docker), einen Auto-Fix-Loop, WebSearch/WebFetch sowie
 eine optionale Textual-TUI (pandora code --tui).
 .
 Benoetigt einen erreichbaren Ollama-Server (separat installieren,
 siehe https://ollama.com). Optionale Zusatzfunktionen (Tree-sitter,
 Textual-TUI, Playwright) lassen sich bei Bedarf nachruesten:
   pip install --break-system-packages 'pandora-code[ast,tui,web]'
EOF

# -- postinst: kurze Erfolgsmeldung + Hinweis, falls Ollama fehlt -------------------------------------------
cat > "$DEBIAN_DIR/postinst" <<'EOF'
#!/bin/sh
set -e
if ! command -v ollama >/dev/null 2>&1; then
    echo "Hinweis: 'ollama' wurde auf diesem System nicht gefunden."
    echo "Pandora Code braucht einen erreichbaren Ollama-Server: https://ollama.com"
fi
echo "Pandora Code installiert. Start: pandora code"
exit 0
EOF
chmod 755 "$DEBIAN_DIR/postinst"

# -- bauen -----------------------------------------------------------------------------------------------
mkdir -p dist
OUT="dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
rm -f "$OUT"
if command -v fakeroot >/dev/null 2>&1; then
    fakeroot dpkg-deb --build --root-owner-group "$BUILD_ROOT" "$OUT"
else
    dpkg-deb --build --root-owner-group "$BUILD_ROOT" "$OUT"
fi

echo "==> Fertig: ${OUT}"
echo "    Installation (Pi 4B und Acer gleichermaßen): sudo apt install ./${OUT}"
if command -v lintian >/dev/null 2>&1; then
    echo "==> lintian-Prüfung:"
    lintian "$OUT" || true
fi
