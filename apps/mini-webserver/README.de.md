# Mini Webserver

Ein kleines Windows-Tool mit Oberfläche (CustomTkinter), das einen Ordner per HTTP oder HTTPS im Netzwerk ausliefert. Es ersetzt den Befehl `python -m http.server 8080`: Start/Stopp per Knopf, Log der Zugriffe, Adresse fürs Handy, Tray-Symbol.

## Funktionen

- Start/Stopp-Knopf mit Ladebalken und Statusanzeige
- **HTTPS** per Häkchen (Standard: an). Nötig, weil Browser das Mikrofon (Diktieren) nur auf sicheren Adressen freigeben. Das Tool erzeugt selbst eine kleine Zertifizierungsstelle (CA) und ein Zertifikat für den Rechnernamen und die aktuelle IP. Ändert sich die IP, wird das Zertifikat automatisch neu ausgestellt
- **Ollama-Weiterleitung**: Alles unter `/api` geht an die eingetragene Ollama-Adresse (Standard `http://127.0.0.1:11434`). Eine HTTPS-Seite darf sonst kein `http://`-Ollama aufrufen (Mixed Content). Die Antworten kommen Stück für Stück an, das Streaming bleibt erhalten. Leer lassen schaltet die Weiterleitung aus
- Ordnerauswahl per Dialog, Port einstellbar (Standard 8080)
- Log mit Zeitstempel und allen Zugriffen
- Zeigt die Adresse fürs Handy, mit Kopieren-Knopf und "Im Browser öffnen"
- Schließen legt das Fenster in den Tray. Rechtsklick auf das Symbol: Fenster öffnen, Server starten/stoppen, Beenden
- Der Server ist eingebaut. Die fertige .exe braucht kein installiertes Python
- Liegt die .exe im Ordner eines HTML-Projekts, wird genau dieser Ordner ausgeliefert. Sonst merkt sich das Tool den zuletzt benutzten Ordner

## Benutzung

1. `MiniWebserver.exe` in den Ordner mit deinem HTML-Projekt kopieren und starten (oder den Ordner im Tool wählen).
2. "Server starten" klicken. Fragt die Windows-Firewall, "Zulassen" für das private Netzwerk wählen.
3. Am Handy (gleiches WLAN) die angezeigte Adresse öffnen, zum Beispiel `https://192.168.178.40:8080/`.
4. Beim ersten Mal warnt der Browser vor dem Zertifikat: „Erweitert“, dann „Weiter“. Ohne Warnung: `https://<IP>:<Port>/mini-webserver-ca.crt` öffnen und das Zertifikat auf dem Handy als CA installieren. Das ist nur einmal nötig, auch nach IP-Wechseln.
5. Läuft Ollama auf einem anderen Rechner, trage dessen Adresse im Feld „Ollama-Adresse“ ein.

Gibt es keine `index.html`, zeigt die Adresse direkt auf die erste gefundene HTML-Datei.

## Die .exe bauen

**Auf Windows:** Python 3.9 oder neuer installieren, dann `build.bat` doppelklicken. Ergebnis: `dist\MiniWebserver.exe`.

**Über GitHub:** Das Repo pushen. Der Workflow `.github/workflows/build.yml` führt die Tests aus und baut die .exe. Du findest sie unter Actions im Artefakt `MiniWebserver-exe`.

## Aus dem Quellcode starten

```bash
pip install -r requirements.txt
python main.py
```

## Tests

```bash
python -m unittest discover -s tests
```

Die Kernlogik (Server, HTTPS mit echtem TLS, Ollama-Weiterleitung mit Streaming, Zertifikate, Ordner, Einstellungen) wird echt getestet. Die Oberfläche wird mit Stellvertreter-Modulen auf ihren Ablauf geprüft, das Aussehen nicht.

## Hinweise zur Sicherheit

- Die Dateien `mini-webserver-ca.key` und `server.key` liegen unter `%APPDATA%\MiniWebserver\cert` und gehören nur auf diesen Rechner. Wer den CA-Schlüssel hat, könnte Zertifikate für Geräte ausstellen, die dieser CA vertrauen. Gib ihn nie weiter.
- Die Ollama-Weiterleitung ist für jedes Gerät im Netzwerk offen, genau wie der Server selbst. Ollama hat keine Anmeldung.
- Der Server ist für alle Geräte im selben Netzwerk erreichbar. Gib nur Ordner frei, die andere sehen dürfen, und nutze das Tool nicht in fremden WLANs.
- Ohne `index.html` zeigt der Server eine Dateiliste des Ordners.
- Windows SmartScreen oder Virenscanner können bei selbst gebauten .exe-Dateien warnen, weil sie nicht signiert sind.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
