# Ablage

Wo liegt was in diesem Projekt.

| Pfad | Inhalt |
|---|---|
| `index.html` | Landingpage als einzelne Datei (gebaut, nicht von Hand ändern) |
| `README.md`, `README.de.md` | Anleitung auf Englisch und Deutsch, mit Screenshots |
| `apps/ollama-browser-chat/` | Chat-Oberfläche (HTML, CSS, JS, PWA-Dateien, Node-Tests) |
| `apps/mini-webserver/` | HTTPS-Webserver mit Ollama-Weiterleitung (Python, CustomTkinter) |
| `apps/ollama-models-installer/` | Modell-Installer (Python, CustomTkinter) |
| `apps/pandora-code/` | Coding-Agent fürs Terminal (Python) |
| `scripts/build_landing.py` | Baut `index.html` aus Vorlage, Bildern und Chat |
| `scripts/landing_template.html` | Vorlage der Landingpage mit Platzhaltern |
| `scripts/simulator_shim.js` | Ollama-Simulator für den Live-Simulator |
| `scripts/build_release.py` | Baut die Release-Pakete für das eigene System, Prüfsummen, Vollständigkeitsprüfung |
| `scripts/browser_check.py` | Browser-Test der Landingpage (Playwright) |
| `scripts/test_*.py` | Python-Tests für Landingpage und Build |
| `docs/` | Banner, Logo, Social-Preview und Screenshots |
| `.github/workflows/` | `ci.yml` (Tests), `release.yml` (Pakete), `pages.yml` (Landingpage) |
| `requirements-build.txt` | Pakete zum Bauen der Programme |
| `playbook/` | Projektsteuerung (diese Dateien) |
| `LICENSE`, `.gitignore`, `.gitattributes` | Lizenz, Ausschlüsse, Zeilenenden |
