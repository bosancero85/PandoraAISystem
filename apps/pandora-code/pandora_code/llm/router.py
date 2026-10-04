"""Aufgaben-Router: verteilt Anfragen nach Komplexität auf kleine/schnelle bzw. große/starke Modelle.

Warum heuristisch statt per Modell-Klassifikation: eine zusätzliche Anfrage nur um zu entscheiden, welches
Modell antworten soll, kostet selbst wieder Zeit und Kontext. Ein paar günstige, transparente Signale
(Schlüsselwörter, Länge, aufeinanderfolgende Tool-Fehler in der Sitzung) reichen für die meisten Fälle,
werden bei jeder Entscheidung offen genannt und lassen sich per `/router aus` jederzeit abschalten oder per
`/model` von Hand übersteuern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Architektur, Refactoring, Debugging, Sicherheit, Performance – klassisch Aufgaben für ein großes Modell.
STRONG_HINTS = re.compile(
    r"\b(architektur\w*|refactor\w*|umbau\w*|entwurf\w*|design\w*|debug\w*|fehlersuche\w*|tiefgreifend\w*|"
    r"komplex\w*|überarbeit\w*|migrat\w*|sicherheitslück\w*|optimier\w*|race.?condition|deadlock|"
    r"performance\w*|analysiere gründlich|review\w*|konzept\w*|kompliziert\w*|durchdenk\w*)\b",
    re.IGNORECASE,
)
# Kurze, klar umrissene Ein-Schritt-Aufgaben – reichen für ein schnelles kleines Modell.
FAST_HINTS = re.compile(
    r"^(erstelle|lege an|schreibe|suche|finde|zeige|liste|lösche|entferne|benenne|formatiere|kopiere|"
    r"verschiebe|committe?|git |ls |cat |grep )",
    re.IGNORECASE,
)
FAILURE_ESCALATION_THRESHOLD = 2  # so viele Tool-Fehler in Folge lösen einen Wechsel auf 'strong' aus
LONG_PROMPT_CHARS = 600


@dataclass
class Signal:
    role: str  # "fast" | "general" | "strong" – siehe llm/models.py ROLES
    reason: str  # menschenlesbare Begründung, wird dem Benutzer angezeigt


@dataclass
class TaskRouter:
    enabled: bool = True
    recent_failures: int = 0  # vor jedem classify() von außen (Agent) aktuell gesetzt

    def classify(self, prompt: str) -> Signal:
        if not self.enabled:
            return Signal("general", "Router deaktiviert")
        text = (prompt or "").strip()
        if self.recent_failures >= FAILURE_ESCALATION_THRESHOLD:
            return Signal("strong", f"{self.recent_failures} Tool-Fehler in Folge – stärkeres Modell zur Fehlersuche")
        if STRONG_HINTS.search(text):
            return Signal("strong", "Anfrage klingt nach Architektur/Refactoring/Debugging")
        if len(text) > LONG_PROMPT_CHARS:
            return Signal("strong", "sehr lange, detaillierte Anfrage")
        if len(text) < 200 and FAST_HINTS.match(text):
            return Signal("fast", "kurzer, klar umrissener Einzelbefehl")
        return Signal("general", "Standardfall")
