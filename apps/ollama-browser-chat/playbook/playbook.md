# Playbook

Arbeitsweise für dieses Projekt:

1. Nummerierte Checkliste, alle Punkte starten auf `[ ]`
2. Strikt von oben nach unten abarbeiten, nichts überspringen oder zusammenfassen
3. Abhaken `[X]` erst, wenn das Ergebnis vollständig und fehlerfrei ist
4. Nach größeren Schritten den Status zeigen
5. Abschluss erst, wenn alles `[X]` ist: fertiges Repo mit LICENSE, README.de, .gitignore

Technische Leitplanken:

- Die App liegt als drei Dateien vor (`ollama.html`, `style.css`, `script.js`), alle im selben Ordner, keine externen Abhängigkeiten (kein CDN, keine Fonts, keine Bibliotheken). PWA-Dateien (`manifest.json`, `sw.js`, `icons/`) sind optionaler Zusatz.
- Der Service Worker fasst nur GET-Anfragen derselben Herkunft ohne `/api/` an, Ollama-Anfragen laufen nie über ihn
- Nutzerinhalte werden immer HTML-escaped, bevor sie angezeigt werden
- Alle Einstellungen und Chats bleiben lokal im Browser
- Branding: Kopfzeile "Pandora® Code", Fußzeile "Pandora® | by AKI_SystemDown ©2026"
