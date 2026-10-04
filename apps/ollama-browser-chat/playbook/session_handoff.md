# Session-Übergabe

Stand: 2026-10-01

## Nachtrag: Diktieren über HTTPS (Webserver 1.1.0)

- [X] Ursache: Spracherkennung braucht einen sicheren Kontext, `http://<IP>:8080` ist keiner
- [X] Lösung: Mini Webserver liefert per HTTPS aus und leitet `/api` an Ollama weiter. Der Chat nutzt über https automatisch seine eigene Adresse als Ollama-Adresse
- [X] Fehlertexte und Einstellungs-Hinweis angepasst, README ergänzt, 55 Node-Tests grün
- [X] Dropdown unter Windows weiß auf weiß: Ursache war die transparente `--surface`-Variable für `option`; jetzt deckende Farben für alle `select option`
- [X] Token-Anzeige (7 Segmente, SVG): IN, OUT, Σ pro Chat, live beim Streamen, exakte Zahlen aus der letzten Ollama-Zeile, gespeichert in `chat.tok`. 61 Node-Tests und Browser-Test mit Fake-Ollama (320 bis 390 px, eine Zeile, Neuladen)
- [X] Token-Anzeige nach oben verschoben (zwischen Titelleiste und Modellauswahl), Test sichert die Position
- [X] Fehlermeldung „zweite Nachricht liefert die erste Antwort“: App-Logik geprüft (identisch zu v1.4, 3 Runden und lange Code-Antworten über HTTPS-Proxy korrekt). Vermutete Ursache: Kontextfenster von Ollama voll (qwen2.5-coder:14b, num_ctx auf Standard). Dafür Kontextwarnung gebaut (IN gelb/rot, Hinweis), 62 Node-Tests grün
- [ ] Rückmeldung abwarten: Zeigt IN nach der zweiten Nachricht rot? Hilft num_ctx 8192?
- [ ] Echter Test am Handy steht aus (Zertifikat bestätigen, Diktieren, Chat-Streaming)

## Checkliste (Version 1.2: Dateiaufteilung, Branding, allgemeiner Datei-Import, Diktat entfernt)

1. [X] Projekt entpackt und Ist-Analyse
2. [X] Bestehenden Bild-Import und Diktierfunktion lokalisiert
3. [X] Modell-Metadaten-Quelle geklärt (`/api/tags` liefert `details.families`, nutzbar für Bild-Erkennung)
4. [X] Aufgetrennt in `ollama.html`, `script.js`, `style.css`
5. [X] Header „Pandora® Code“ und Footer „Pandora® | by AKI_SystemDown ©2026“ eingebaut
6. [X] Bild-Import zu allgemeinem Datei-Import erweitert, automatische Modellwahl (Vision/Coder) ergänzt
7. [X] Diktierfunktion (Web Speech API) vollständig entfernt, inkl. aller Tests und CSS-Regeln
8. [X] Qualitätskontrolle (Syntax aller Dateien, verwaiste ID-Referenzen zwischen HTML und JS geprüft)
9. [X] Tests: 46 Node-Tests grün (`node tests/run.js`), 18 Browser-Prüfpunkte mit Playwright grün (Branding, Datei-Anhang, Modellwechsel bei Code-Datei und bei Bild, Versand-Payload, keine JS-Fehler)
10. [X] Formatierung geprüft (UTF-8, LF, keine Tabs)
11. [ ] Abschluss: auf einem echten Handy geprüft, Repo bei GitHub angelegt und gepusht

## Nächster Schritt

Wie schon in der vorherigen Übergabe: (1) Test auf einem echten Handy, jetzt zusätzlich mit einer echten Code-Datei und einem echten Bild, um die automatische Modellwahl mit echten Ollama-Modellen zu prüfen (2) `git remote add origin <URL>` und `git push -u origin main`.

## Was sich geändert hat

- **Dateiaufteilung**: `index.html` gibt es nicht mehr. Die App ist jetzt `ollama.html` + `style.css` + `script.js`, alle drei müssen im selben Ordner liegen. Das bricht bewusst mit der bisherigen Ein-Datei-Regel aus `interview.md`/`ablage.md` (auf expliziten Wunsch); `playbook.md` und `ablage.md` sind entsprechend angepasst.
- **PWA-Start**: `manifest.json` hat jetzt `start_url`/`entry` explizit auf `ollama.html` gesetzt (vorher reichte `./`, weil `index.html` der Standard-Dateiname ist). `sw.js` cacht `ollama.html`, `style.css`, `script.js` statt `index.html`, Cache-Name auf `pandora-code-v2` angehoben, Offline-Navigations-Rückfall zeigt jetzt gezielt auf `ollama.html` statt auf `./`.
- **Datei-Anhang**: `#imgFile` (nur Bilder) ersetzt durch `#attachFile` (Bilder plus Text-/Code-Dateien). Ob eine Datei Text ist, wird anhand der ersten 8 KB auf ein NUL-Byte geprüft (Binärdateien wie PDF/ZIP/EXE werden abgelehnt), nicht nur an der Dateiendung. Dateiinhalt wird beim Senden als Markdown-Codeblock in `content` eingefügt (Ollama kennt keine generischen Datei-Anhänge, nur `images`). Bilder laufen unverändert über das `images`-Feld.
- **Automatische Modellwahl**: `isVisionCapable()` kombiniert `details.families` aus `/api/tags` (z. B. `clip`, `mllama`) mit einer Namens-Heuristik (`llava`, `vision`, `-vl`, …) als Rückfall. `isCoderModelName()` ist reine Namens-Heuristik (`coder`, `codellama`, `starcoder`, …), da Ollama dafür kein Metadatenfeld liefert. Wechsel passiert nur, wenn ein passendes installiertes Modell existiert und das aktuelle Modell die Anforderung nicht schon erfüllt; per Toast sichtbar gemacht.
- **Diktat**: komplett entfernt (Mikrofon-Knopf, `SpeechRecognition`, `mergeDictation`, `dictationError`, zugehörige CSS-Regeln und Tests).

## Hinweise (weiterhin gültig, siehe auch vorherige Übergabe für Details zu Tastatur/Streaming)

- Ollama braucht `OLLAMA_HOST=0.0.0.0` und `OLLAMA_ORIGINS=*`, sonst blockiert der Browser die Anfragen
- Regel im Playbook: keine externen Abhängigkeiten, auch nicht per CDN
- Browser-Test Modellwahl: `<option>`-Elemente in einem nativen `<select>` gelten in Playwright/Chromium headless nicht als "visible" – beim Warten `state='attached'` verwenden, nicht die Standard-Sichtbarkeitsprüfung
- Binär-Erkennung für Datei-Anhänge prüft nur ein NUL-Byte in den ersten 8 KB; das erkennt die allermeisten Binärformate, aber keine Garantie für jede Datei

## Version 1.3 (2026-10-01)

- Neonglow-Glassmorphism als Block am Ende von `style.css` (überschreibt die Variablen aus `:root`, helles Theme ist damit faktisch abgelöst). Electric Border via `@property --eb` + `conic-gradient` + Mask auf `::before`; Hover nur unter `@media (hover:hover)`
- Projekte (`state.projects`, `state.project`, `chat.projectId`) und Artefakte (`state.artifacts`) im Tab-Layout der Seitenleiste; reine Funktionen `buildSystem`, `artifactExt`, `artifactTitle`
- Bekannt/offen: JSON-Export/-Import enthält noch keine Projekte/Artefakte und keine `projectId`; Service-Worker-Cache jetzt `pandora-code-v3`
- Nächster Schritt: Test auf echtem Handy (Performance von `backdrop-filter` und Animation bei langen Chats)

## Version 1.4 (2026-10-01)

- Diktat neu gebaut (in 1.2 war es entfernt): `btnMic`, `toggleMic`/`beginRec`/`stopRec` in `script.js`, reine Funktionen `mergeDictation`, `dictationSupport`, `dictationErrorText`, `dictationLang`. Einstellung `state.dictLang`
- Der alte Test "Keine Diktierfunktion mehr im Projekt" wurde durch einen Test ersetzt, der externe Skripte und eigene Audio-/Cloud-Anbindung verbietet (Playbook-Regel: keine externen Abhängigkeiten)
- Browser-Test-Hinweis: Chromium hat `SpeechRecognition` bereits unpräfixiert; zum Simulieren beide Namen per `Object.defineProperty` überschreiben, sonst nutzt die App die echte API
- Grenze: Das Audio geht an den Browser-Anbieter (Internet nötig); über `http://<IP>` im WLAN ist das Mikrofon gesperrt (Secure Context)
- Nächster Schritt: Test auf echten Geräten (Win, Mac, Linux, Android, iPhone), vor allem Android-Verhalten bei längeren Diktaten
