# Playbook

Arbeitsweise für dieses Projekt:

1. Nummerierte Checkliste, alle Punkte starten auf `[ ]`
2. Strikt von oben nach unten abarbeiten, nichts überspringen oder zusammenfassen
3. Abhaken `[X]` erst, wenn das Ergebnis vollständig und fehlerfrei ist
4. Nach größeren Schritten den Status zeigen
5. Abschluss erst, wenn alles `[X]` ist: fertiges Repo mit LICENSE, README.de, .gitignore

Technische Leitplanken:

- Die vier Werkzeuge liegen unter `apps/` und funktionieren einzeln. Gemeinsam sind nur Dokumentation, Skripte und Workflows im Hauptordner.
- Dateinamen der Release-Pakete stehen an **einer** Stelle: `scripts/build_release.py` (`ASSETS`). Landingpage, README und `release.yml` müssen dazu passen, `scripts/test_build_release.py` prüft das.
- `index.html` wird **nie von Hand bearbeitet**, sondern mit `python scripts/build_landing.py` aus `scripts/landing_template.html`, den Bildern in `docs/` und der echten Chat-App gebaut. Der Test `test_committed_index_html_is_current` meldet eine veraltete Datei.
- Der Live-Simulator ersetzt nur `fetch` für `/api/tags`, `/api/ps` und `/api/chat` (`scripts/simulator_shim.js`). Die Chat-App selbst bleibt unverändert, in der Demo hat sie einen eigenen Speicherschlüssel.
- Bilder für Screenshots enthalten keine persönlichen Daten (Benutzernamen, Pfade, E-Mail-Adressen). Vor jedem Veröffentlichen prüfen.
- PyInstaller baut nur für das eigene System. Darum baut `release.yml` je Betriebssystem auf einem eigenen Runner.
- Branding: Kopfzeile „Pandora® Code“ im Chat, Fußzeile „Pandora® | by AKI_SystemDown ©2026“
