<div align="center">

<img src="ollama_model_installer_icon_256.png" alt="Ollama Modell Installer" width="128">

# Ollama Modell Installer

**Grafische Oberfläche zum Installieren von Ollama-Modellen – mit der kompletten Ollama-Bibliothek, Suche, Filtern und Batch-Installation.**

![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green.svg)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)
![Plattformen](https://img.shields.io/badge/Plattformen-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![GUI: CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-9D00FF.svg)

</div>

---

## Inhalt

- [Überblick](#überblick)
- [Funktionen](#funktionen)
- [Voraussetzungen](#voraussetzungen)
- [Schnellstart](#schnellstart)
- [Bedienung](#bedienung)
- [Fertige Programme bauen](#fertige-programme-bauen)
- [Modell-Empfehlungen](#modell-empfehlungen)
- [Häufige Probleme](#häufige-probleme)
- [Projektstruktur](#projektstruktur)
- [Entwicklung und Tests](#entwicklung-und-tests)
- [Lizenz](#lizenz)

## Überblick

Der Ollama Modell Installer ersetzt das Tippen von `ollama pull …` durch eine übersichtliche Oberfläche. Er kennt **238 Modellfamilien** der offiziellen [Ollama-Bibliothek](https://ollama.com/library), zeigt an, welche bereits installiert sind, schätzt vor dem Download den Speicherbedarf und lädt die gewählten Modelle nacheinander herunter – mit Fortschrittsanzeige, Geschwindigkeit und Restzeit.

Der Installer ruft im Hintergrund lediglich `ollama list` und `ollama pull` auf. Es werden keine Konten, Server oder Telemetrie benötigt.

<!-- Screenshot einfügen: docs/screenshot.png -->

## Funktionen

- **Komplette Bibliothek:** 238 Modellfamilien (Stand 2026-09-28), fest eingebauter Katalog – funktioniert offline.
- **Suche und Kategorien:** Allgemein, Code, Reasoning, Vision und Embeddings.
- **Größenauswahl je Modell:** jede verfügbare Variante (z. B. `3b`, `8b`, `14b`) einzeln wählbar; Fähigkeiten wie Tools, Thinking und Vision werden angezeigt.
- **„Gefilterte auswählen“:** wählt je Modell die größte Variante innerhalb eines Größenlimits (≤ 4B, ≤ 8B, ≤ 14B, ≤ 32B oder unbegrenzt; Standard ≤ 8B).
- **Installiert-Status:** Abgleich mit `ollama list`, installierte Modelle sind markiert.
- **Speicherschätzung:** vor dem Download ein Dialog mit geschätzter Gesamtgröße (grob, Q4-Quantisierung) und freiem Speicherplatz auf dem Modell-Laufwerk.
- **Batch-Installation:** beliebig viele Modelle nacheinander, mit Gesamtfortschritt und Abbruch-Knopf.
- **Live-Konsole:** Ausgabe von `ollama pull` im Programm, ohne aufblitzende Konsolenfenster unter Windows.
- **Cloud-Modelle** (12 Stück, z. B. `kimi-k3`) sind standardmäßig ausgeblendet und lassen sich über „Cloud-Modelle anzeigen“ einblenden; sie laufen über Ollamas Cloud (`name:cloud`) und brauchen ein Konto (`ollama signin`).
- **Plattformübergreifend:** Windows, Linux (inkl. Raspberry Pi) und macOS – jeweils mit passender Schriftart, Icon und Ollama-Erkennung.

## Voraussetzungen

| | |
|---|---|
| **Ollama** | Muss separat installiert sein: <https://ollama.com/download> |
| **Python** | 3.9 oder neuer (nur zum Ausführen aus dem Quellcode und zum Bauen) |
| **Tk** | Tk 8.6 (`tkinter`) – bei Windows-Python und python.org-Installern enthalten |
| **Speicherplatz** | Je nach Modell: von wenigen hundert MB bis zu mehreren zehn GB |

Der Installer findet `ollama` auch dann, wenn es nicht im `PATH` liegt (z. B. bei einer per Finder gestarteten macOS-App).

## Schnellstart

Der Installer läuft direkt aus dem Quellcode. Wer lieber ein eigenständiges Programm möchte (`.exe`, `.deb`, `.app`), findet die Anleitung unter [Fertige Programme bauen](#fertige-programme-bauen).

### Aus dem Quellcode starten

```bash
git clone https://github.com/bosancero85/Ollama-Models-Libary-and-Installer-Mac-Linux-Win.git
cd Ollama-Models-Libary-and-Installer-Mac-Linux-Win-main
pip install -r requirements-runtime.txt
python ollama_model_installer.py
```

Unter **Debian / Ubuntu / Kali / Raspberry Pi OS** fehlt `tkinter` oft und muss zuerst installiert werden:

```bash
sudo apt install python3-tk python3-pip
```

Unter **macOS** wird Python mit Tk 8.6 benötigt (python.org-Installer oder `brew install python-tk`); das Python der Command Line Tools bringt nur das veraltete Tk 8.5 mit.

## Bedienung

1. Programm starten. Beim Start wird automatisch `ollama list` geprüft; mit **„Status prüfen“** lässt sich das jederzeit wiederholen.
2. Modell suchen oder nach Kategorie filtern.
3. Pro Modell die gewünschte Größe wählen und ein Häkchen setzen – oder **„Gefilterte auswählen“** nutzen und das Größenlimit einstellen. **„Auswahl leeren“** hebt alles wieder auf.
4. **„Auswahl installieren“** klicken. Ein Dialog zeigt die geschätzte Gesamtgröße und den freien Speicher; nach Bestätigung werden die Modelle nacheinander geladen.
5. Über **„Download Abbrechen“** lässt sich der laufende Download jederzeit stoppen.

> **Hinweis:** „Alle Modelle“ auf einmal zu laden würde viele Terabyte belegen. Installiert wird deshalb nur, was per Häkchen ausgewählt ist. Modelle ohne Größenangabe werden bei „Gefilterte auswählen“ nur mit dem Limit „Unbegrenzt“ berücksichtigt.

Beliebige Tags, die nicht im Katalog stehen, lassen sich weiterhin direkt mit `ollama pull <name>` laden.

## Fertige Programme bauen

| Plattform | Befehl | Ergebnis |
|---|---|---|
| Windows | `build.bat` | `dist\OllamaModelInstaller.exe` (Einzeldatei) |
| Debian / Kali / Raspberry Pi OS | `./build_deb.sh` | `dist/ollama-modell-installer_<Version>_all.deb` |
| macOS | `./build_mac.sh` | `dist/OllamaModelInstaller.app` (optional `.dmg`) |

Alle Skripte legen bei Bedarf eine eigene virtuelle Umgebung an und installieren die Abhängigkeiten selbst. Das Icon wird automatisch berücksichtigt.

### Windows

```cmd
build.bat            :: mit Pause am Ende
build.bat nopause    :: ohne Pause, z. B. für CI
```

### Linux (`.deb`)

Das Paket ist architekturunabhängig (`Architecture: all`) und bringt `customtkinter` bereits mit. **Ein einziges `.deb` läuft auf allen Debian-basierten Systemen** – etwa auf einem Raspberry Pi 4B (arm64/armhf) genauso wie auf einem x86-64-Rechner mit Kali Linux.

```bash
sudo apt install python3 python3-pip python3-pil dpkg-dev   # Bau-Voraussetzungen
./build_deb.sh                       # Version 1.0.0
./build_deb.sh -v 1.2.0              # eigene Version
./build_deb.sh --wheels ./wheels     # ohne Internet, mit vorab geladenen Wheels

sudo apt install ./dist/ollama-modell-installer_1.0.0_all.deb
```

`python3-tk` wird bei der Installation automatisch nachgezogen. Gestartet wird über das Anwendungsmenü („Ollama Modell Installer“) oder mit `ollama-modell-installer`. Entfernen: `sudo apt remove ollama-modell-installer`.

### macOS (`.app`)

Der Build muss auf einem Mac laufen (PyInstaller kann nicht cross-kompilieren).

```bash
./build_mac.sh                # App für die eigene Architektur
./build_mac.sh --dmg          # zusätzlich ein .dmg mit Programme-Link
./build_mac.sh --universal2   # Intel + Apple Silicon (universal2-Python nötig)
./build_mac.sh -v 1.2.0       # Versionsnummer der App
```

Das `.icns`-Icon wird aus `ollama_model_installer_icon.png` erzeugt; liegt eine eigene `ollama_model_installer_icon.icns` im Projektordner, wird diese verwendet. Die App ist **nicht notarisiert**: Auf anderen Macs zuerst per Rechtsklick → „Öffnen“ starten oder die Quarantäne entfernen:

```bash
xattr -dr com.apple.quarantine dist/OllamaModelInstaller.app
```

## Modell-Empfehlungen

Eine kleine Auswahl für lokale Coding-Agenten auf einem System mit **16 GB RAM und 4 GB VRAM**. Modelle bis etwa 3,8B passen komplett in den Grafikspeicher und antworten entsprechend schnell; größere Modelle nutzt Ollama per automatischem CPU/RAM-Offloading. Alle Modelle sind im Katalog enthalten – einfach per Suche finden.

| Einsatz | Modell | Speicherbedarf | Anmerkung |
|---|---|---|---|
| Schnelle Patches, Refactoring | `qwen2.5-coder:3b` | ca. 1,9 GB | passt in 4 GB VRAM, gutes Tool-Calling |
| Mikro-Aufgaben | `qwen2.5-coder:1.5b` | ca. 1,0 GB | Linter-Fixes, Commit-Messages, Regex |
| Code-Vervollständigung | `codegemma:2b` | ca. 1,6 GB | Fill-in-the-Middle, Inline-Patches |
| Planung, Architektur | `deepseek-r1:8b` | ca. 4,9 GB | Chain-of-Thought-Reasoning |
| Planung, Logik (groß) | `phi4:14b` | ca. 9,1 GB | läuft über RAM-Offloading |
| Planung, Logik (kompakt) | `phi3.5:3.8b` | ca. 2,2 GB | komplett im VRAM |
| Review, Dokumentation | `llama3.1:8b` | ca. 4,7 GB | zuverlässige Instruktionsbefolgung |
| Review nach strengen Regeln | `mistral:7b` | ca. 4,1 GB | präzise bei Vorgaben und Linter-Regeln |
| Vision, Screenshots | `moondream` | ca. 1,5 GB | UI- und Fehler-Screenshots |
| Vision, Dokumente | `qwen2-vl:2b` | ca. 1,5 GB | Dokumente und Code-Screenshots |
| Embeddings, RAG | `nomic-embed-text` | ca. 270 MB | semantische Suche im Projektordner |

Alle elf Modelle auf einmal per Kommandozeile:

```bash
for m in qwen2.5-coder:3b qwen2.5-coder:1.5b codegemma:2b deepseek-r1:8b phi4:14b \
         phi3.5:3.8b llama3.1:8b mistral:7b moondream qwen2-vl:2b nomic-embed-text; do
  ollama pull "$m"
done
```

<details>
<summary>PowerShell-Variante</summary>

```powershell
"qwen2.5-coder:3b","qwen2.5-coder:1.5b","codegemma:2b","deepseek-r1:8b","phi4:14b",
"phi3.5:3.8b","llama3.1:8b","mistral:7b","moondream","qwen2-vl:2b","nomic-embed-text" |
  ForEach-Object { ollama pull $_ }
```

</details>

## Häufige Probleme

**„Ollama nicht erreichbar“ / `ollama list` schlägt fehl**
Ollama ist nicht installiert oder nicht gestartet. Installation: <https://ollama.com/download>. Prüfen lässt sich das im Terminal mit `ollama list`.

**`ModuleNotFoundError: No module named 'tkinter'`** (Linux)
`sudo apt install python3-tk`

**macOS: Fenster bleibt leer oder Tk ist zu alt**
Python mit Tk 8.6 verwenden (python.org-Installer oder `brew install python-tk`).

**macOS: „App kann nicht geöffnet werden“**
Die App ist nicht notarisiert – Rechtsklick → „Öffnen“ oder `xattr -dr com.apple.quarantine …` (siehe oben).

**Cloud-Modelle lassen sich nicht laden**
Für Modelle mit `:cloud` ist ein Ollama-Konto nötig: `ollama signin`.

**Der freie Speicher wird für das falsche Laufwerk angezeigt**
Der Modell-Ordner wird in dieser Reihenfolge bestimmt: Umgebungsvariable `OLLAMA_MODELS`, unter Linux `/usr/share/ollama/.ollama/models` (systemd-Dienst), sonst `~/.ollama/models`.

## Projektstruktur

```text
ollama_model_installer.py          Hauptprogramm (GUI, Download-Warteschlange, Fortschritt)
ollama_library.py                  Modellkatalog (238 Familien), Filter, Größenschätzung
platform_support.py                Windows/Linux/macOS-Anpassungen (Ollama-Suche, Schrift, Icon)
make_icons.py                      Icon-Erzeugung (PNG-Größen, .icns, .ico) für die Build-Skripte
test_ollama_library.py             Unit-Tests (ohne echte GUI)
build.bat                          Windows-Build (.exe)
build_deb.sh                       Linux-Build (.deb, Raspberry Pi / Kali / Debian)
build_mac.sh                       macOS-Build (.app / .dmg)
requirements.txt                   Laufzeit + Build-Abhängigkeiten
requirements-runtime.txt           nur Laufzeit-Abhängigkeiten
ollama_model_installer_icon.*      Icons (.png, .ico, 256-px-PNG für das Fenster)
playbook/                          Projektnotizen und Arbeitsablauf
```

## Entwicklung und Tests

```bash
pip install -r requirements.txt
python -m unittest -v
```

Die Tests prüfen den Katalog, die Filter- und Auswahllogik, die Fortschrittsauswertung von `ollama pull` und die Plattformerkennung – die GUI wird dafür durch Stubs ersetzt, ein Display ist nicht nötig.

Der Katalog ist ein fest eingebauter Schnappschuss (`ollama_library.py`, Stand 2026-09-28). Mit neuen Ollama-Versionen wird er zusammen mit der Kompatibilität aktualisiert.

## Lizenz

[MIT](LICENCE) © 2026 Aki_SystemDown
