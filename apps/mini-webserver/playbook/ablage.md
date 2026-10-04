# Ablage

| Pfad | Inhalt |
|---|---|
| `main.py` | Einstiegspunkt |
| `mini_webserver/core/server.py` | Webserver-Steuerung (Start/Stop, Log-Callback) |
| `mini_webserver/core/certs.py` | CA und Server-Zertifikat für HTTPS |
| `mini_webserver/utils/net.py` | Ermittlung der lokalen IP-Adresse |
| `mini_webserver/utils/settings.py` | Speichern von Ordner und Port |
| `mini_webserver/ui/app.py` | Hauptfenster (CustomTkinter) |
| `mini_webserver/ui/tray.py` | Tray-Symbol und Menü |
| `tests/test_core.py` | Automatische Tests |
| `build.bat` | Baut die .exe lokal mit PyInstaller |
| `.github/workflows/build.yml` | Baut die .exe automatisch auf GitHub |
| `playbook/` | Projektsteuerung |
