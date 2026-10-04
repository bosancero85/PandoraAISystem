# Fertige Definition (Definition of Done)

Das Projekt ist fertig, wenn alle Punkte erfüllt sind:

- [X] `README.md` (Englisch) und `README.de.md` (Deutsch) mit Screenshots
- [X] Landingpage `index.html` als einzelne Datei, läuft ohne Internet
- [X] Live-Simulator in der Landingpage: echte Chat-App mit simuliertem Ollama
- [X] Beispiel-Knöpfe, Handy- und Desktop-Ansicht, Token-Anzeige und Kontextwarnung im Simulator
- [X] Download-Bereich mit Betriebssystem-Erkennung für Windows, macOS und Linux
- [X] Build-Skript `scripts/build_release.py` für Installer, Webserver, Pandora Code und Web-Paket
- [X] `release.yml` baut für Windows, macOS und Linux und veröffentlicht bei einem Tag `v*`
- [X] `ci.yml` führt alle Tests aus, `pages.yml` veröffentlicht die Landingpage
- [X] Dateinamen in Build, Landingpage, README und Workflow stimmen überein (automatisch geprüft)
- [X] Keine persönlichen Daten in Bildern und Dateien
- [X] LICENSE, README.de und .gitignore vorhanden
- [X] Alle Tests grün (Chat, Webserver, Installer, Pandora Code, Skripte, Browser-Test)

Noch nicht möglich ohne die jeweiligen Systeme:

- [ ] Erster echter Lauf von `release.yml` auf GitHub (Windows-, macOS-, Linux-Runner)
- [ ] Test der gebauten Programme auf echten Geräten
