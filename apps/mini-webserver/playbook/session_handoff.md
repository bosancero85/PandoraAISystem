# Session-Übergabe

Stand: 2026-10-01

## Version 1.1.0: HTTPS und Ollama-Weiterleitung (Diktieren am Handy)

Anlass: Das Diktieren im Chat meldete einen Fehler, weil `http://<IP>` kein sicherer Kontext ist.

1. [X] `core/certs.py`: eigene CA plus Server-Zertifikat (Namen und IP), automatische Erneuerung bei IP-Wechsel
2. [X] `core/server.py`: HTTPS (TLS-Handshake im Verbindungs-Thread), CA-Download unter `/mini-webserver-ca.crt`
3. [X] Weiterleitung `/api` an Ollama mit Streaming (ohne Origin/Referer, sonst Ollama-403)
4. [X] Oberfläche: HTTPS-Häkchen, Ollama-Adresse, https-Adressen, Zertifikatshinweis
5. [X] Tests: 33 grün (echtes TLS, Proxy-Streaming, Zertifikatserneuerung, Oberfläche)
6. [X] Doku: README, Version 1.1.0
7. [ ] `MiniWebserver.exe` neu bauen (die mitgelieferte .exe ist noch Version 1.0.0 ohne HTTPS)
8. [ ] Echter Test am Handy (Android Chrome, iPhone Safari): Warnung bestätigen, Diktieren, Chat

## Erledigt (Version 1.0.0)

- Kernlogik: Server im Programm (wie `http.server`), Ordner/Port-Prüfung, verständliche Fehler
- Oberfläche: Ordnerwahl, Start/Stopp, Ladebalken, Log, Adresse fürs Handy
- Tray: Schließen legt in den Tray, Menü mit Öffnen/Start-Stopp/Beenden
- Build: `build.bat` und GitHub-Workflow
- 21 Tests grün (Kernlogik echt, Oberfläche mit Stellvertreter-Modulen)
- LICENSE, README.de.md, .gitignore, Playbook, lokaler Git-Commit

## Offen

- Erster echter Lauf auf Windows: `python main.py` (Aussehen und Tray prüfen)
- .exe bauen (`build.bat` oder GitHub Actions) und einmal starten
- Repo bei GitHub anlegen und pushen

## Hinweise

- In der Entwicklungsumgebung gab es kein tkinter und kein Netz, daher wurde die echte Oberfläche nicht gezeigt
- Zugehöriges Projekt: Ollama Mobile Chat (wird mit diesem Tool ausgeliefert)
