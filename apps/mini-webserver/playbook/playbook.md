# Playbook

1. Nummerierte Checkliste, alle Punkte starten auf `[ ]`
2. Strikt von oben nach unten abarbeiten, nichts überspringen oder zusammenfassen
3. Abhaken `[X]` erst, wenn das Ergebnis vollständig und fehlerfrei ist
4. Nach größeren Schritten den Status zeigen
5. Abschluss erst bei allem `[X]`: fertiges Repo mit LICENSE, README.de, .gitignore

Leitplanken:

- Oberfläche und Meldungen auf Deutsch
- Kernlogik (core) kennt keine UI, die UI kennt keine Server-Details
- Zugriffe aus Threads laufen über eine Queue in die UI
- Server lauscht bewusst auf allen Adressen (0.0.0.0), damit das Handy zugreifen kann
