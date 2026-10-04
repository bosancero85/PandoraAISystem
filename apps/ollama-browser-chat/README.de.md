# Pandora Code

Drei Dateien (`ollama.html`, `style.css`, `script.js`), mit denen du dein lokales [Ollama](https://ollama.com) bequem vom Handy aus nutzt. Keine Installation, keine externen Bibliotheken. Für den Chat selbst brauchst du kein Internet, nur das WLAN zu deinem Rechner.

## Funktionen

**Chat**

- Streaming-Antworten mit Stopp-Knopf, schonend für das Handy (während des Streams wird nur Text angehängt, die Formatierung folgt am Ende)
- Modellauswahl, automatisch aus Ollama geladen
- Mehrere Chats, lokal im Browser gespeichert, mit Suche (Titel und Inhalt) und Umbenennen
- Chats als Markdown (einzelner Chat) oder JSON (alle) exportieren, JSON-Verläufe wieder importieren
- Dateien anhängen: Bilder für Vision-Modelle (zum Beispiel `llava` oder `llama3.2-vision`), dazu Text- und Code-Dateien (Inhalt wird als Codeblock in die Nachricht eingefügt)
- Modell wird passend zum Anhang automatisch gewechselt, sofern ein geeignetes installiert ist: bei einem Bild auf ein bild-fähiges Modell, bei einer Code-Datei auf ein Coder-Modell
- Gedankengang von Modellen wie DeepSeek-R1 wird automatisch in einen aufklappbaren Bereich verschoben

- Diktieren per Mikrofon-Knopf: Text erscheint live im Eingabefeld (siehe "Hinweise zum Diktieren")

**Projekte und Artefakte**

- Projekte bündeln Chats und Artefakte. Ein aktives Projekt filtert die Chatliste, neue Chats gehören automatisch dazu, und seine Anweisungen werden dem Systemprompt hinzugefügt
- Artefakte: Am Codeblock auf "Artefakt" tippen, dann liegt er im Tab "Artefakte" der Seitenleiste. Von dort kopieren, herunterladen, löschen; HTML-Artefakte haben eine Vorschau in einer abgeschotteten Sandbox

**Darstellung**

- Markdown mit Überschriften, Listen, Zitaten, Tabellen, ~~Durchgestrichenem~~ und Codeblöcken mit Syntaxhervorhebung und Kopieren-Knopf
- Neonglow-Glassmorphism (dunkel) mit Hover-Effekten (nur bei Maus/Trackpad) und rotierendem Electric-Border-Effekt; für Touch-Bedienung gebaut
- Die App passt sich an die Bildschirmtastatur an: Die Eingabezeile bleibt sichtbar, auch auf dem iPhone
- Installierbar als App auf dem Startbildschirm (PWA, siehe unten)

**Einstellungen**

- Systemprompt, Temperatur, `top_p`, Wiederholungsstrafe (`repeat_penalty`) und Kontextfenster (`num_ctx`)

## Einrichtung

**1. Ollama für das Netzwerk freigeben** (auf dem Rechner, auf dem Ollama läuft):

```bash
OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS=* ollama serve
```

Läuft Ollama als Systemdienst, setze die beiden Variablen in der Dienstkonfiguration (`sudo systemctl edit ollama`) und starte den Dienst neu.

**2. Die Seite aufs Handy bringen** (Handy und Rechner im selben WLAN). Am einfachsten:

```bash
python3 -m http.server 8080
```

Dann auf dem Handy `http://<IP-des-Rechners>:8080/ollama.html` öffnen. Mit dem **Mini Webserver** (mit HTTPS, siehe unten) öffnest du stattdessen `https://<IP-des-Rechners>:8080/ollama.html`, damit das Diktieren funktioniert. Alternativ kannst du `ollama.html`, `style.css` und `script.js` zusammen (alle drei, im selben Ordner) per Datei-Übertragung aufs Handy kopieren und `ollama.html` dort im Browser öffnen.

**3. Adresse eintragen.** In den Einstellungen die Ollama-Adresse setzen, zum Beispiel `http://192.168.0.10:11434`, dann "Speichern und verbinden".

## Als App installieren (PWA)

Zusätzlich zu `ollama.html`, `style.css` und `script.js` liegen `manifest.json`, `sw.js` und der Ordner `icons/` im Projekt. Sie sind optional: Fehlen sie oder öffnest du `ollama.html` direkt vom Dateisystem, funktioniert die App genauso.

- Über `http://<IP>:8080/ollama.html` (unverschlüsselt im WLAN) kannst du auf dem iPhone "Zum Home-Bildschirm" wählen. Die App startet dann ohne Browserleiste.
- Der Offline-Start der App-Hülle (Service Worker) und die Installationsabfrage in Chrome brauchen einen sicheren Kontext, also `https://` oder `http://localhost`. Über `http://192.168.x.x` gibt es keinen Offline-Cache.
- Wird die Seite per `https://` geladen, blockiert der Browser Aufrufe an ein `http://`-Ollama (Mixed Content). Der Mini Webserver löst das: Er leitet `/api` an Ollama weiter, die App spricht dann nur mit ihrer eigenen `https://`-Adresse (so ist es vorausgefüllt).
- Der Service Worker fasst nur Dateien der App selbst an. Anfragen an Ollama laufen nie über ihn.

## Hinweise zu Datei-Anhängen

- **Bilder** funktionieren nur mit Modellen, die Bilder verstehen. Die App verkleinert sie auf höchstens 1280 Pixel Kantenlänge und sendet sie als JPEG, bis zu vier Anhänge pro Nachricht. Bilder liegen nur im Arbeitsspeicher: Nach einem Neuladen zeigt der Chat einen Platzhalter, und der Export enthält keine Bilddaten.
- **Text- und Code-Dateien** (zum Beispiel `.py`, `.js`, `.md`, `.json`, `.csv`, `.log`, `.yaml`, ...) werden gelesen und als Codeblock in deine Nachricht eingefügt, der Inhalt zählt also zum Kontextfenster (`num_ctx`) dazu. Sehr lange Dateien werden bei rund 60.000 Zeichen gekürzt, du bekommst dazu eine kurze Meldung. Binärdateien (zum Beispiel PDF, ZIP, EXE) werden erkannt und abgelehnt, da ihr Inhalt sich nicht sinnvoll als Text einfügen lässt.
- **Automatische Modellwahl**: Hängst du ein Bild an und dein aktuelles Modell kann keine Bilder verarbeiten, wechselt die App zu einem installierten bild-fähigen Modell (erkannt an Namen wie `llava`, `vision`, `-vl` oder an den Modell-Metadaten). Hängst du eine Code-Datei an, wird entsprechend zu einem installierten Coder-Modell gewechselt (erkannt am Namen, zum Beispiel `coder`, `codellama`, `starcoder`). Ist kein passendes Modell installiert, bleibt die Auswahl unverändert; bei fehlendem Bild-Modell bekommst du dazu einen Hinweis.

## Token-Anzeige

Ganz oben, zwischen dem Titel und der Modellauswahl, zeigt eine digitale 7-Segment-Anzeige den Token-Verbrauch des aktuellen Chats:

- **IN** (cyan): Tokens der letzten Anfrage, also Verlauf, System-Prompt und Dateien, die an das Modell gingen.
- **OUT** (magenta): Tokens der letzten Antwort. Beim Streamen zählt die Anzeige live mit, am Ende springt sie auf die exakte Zahl von Ollama.
- **Σ** (grün): Summe aus IN und OUT über alle Anfragen dieses Chats. Sie wird im Chat gespeichert und bleibt nach einem Neuladen erhalten.

Hinweise:

- Die exakten Zahlen liefert Ollama in der letzten Zeile der Antwort (`prompt_eval_count`, `eval_count`). Bricht du eine Antwort ab, gibt es keine exakte Zahl, dann zählt die Summe die bis dahin gestreamten Stücke (etwa ein Token pro Stück).
- Ollama nutzt für gleiche Anfang-Teile des Gesprächs einen Zwischenspeicher. Dann kann IN kleiner sein als der ganze Verlauf.
- **Kontextwarnung:** Ist das Kontextfenster zu 85 % gefüllt, färbt sich IN gelb, ist es voll, rot und pulsiert. Dazu erscheint ein Hinweis. Die Fenstergröße nimmt die App aus der Einstellung „Kontextfenster (num_ctx)“, sonst fragt sie Ollama über `/api/ps` (neuere Ollama-Versionen). Kennt sie die Größe nicht, bleibt die Warnung aus. Tippe auf IN, um den genauen Stand zu sehen (Tooltip am PC).
- Ist das Fenster voll, schneidet Ollama den ältesten Teil des Verlaufs ab. Das Modell verliert dann den Bezug zu früheren Antworten und wiederholt zum Beispiel Altes oder antwortet an der Frage vorbei. Abhilfe: num_ctx erhöhen (8192 ist bei 8 GB Grafikspeicher ein guter Wert) oder einen neuen Chat beginnen.
- IN und OUT zeigen bis 999 999, die Summe bis 9 999 999.
- Exportierte Chats und importierte Chats enthalten den Verbrauch nicht, die Anzeige startet dort bei null.

## Tipps

- Wird die Seite per `http://` vom Rechner geladen, ist die Adresse schon vorausgefüllt.
- Öffnest du die Seite über `https://`, trage in den Einstellungen die Adresse der Seite selbst ein (`https://<IP>:<Port>`, ist vorausgefüllt). Eine direkte `http://`-Ollama-Adresse blockiert der Browser dann.
- Ollama hat keine Anmeldung. Setze die Freigabe nur in einem vertrauenswürdigen Netzwerk und öffne Port 11434 nicht ins Internet.
- Chats und Einstellungen liegen nur im Browser deines Handys (localStorage).

## Tests

```bash
node tests/run.js
```

Prüft Markdown-Darstellung (inklusive XSS-Schutz, Tabellen und Syntaxhervorhebung), den Stream-Parser, Export und Import, Denk-Tags, Suche, Ollama-Parameter, die automatische Modellwahl bei Datei-Anhängen, die Tastatur-Berechnung, die PWA-Dateien und einen Mock-Ollama-Server. Benötigt nur Node.js ab Version 18.

## Lizenz

MIT, siehe [LICENSE](LICENSE).

## Hinweise zum Diktieren

Das Diktat nutzt die Spracherkennung des Browsers (Web Speech API), ohne zusätzliche Bibliothek. Die Sprache stellst du in den Einstellungen ein, Standard ist die Browsersprache.

| System | Browser | Diktat |
|---|---|---|
| Windows, macOS, Linux | Chrome, Edge, Chromium, Brave | funktioniert (Brave nur teilweise, je nach Version) |
| macOS, iPhone, iPad | Safari | funktioniert, auf iOS muss die Diktierfunktion in den Einstellungen aktiv sein |
| Android | Chrome | funktioniert |
| alle | Firefox | nicht verfügbar, die App zeigt einen Hinweis |

Wichtig:

- **Sichere Adresse nötig.** Mikrofon und Spracherkennung funktionieren nur über `https://` oder `localhost`. Wenn du die App über `http://192.168.x.x:8080` im WLAN öffnest, sperrt der Browser das Mikrofon. Lösung: Im Mini Webserver (Version 1.1) „HTTPS verwenden“ einschalten und die Seite über `https://<IP>:<Port>/ollama.html` öffnen. Beim ersten Mal warnt der Browser vor dem selbst ausgestellten Zertifikat: „Erweitert“, dann „Weiter“. Ohne Warnung geht es, wenn du `https://<IP>:<Port>/mini-webserver-ca.crt` auf dem Handy öffnest und das Zertifikat als vertrauenswürdige CA installierst (Android: Einstellungen, Sicherheit, Zertifikat installieren, CA-Zertifikat. iPhone: Profil laden, installieren, danach unter Einstellungen, Allgemein, Info, Zertifikatsvertrauenseinstellungen aktivieren). Alternativ geht auch Tailscale Serve oder die App direkt auf dem Gerät über `http://localhost`.
- **Internet nötig.** Die Erkennung läuft beim Browser-Anbieter (Google, Apple oder Microsoft), das Audio verlässt also dein Gerät. Das gilt nur für das Diktat, der Chat mit Ollama bleibt im lokalen Netz.
- **Mobil** arbeitet die App mit Einzelphrasen und startet automatisch neu, das verhindert Doppeltext auf Android. Bei längerer Stille stoppt das Diktat von selbst.
- Beim Senden, beim Wechsel in eine andere App oder beim erneuten Tippen auf das Mikrofon endet die Aufnahme.
