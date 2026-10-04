# Ablage

Wo Dateien liegen. Vor dem ersten Anlegen lesen; bei Abweichung hier anpassen statt still abzuweichen.

## Struktur

```
<projekt>/
├── src/ oder <paketname>/   Quellcode
├── tests/                   Tests, spiegeln die Struktur des Quellcodes
├── docs/                    ausführliche Dokumentation (optional)
├── playbook/                dieses Playbook (mit ins Repository)
├── README.de.md             deutsche Beschreibung
├── LICENSE                  Lizenztext
├── .gitignore
└── project.toml oder pyproject.toml   Konfiguration (siehe playbook/project.toml für den Steckbrief)
```

## Regeln

- Namen: Ordner und Dateien klein, mit `_` getrennt (`session_handoff.md`); Python-Module wie üblich `snake_case`.
- Ein Modul, eine Aufgabe. Keine Sammel-Dateien wie `utils2.py` oder `neu_final.py`.
- Erzeugtes (Build, Caches, virtuelle Umgebungen, Logs, Zugangsdaten) gehört in `.gitignore`, nicht ins Repository.
- Temporäres und Experimente in `scratch/` (in `.gitignore`), nie neben den Quellcode.
- Die Playbook-Dateien bleiben in `playbook/`; nichts davon in den Quellcode-Ordner kopieren.
