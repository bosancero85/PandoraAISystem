# Fertige Definition (Definition of Done)

Das Projekt ist fertig, wenn alle Punkte erfüllt sind:

- [X] `index.html` läuft als einzelne Datei ohne Internetzugriff
- [X] Verbindung zu Ollama über frei einstellbare Server-URL
- [X] Modelle werden automatisch aus `/api/tags` geladen
- [X] Antworten erscheinen als Stream, Abbrechen ist möglich
- [X] Mehrere Chats, gespeichert im Browser (localStorage)
- [X] Bedienbar auf dem Handy (Touch, Safe-Area, 16px-Eingabe)
- [X] Verständliche Fehlermeldungen bei Verbindungsproblemen
- [X] Tests laufen fehlerfrei (`node tests/run.js`)
- [X] LICENSE, README.de.md und .gitignore vorhanden

## Erweiterungen Version 1.1

- [X] Chats als Markdown und JSON exportieren, JSON importieren
- [X] Bild-Eingabe für Vision-Modelle (Base64, auf 1280 px verkleinert, höchstens 4 Bilder)
- [X] Ollama-Parameter `num_ctx`, `repeat_penalty`, `top_p` einstellbar
- [X] Chat-Suche in der Seitenleiste und Chat-Titel umbenennen
- [X] `<think>`-Tags im Textstrom werden in den Gedankengang verschoben
- [X] Markdown-Tabellen, Durchgestrichenes und Syntaxhervorhebung ohne externe Bibliothek
- [X] PWA: `manifest.json`, `sw.js`, Icons
- [X] Streaming hängt nur Text an, Markdown erst nach dem Ende
- [X] Anpassung an die Bildschirmtastatur über `visualViewport`
- [X] Tests laufen fehlerfrei (43 Node-Tests, Browser-Tests in der Sandbox)
- [ ] Auf einem echten Handy geprüft: iOS-Tastatur, Bild-Upload mit `llava` oder `llama3.2-vision`, `<think>` mit DeepSeek-R1, Diktieren, PWA-Installation
- [ ] Repo bei GitHub angelegt und gepusht

## Erweiterungen Version 1.2

- [X] Projekt aufgetrennt in `ollama.html`, `style.css`, `script.js`
- [X] Branding: Kopfzeile "Pandora® Code", Fußzeile "Pandora® | by AKI_SystemDown ©2026"
- [X] Datei-Anhang statt reinem Bild-Upload: Bilder wie bisher, dazu Text-/Code-Dateien (per NUL-Byte-Prüfung von Binärdateien unterschieden), Dateiinhalt wird als Codeblock in die Nachricht eingefügt
- [X] Automatische Modellwahl: bei Bild-Anhang wird auf ein installiertes bild-fähiges Modell gewechselt (Namens- und `families`-Erkennung), bei Code-Datei auf ein installiertes Coder-Modell; nur wenn ein passendes Modell vorhanden ist
- [X] Diktierfunktion (Web Speech API) vollständig entfernt
- [X] Tests laufen fehlerfrei (46 Node-Tests, 18 Browser-Prüfpunkte inkl. Modellwahl und Datei-Versand)
- [ ] Auf einem echten Handy geprüft (siehe Hinweise unten)
- [ ] Repo bei GitHub angelegt und gepusht

## Erweiterungen Version 1.3

- [X] Design: Neonglow-Glassmorphism mit Hover- und Electric-Border-Effekt (reines CSS, keine Abhängigkeiten)
- [X] Projekte: anlegen, bearbeiten, löschen, aktivieren; Chatfilter; Projektanweisungen im Systemprompt
- [X] Artefakte: Codeblock sichern, auflisten, kopieren, herunterladen, löschen, HTML-Vorschau in Sandbox
- [X] Tests laufen fehlerfrei (51 Node-Tests, 12 Browser-Prüfpunkte)
- [ ] Auf einem echten Handy geprüft (Glas-Blur und Electric Border auf iOS Safari und Android Chrome)

## Erweiterungen Version 1.4

- [X] Diktierfunktion (Web Speech API) mit Mikrofon-Knopf, Live-Zwischenergebnis, einstellbarer Sprache
- [X] Plattformlogik: Dauermodus am Desktop, Einzelphrasen mit Neustart auf Touch-Geräten, Schutz vor Neustart-Schleifen
- [X] Verständliche Hinweise bei fehlender API (Firefox), unsicherer Adresse (http), verweigertem Mikrofon, fehlendem Internet
- [X] Tests laufen fehlerfrei (55 Node-Tests, 20 Browser-Prüfpunkte mit simulierter Spracherkennung)
- [ ] Auf echten Geräten geprüft: Windows/Chrome, Mac/Safari, Linux/Chromium, Android/Chrome, iPhone/Safari (echte Erkennung konnte in der Sandbox nicht getestet werden)
