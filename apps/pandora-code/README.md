# Pandora® 🦙 Code

Lokaler Coding-Agent für das Terminal (Nachbau des Claude-Code-Bedienkonzepts) – läuft über **Ollama**,
nur Python-Standardbibliothek, Python 3.9+.

## Plattformen
Läuft auf **Linux** (primäres Zielsystem, getestet auf Kali/Raspberry Pi 4B und Debian/Ubuntu-artigen
Systemen), **macOS** und **Windows** – überall reine Python-Standardbibliothek, keine plattformspezifische
Installation nötig, nur ein erreichbarer Ollama-Server.

- **Windows**: Das Werkzeug `Bash` erkennt automatisch eine echte Bash (Git Bash oder WSL, falls im PATH)
  und nutzt sie direkt – dann funktionieren normale Bash-Befehle wie unter Linux/macOS. Ohne installierte
  Bash laufen Befehle über `cmd.exe`; der Agent wird in diesem Fall im System-Prompt ausdrücklich auf
  Windows-Befehle (`dir`, `del`, `type`, `copy`, ...) bzw. `powershell -NoProfile -Command "..."`
  hingewiesen, schreibt also keine unpassende Bash-Syntax mehr. Farbige Ausgabe (ANSI) wird automatisch für
  Windows Terminal/neue `conhost`-Fenster aktiviert. Die **Sandbox-Engine** (Punkt „sandbox“) nutzt unter
  Windows automatisch Docker statt Firejail (Firejail ist Linux-only), sofern `sandboxContainer`/
  `sandboxImage` konfiguriert ist.
- **macOS**: Firejail ist ebenfalls Linux-only und daher nicht verfügbar; die Sandbox-Engine nutzt auch hier
  automatisch Docker, wenn konfiguriert. Alles andere (Modell-Router, AST-Graph, Vektor-RAG, Auto-Fix,
  WebSearch/WebFetch, TUI) funktioniert unverändert.
- **Alle Plattformen**: Dateien werden immer explizit als UTF-8 gelesen/geschrieben (keine
  locale-abhängigen Standard-Encodings), Pfade laufen durchgehend über `pathlib` (keine hartkodierten
  `/`-Trenner). Fehlt ein optionales Kommandozeilenprogramm (`ruff`, `eslint`, `pytest`, `npm`, `firejail`,
  `docker`, `ollama` selbst …), wird das erkannt und sauber gemeldet statt mit einem kryptischen Fehler
  abzubrechen.

## Installation und Start als Befehl
    pipx install .              # empfohlen (isoliert, auch unter Kali/Debian); alternativ: pip install .
    pandora code                # im gewünschten Ordner ausführen – auch `pandora` und `pandora-code` funktionieren

### Debian-Paket (.deb) – geteste auf Raspberry Pi 4B und Acer Aspire 5930g (Kali Linux)
Alternative zu pipx/pip: `./build_deb.sh` baut ein echtes `.deb`, das sich auf beiden Geräten gleichermaßen
installieren lässt. Pandora Code ist reines Python ohne Pflicht-Abhängigkeiten (nichts wird kompiliert),
deshalb genügt **ein** `Architecture: all`-Paket für beide Systeme – ein separates Paket je Architektur
(arm64 für den Pi, amd64 für den Acer) wäre hier unnötig.

    ./build_deb.sh                              # baut dist/pandora-code_<version>_all.deb
    sudo apt install ./dist/pandora-code_*.deb  # auf dem Pi 4B UND dem Acer gleichermaßen
    pandora code                                # danach systemweit verfügbar, kein venv/pip nötig

Installiert nach `/usr/lib/python3/dist-packages/` (Debians Standardpfad für system-weite Python-Pakete)
plus dünne Wrapper-Skripte unter `/usr/bin/pandora` und `/usr/bin/pandora-code`. Braucht zum Bauen nur
`dpkg-deb` (Teil von `dpkg`, auf jedem Kali-System vorhanden) – kein pip, kein venv, keine
Internetverbindung. Optionale Zusatzfunktionen (Tree-sitter, Textual-TUI, Playwright) lassen sich bei
Bedarf per `pip install --break-system-packages 'pandora-code[ast,tui,web]'` nachrüsten.

Der Agent arbeitet im **aktuellen Ordner** (`--cwd` ändert das): Er kann dort Dateien lesen, erstellen, ändern und
Shell-Befehle ausführen – aber jeweils erst nach deiner Bestätigung (Modus `ask`, Diff-Vorschau). Achtung: Das ist keine
Sandbox. Das Modell kann auch absolute Pfade oder `..` ansprechen; die Rückfrage ist der Schutz. Ollama selbst
liest keine Dateien, das macht nur Pandora Code über seine Werkzeuge.

## Modell und Ollama-Adresse dauerhaft festlegen
`~/.pandora/settings.json` (Windows: `%USERPROFILE%\.pandora\settings.json`), Vorlage: `settings.example.json`:

    {"model": "qwen2.5-coder:14b", "host": "http://YOUR-IP:11434"}

Vorrang Modell: `-m` > `$PANDORA_MODEL` > settings.json > automatische Wahl.
Vorrang Host: `--host` > settings.json > `$OLLAMA_HOST` > `127.0.0.1:11434`.
Aus Projektdateien (`.pandora/settings.json` im Ordner) werden `model` und `host` bewusst ignoriert – ein geklontes
Repo soll deine Anfragen nicht auf einen fremden Server umleiten.
Der Ollama-Rechner muss von außen erreichbar sein (`OLLAMA_HOST=0.0.0.0` beim Start von `ollama serve`) und das Modell
dort geladen sein (`ollama pull qwen2.5-coder:14b`).

## Modell-Router (automatischer Fallback, Hot Reload)
Pandora Code fragt die installierten Ollama-Modelle bei Bedarf live ab (`pandora_code/llm/models.py`) – ein neu mit
`ollama pull` geladenes Modell steht ohne Neustart zur Verfügung. Ein **ausdrücklich** gewähltes Modell (`-m`,
`$PANDORA_MODEL`, `settings.json`) muss installiert sein, sonst bricht der Start mit einer klaren Meldung ab.
Automatisch (ohne Ersatzfrage) wird dagegen gewechselt bei:
- **Subagenten** (`Task`-Werkzeug, Modell in einer `.md`-Agentendatei über `model:`): fehlt dieses Modell oder
  unterstützt es keine Werkzeuge, springt der Subagent auf das beste passende installierte Modell.
- **Laufzeit-Ausfall**: verschwindet das aktuell genutzte Modell während der Sitzung (z. B. durch `ollama rm`) oder
  lehnt es Tool-Calls ab, wechselt der laufende Agent automatisch weiter, statt die Sitzung abzubrechen.

Rollen für die automatische Wahl: `fast` (~7B, für einfache/Such-Aufgaben), `general` (Standard, bevorzugt das
größte Coder-Modell), `strong` (größtes installiertes Modell, für Subagenten mit `model: strong`), `tiny` (kleinstes
Modell ohne Tool-Pflicht). In `settings.json` festlegbar:

    {"models": {"fast": "qwen2.5-coder:7b", "strong": "qwen2.5-coder:14b"}}

`/models` zeigt alle installierten Modelle mit Größe, Tool-Fähigkeit und der aktuellen Rollen-Zuordnung.

### Smart Model Router (automatisch fast/general/strong je Nachricht)
Zusätzlich zum reinen Fallback entscheidet ein leichtgewichtiger, regelbasierter Router
(`pandora_code/llm/router.py`) **pro Nachricht**, welche Rolle am besten passt – ganz ohne eine zusätzliche
Modellanfrage: kurze Einzelbefehle ("suche …", "lösche …") laufen auf dem schnellen Modell (`fast`), Anfragen mit
Wörtern wie "Architektur", "Refactoring", "Debugging", sehr lange Anfragen oder mehrere Tool-Fehler in Folge
eskalieren automatisch auf das größte installierte Modell (`strong`); alles andere bleibt bei `general`. Jeder
Wechsel wird mit Begründung angezeigt (`↻ Router: …`).
- `/router` zeigt den Status, `/router aus` / `/router an` schaltet ihn um, `"router": false` in `settings.json`
  oder `--no-router` deaktiviert ihn dauerhaft.
- `/model <name>` übersteuert von Hand und **pausiert** den Router, bis `/router an` wieder aktiviert wird.
- Subagenten ohne eigenes `model:` in der Agentendatei nutzen denselben Router für ihre Aufgabe; der eingebaute
  `explore`-Agent (reine Recherche) bleibt dabei immer auf der schnellen Rolle.

## Editierbarer Prompt
Beim ersten Start entsteht `~/.pandora/prompt.md` (Standard: strukturierter Projekt-Assistent mit Checkliste).
Die Datei mit einem beliebigen Editor ändern – sie wird vor **jeder** Nachricht neu gelesen. `.pandora/prompt.md`
im Projekt hat Vorrang. `/prompt` zeigt, welche Datei gerade gilt. Wird die Datei gelöscht, entsteht sie neu.

## Playbook
`/playbook` legt `playbook/` im Arbeitsverzeichnis an (`playbook.md`, `ablage.md`, `fertige_definition.md`,
`interview.md`, `project.toml`, `session_handoff.md`); vorhandene Dateien werden nie überschrieben. Existiert der Ordner,
wird `playbook/playbook.md` in den System-Prompt geladen und der Agent hält sich daran.
Vorlagen: `pandora_code/playbook_template/`.

## Start ohne Installation
    ollama pull qwen2.5-coder:7b        # ein Modell mit Tool-Unterstützung
    python pandora_code_start.py        # interaktiv (oder: python -m pandora_code)
    python pandora_code_start.py "Erkläre dieses Projekt"
    python pandora_code_start.py -p --yolo "Führe die Tests aus"   # nicht interaktiv

Optionen: `-m/--model`, `--host`, `--cwd`, `--mode ask|accept-edits|plan|yolo`, `--yolo`, `-p/--print`,
`--no-router`, `--sandbox auto|firejail|docker|off`, `--tui`, `--doctor`,
`--disable <erweiterung>` (mehrfach möglich).
Umgebung: `OLLAMA_HOST`, `PANDORA_MODEL`, `PANDORA_NUM_CTX` (Standard 16384), `PANDORA_HOME` (Standard `~/.pandora`),
`PANDORA_DISABLE` (kommagetrennt), `NO_COLOR`.

## Textual-TUI (`pandora code --tui`)
Volle Terminal-Oberfläche statt der einfachen Konsolenausgabe (`pandora_code/ui/tui.py`): links der
Gedanken-/Tool-Aktivitäts-Stream, rechts die Live-Diff-Vorschau der zuletzt geänderten Datei (auch in
`yolo`/`accept-edits`, wo sonst nie nachgefragt wird), unten Eingabezeile und Statuszeile
(Modell/Modus/Verzeichnis) in Neon-Violett (`#9D00FF`) und Cyan. `Agent.run_turn()` läuft dabei in einem
Hintergrund-Thread, damit lange Modell-/Werkzeugaufrufe die Oberfläche nicht einfrieren.
Optionale Abhängigkeit: `pip install 'pandora-code[tui]'` (installiert `textual`). Ohne dieses Extra bleibt
die normale Konsole unverändert nutzbar; `--tui` gibt dann eine klare Installationsanweisung aus und bricht
mit Exit-Code 1 ab, statt sich nur schlechter zu verhalten.

## Befehle in der Sitzung
`/help [befehl]` zeigt die kategorisierte Übersicht, oder mit Argument eine ausführliche Erklärung zu genau
einem Befehl (z. B. `/help sandbox`) – inklusive Beispiel, wo sinnvoll. `/about` erklärt, was Pandora Code
ist und kann (Version, Kernfähigkeiten, aktuelles Modell/Modus/Ollama-Adresse).
`/clear /compact /model /models /permissions /cost /init /prompt /playbook /exit`, `!shellbefehl`, `\` am
Zeilenende = mehrzeilig. `/router [an|aus]`, `/sandbox [auto|firejail|docker|off]`.
Dazu die Befehle der Erweiterungen: `/plan [off]`, `/autofix [an|aus|...]`, `/image <pfad> [Frage]`, `/hooks`,
`/agents`, `/mcp`, `/graph [neu]`, `/rag [neu]`, `/websearch [an|aus]`.
Projekt-Notizen in `PANDORA.md` (Gegenstück zu CLAUDE.md) werden automatisch in den System-Prompt geladen.

## Werkzeuge
Read, Write, Edit, Bash, Glob, Grep, LS, TodoWrite – Write/Edit/Bash fragen vorher (Diff-Vorschau).
Erweiterungen fügen hinzu: `Task` (Subagenten), `ExitPlanMode` (nur im Plan-Modus) und `mcp__<server>__<werkzeug>`.

## Berechtigungsmodi
| Modus | Wirkung |
|---|---|
| `ask` | vor jeder Änderung und jedem Bash-Befehl fragen |
| `accept-edits` | Write/Edit automatisch, Bash weiter fragen |
| `plan` | nur lesen und planen; Änderungen und Bash sind gesperrt (auch nach „immer erlauben“) |
| `yolo` | alles automatisch (Vorsicht!) |

**Plan-Modus:** `/plan` (oder `--mode plan`) → das Modell erkundet nur lesend und legt den Plan mit `ExitPlanMode`
vor. Freigabe: `j` = umsetzen mit automatischen Edits, `m` = umsetzen mit Einzelbestätigung, `n` = ablehnen (mit Rückmeldung).

## Erweiterungen (`pandora_code/extensions/`)
Jedes Modul stellt `install(agent, settings)` bereit; ein defektes Modul verhindert den Start nicht.
Abschalten mit `--disable hooks|auto_fix|plan|vision|subagents|mcp|ast_graph|vector_rag|sandbox|web_search|plugins|skills`.

- **hooks** – eigene Befehle bei `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop` (Form wie bei Claude Code).
  Der Hook erhält JSON auf stdin; Exit-Code 2 (oder `{"decision":"block","reason":"…"}`) blockiert,
  andere Fehler sind nur Warnungen. Ein Stop-Hook darf den Agenten pro Zug höchstens 3-mal weiterarbeiten lassen.
- **auto_fix** – Auto-Fix & Continuous Quality Loop, ganz ohne Konfiguration nutzbar: nach jedem `Write`/`Edit`
  läuft sofort ein passender Linter auf genau diese Datei (Python: `ruff`, sonst `flake8`; JS/TS: `eslint` –
  jeweils nur wenn installiert); meldet er Probleme, sieht der Agent sie direkt im selben Zug. Bevor der
  Agent seinen Zug für beendet erklärt, UND nur wenn seit dem letzten grünen Lauf etwas geändert wurde, läuft
  einmal der erkannte Test-Runner (`pytest` bzw. `npm test`, je nach Markerdatei im Projekt); schlägt er fehl,
  wird der Stopp blockiert und der Agent arbeitet weiter, bis die Tests grün sind oder das Stop-Hook-Limit
  (siehe oben, Standard 3) erreicht ist. Ersetzt keine eigenen Hooks aus `settings.json`, sondern verkettet
  sich davor/dahinter. `/autofix [an|aus|lint-an|lint-aus|test-an|test-aus]` zeigt Status oder schaltet um;
  `"autoFix"`, `"autoFixLint"`, `"autoFixTest"` (bool) und `"autoFixTestCommand"` (eigener Testbefehl) in
  `settings.json`.
- **plan** – Plan-Modus, siehe oben.
- **vision** – `/image <pfad> [Frage]`. Im Kern: `@pfad/bild.png` mitten im Text und `Read` auf Bilddateien
  (png, jpg, gif, webp, bmp; max. 10 MB, max. 5 pro Nachricht). Das Modell muss Bilder unterstützen.
- **subagents** – Werkzeug `Task` delegiert Aufgaben an Subagenten mit eigenem Kontext. Eingebaut: `general-purpose`
  und `explore` (nur lesend). Eigene Agenten als Markdown in `~/.pandora/agents/` oder `.pandora/agents/`
  (Kopfzeilen `name`, `description`, `tools`, `model`). Subagenten teilen Berechtigungen, Plan-Modus und Hooks.
- **mcp** – MCP-Client für stdio- und Streamable-HTTP-Server. Nur Werkzeuge mit `readOnlyHint` laufen ohne Rückfrage;
  im Plan-Modus sind alle anderen gesperrt. `$VAR`/`${VAR}` in `env`, `args`, `url`, `headers` kommen aus der Umgebung.
- **ast_graph** – Code-Graph-Engine: `CodeSymbols`, `CodeDef` ("wo ist X definiert") und `CodeCallers`
  ("wer ruft X auf") arbeiten auf einem echten Syntaxbaum statt auf Text-Treffern – findet also nicht
  versehentlich Kommentare/Strings und unterscheidet Definition von Aufruf. Python läuft immer exakt über das
  eingebaute `ast`-Modul; für JavaScript/TypeScript/C/C++/Lua wird, falls installiert
  (`pip install pandora-code[ast]`, benötigt `tree_sitter`/`tree-sitter-languages`), Tree-sitter genutzt, sonst
  eine als solche gekennzeichnete Regex-Näherung. `/graph` zeigt Sprachen, genutztes Backend je Sprache und
  lädt geänderte Dateien nach; `/graph neu` baut komplett neu auf. Der Graph wird lazy beim ersten Zugriff
  aufgebaut, ausgeschlossen sind u. a. `.git`, `node_modules`, `venv`, `dist`, `build`.
- **vector_rag** – Werkzeug `CodeSearch`: lokales Vektor-RAG (`pandora_code/context/vector_store.py`), findet
  bei großen Repositories nur die semantisch relevanten Codeblöcke, statt das Kontextfenster mit ganzen
  Dateien zu überlasten. Nutzt automatisch ein installiertes Ollama-Embedding-Modell (z. B.
  `ollama pull nomic-embed-text`, per Hot Reload erkannt); ohne ein solches Modell greift ein
  abhängigkeitsfreier lexikalischer Fallback (Feature-Hashing über Wort-Tokens), sodass die Suche auch ganz
  ohne Zusatzinstallation nutzbar ist – nur eben weniger genau. Der Index liegt als `.pandora/vector_index.json`
  im Projekt (linear per Kosinus-Ähnlichkeit durchsucht, mit `numpy` beschleunigt falls vorhanden) und wird
  beim Wechsel des Embedding-Backends automatisch verworfen und neu aufgebaut. `/rag` zeigt Status/Backend und
  bettet neue/geänderte Dateien nach; `/rag neu` baut komplett neu. Override in `settings.json`:
  `{"embedModel": "mxbai-embed-large"}`.
- **sandbox** – schottet das Werkzeug `Bash` vom Host-System ab: `/sandbox [auto|firejail|docker|off]`.
  Standard `auto` bevorzugt **Firejail** (leichtgewichtig, kein Daemon, nutzt weiter die Host-Toolchain –
  auf Kali bleiben apt-installierte Pentest-Werkzeuge ohne Neuinstallation in einem Image nutzbar; sperrt
  u. a. Root-Rechte-Erweiterung und standardmäßig Netzwerkzugriff). **Docker** wird nur automatisch genutzt,
  wenn zusätzlich ein laufender Container (`sandboxContainer`) oder ein Image (`sandboxImage`) in
  `settings.json` konfiguriert ist. Ohne installiertes Backend läuft `Bash` wie bisher direkt auf dem Host
  (sichtbar über `/sandbox`, kein stiller Rückfall). Weitere Einstellungen: `"sandboxNetwork": true`
  (Netzwerk in der Sandbox erlauben, Standard aus), `"sandboxWorkdir"`. CLI-Override: `--sandbox off`.
- **plugins** – Plugin-System mit Hot Reload, kompatibel zum von Claude Code etablierten
  `.claude-plugin`-Format (Marketplace, `agents/`, `hooks/hooks.json`, `commands/`, `.mcp.json`, `skills/`)
  – dadurch installierbar: das bestehende Ökosystem (z. B. [ECC](https://github.com/affaan-m/ECC)) und jede
  eigene Claude-Code-Plugin-Sammlung, ohne dass deren Autoren etwas für Pandora extra bauen müssten.
  ```
  /plugin install https://github.com/affaan-m/ECC   # oder: ein lokaler Pfad zum Entwickeln (Live-Symlink)
  /plugin install ecc@https://github.com/affaan-m/ECC   # gezielt ein Plugin aus einem Marketplace-Repo
  /plugin reload <name>                               # nach lokalem Bearbeiten neu einlesen
  /plugin remove <name>
  /plugin                                              # installierte Plugins mit Bestandteilen auflisten
  ```
  **Hot Reload** heißt hier: eine Installation (oder `/plugin reload`) wirkt **sofort** in der laufenden
  Sitzung – neue Subagenten stehen dem `Task`-Werkzeug im nächsten Zug zur Verfügung, neue Hooks werden live
  in den laufenden Hook-Mechanismus gemergt (der Matcher folgt exakt der offiziell dokumentierten
  Claude-Code-Grammatik – einfache, durch `|`/`,` getrennte Werkzeugnamen oder ein unverankerter regulärer
  Ausdruck), neue MCP-Server werden sofort verbunden, neue
  `/`-Befehle aus `commands/*.md` sind direkt nutzbar ($ARGUMENTS wird ersetzt) – alles ganz ohne Neustart.
  `skills/*/SKILL.md` wird erkannt und bei `/plugin` aufgelistet, aber (noch) nicht automatisch geladen –
  Pandora hat kein dateibasiertes Skill-Laufzeitsystem wie Claude Code; das ist eine bewusste, offen
  ausgewiesene Lücke, kein verstecktes Problem.
  Ein Plugin mit eigenem `pandora_plugin.py` läuft mit vollem Zugriff (wie eine eingebaute Erweiterung) und
  bekommt deshalb eine eigene, deutlichere Sicherheitsabfrage vor dem Laden – ganz generell fragt
  `/plugin install` immer erst nach, bevor irgendetwas von der angegebenen Quelle geklont/ausgeführt wird.
  Installiert nach `~/.pandora/plugins/<name>/`.

- **skills** – Werkzeuge `SkillSearch`/`SkillLoad` für das `SKILL.md`-Format
  ([agentskills.io](https://agentskills.io)/Anthropic): progressiv durchsuchbar statt alles auf einmal in den
  Kontext zu laden (bei z. B. 818 Skills aus Anthropic-Cybersecurity-Skills würde das sofort das
  Kontextfenster sprengen). Durchsucht automatisch **vier** Quellen – `~/.pandora/skills`,
  `<projekt>/.pandora/skills`, `~/.agents/skills`, `<projekt>/.agents/skills` – plus `skills/` jedes über
  `/plugin` installierten Plugins. Die `~/.agents/skills`-Konvention ist werkzeugübergreifend: Tools wie
  `agent-reach install` oder `browser-use skill install` befüllen sie selbst – einmal separat installiert,
  findet Pandora deren Skill automatisch, ganz ohne eigene Pandora-Integration für dieses Tool.
  `/skills [suchbegriff]` zeigt Status/Treffer.

- **web_search** – Werkzeuge `WebSearch` und `WebFetch`: wenn Ollama eine Bibliothek/API nicht kennt (sein
  Trainingsstand ist zwangsläufig älter als "heute"), kann der Agent aktuelle Dokumentation nachschlagen.
  `WebSearch` nutzt zuerst eine **lokale SearXNG-Instanz** (automatisch erkannt unter `localhost:8080` u. ä.,
  oder über `"searxngUrl"` konfiguriert – die Instanz muss `formats: [html, json]` in ihrer `settings.yml`
  erlauben), sonst die DuckDuckGo-HTML-Ausgabe als externer Fallback ohne API-Key (einfache, etwas
  störanfällige Regex-Extraktion, mit klarer Kennzeichnung der genutzten Quelle im Ergebnis). `WebFetch` lädt
  eine URL und wandelt HTML in lesbaren Text um (reine Standardbibliothek); mit `"render": true` bzw.
  `"webJsRender": true` und installiertem Playwright (`pip install pandora-code[web]`) wird stattdessen ein
  echter Browser genutzt – für Seiten, die ohne JavaScript leer bleiben. `/websearch [an|aus]` zeigt Status
  oder schaltet die Suche komplett ab.

## Konfiguration
Benutzer: `~/.pandora/settings.json` und `~/.pandora/mcp.json`. Projekt: `.pandora/settings.json` und `.mcp.json`
(kompatibel zu Claude-Code-Projekten).

    {"hooks": {"PreToolUse": [{"matcher": "Bash|Edit", "hooks": [{"type": "command", "command": "./check.sh", "timeout": 30}]}]},
     "mcpServers": {"name": {"command": "npx", "args": ["-y", "server-paket"], "env": {"KEY": "${KEY}"}}}}

**Sicherheit:** Hooks und MCP-Server starten Programme. Projektdateien werden deshalb nur nach Rückfrage geladen –
der Inhalt wird angezeigt, die Bestätigung gilt für genau diesen Datei-Stand (Hash in `~/.pandora/trusted.json`).
Bei jeder Änderung wird erneut gefragt. Im Modus `-p` kann nicht gefragt werden: neue oder geänderte
Projekt-Konfiguration bleibt dort aus.

## Banner
Der Banner (`pandora_code/banner.py`) bleibt per Scroll-Region dauerhaft in den obersten Zeilen stehen.
Bei zu kleinem Terminal oder ohne TTY wird er einmal normal ausgegeben.

## Tests
    python -m unittest discover -s tests -t .
