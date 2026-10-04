# Ablage

Wo liegt was in diesem Projekt.

| Pfad | Inhalt |
|---|---|
| `ollama.html` | Markup der App |
| `style.css` | Gesamtes CSS |
| `script.js` | Gesamte Logik (JS) |
| `manifest.json`, `sw.js`, `icons/` | Optionale PWA-Dateien (Installation auf dem Homescreen, Offline-Start der App-Hülle) |
| `tests/run.js` | Automatische Tests (Markdown, Stream-Parser, Export/Import, Tastatur, Modellwahl, PWA-Dateien, Mock-Ollama-Server) |
| `playbook/` | Projektsteuerung (diese Dateien) |
| `README.de.md` | Anleitung auf Deutsch |
| `LICENSE` | MIT-Lizenz |
| `.gitignore` | Ausgeschlossene Dateien |

Regel: `ollama.html`, `style.css` und `script.js` gehören zusammen in einen Ordner und haben keine externen Abhängigkeiten (kein CDN, keine Fonts, keine Bibliotheken). Die PWA-Dateien sind ein optionaler Zusatz: fehlen sie oder wird `ollama.html` per `file://` geöffnet, funktioniert die App unverändert.
