# Playbook

Verbindlicher Ablauf für jedes Projekt und jede größere Aufgabe. Die übrigen Dateien in diesem Ordner
gehören dazu und werden an den genannten Stellen gelesen und gepflegt.

| Datei | Zweck | Wann |
|---|---|---|
| `interview.md` | Fragen an den Nutzer, Antworten festhalten | Projektstart |
| `project.toml` | Steckbrief des Projekts (aus dem Interview) | Projektstart, danach bei Änderungen |
| `ablage.md` | Wo welche Datei liegt und wie sie heißt | vor dem ersten Anlegen von Dateien |
| `fertige_definition.md` | Wann ein Schritt und das Projekt fertig sind | vor dem Abhaken, vor dem Abschluss |
| `session_handoff.md` | Übergabe an die nächste Sitzung | nach jedem größeren Schritt und wenn der Kontext knapp wird |

## Ablauf

1. **Interview.** `interview.md` durchgehen: nur offene Fragen stellen, alle auf einmal, Antworten in
   `project.toml` und im Interview-Protokoll festhalten. Was der Nutzer schon gesagt hat, wird nicht erneut gefragt.
2. **Checkliste.** Nummerierte Checkliste aller Teilschritte erstellen (inklusive Ablage, Tests, Qualitätskontrolle,
   Formatierung, Abschlussdateien). Mit `TodoWrite` führen und dem Nutzer zeigen; alles beginnt auf `[ ]`.
3. **Abarbeiten.** Strikt von oben nach unten, immer nur ein Schritt `[~]` gleichzeitig. Nichts überspringen,
   nichts zusammenfassen.
4. **Abhaken.** Ein Schritt wird erst `[x]`, wenn er die Prüfpunkte aus `fertige_definition.md` erfüllt und das
   Ergebnis wirklich geprüft wurde (Test gelaufen, Datei gelesen, Programm gestartet). Was nicht geklappt hat,
   wird ehrlich als offen oder fehlgeschlagen gemeldet.
5. **Zwischenstand.** Nach jedem größeren Schritt Checkliste anzeigen und `session_handoff.md` aktualisieren.
6. **Abschluss.** Erst wenn alles `[x]` ist: Abschlusspunkte aus `fertige_definition.md` abarbeiten
   (`LICENSE`, `README.de.md`, `.gitignore`) und das Projekt für beendet erklären.

## Regeln

- Änderungen nur innerhalb des Arbeitsverzeichnisses, außer der Nutzer sagt ausdrücklich etwas anderes.
- Keine unnötigen Dateien anlegen; jede Datei gehört an ihren Platz laut `ablage.md`.
- Keine Geheimnisse (Schlüssel, Passwörter, Tokens) in Dateien schreiben.
- Widerspricht eine Anweisung des Nutzers diesem Playbook, gilt die Anweisung des Nutzers; kurz darauf hinweisen.
