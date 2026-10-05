"""Skills: das von Anthropic/agentskills.io etablierte `SKILL.md`-Format (YAML-Frontmatter + Markdown-
Anleitung), progressiv ladbar – erst nur Name+Beschreibung durchsuchen (billig, viele hundert Skills kein
Problem), dann gezielt genau eine volle Anleitung nachladen (teuer, nur bei Bedarf).

Woher Skills kommen (alle werden gemeinsam durchsucht):
- `~/.pandora/skills/` und `<projekt>/.pandora/skills/` – von Hand abgelegte/eigene Skills.
- `~/.agents/skills/` und `<projekt>/.agents/skills/` – die werkzeugübergreifende Konvention, die u. a.
  `npx skills add`, `agent-reach install` und `browser-use skill install` selbst befüllen: installiert man
  eines dieser Tools separat (siehe deren eigene Dokumentation), findet Pandora dessen Skill automatisch,
  ganz ohne eigene Pandora-Integration für dieses Tool.
- `skills/` jedes über /plugin installierten Plugins (siehe extensions/plugins.py) – z. B. ECC (293 Skills),
  Anthropic-Cybersecurity-Skills (818) oder scientific-agent-skills (177): als Plugin installiert, werden
  ihre Skills automatisch mit durchsucht.

Bewusst KEIN automatisches Einspeisen in den System-Prompt (das würde bei hunderten Skills das
Kontextfenster lokaler Modelle sofort sprengen) – der Agent sucht aktiv per Werkzeug, genau wie bei
CodeSearch/WebSearch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import home_dir

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß0-9_]{3,}")


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path  # Pfad zur SKILL.md selbst
    source: str  # Herkunfts-Verzeichnis, für Transparenz in /skills und Suchergebnissen


def parse_skill_file(path: Path) -> tuple[str, str] | None:
    """(name, description) aus der YAML-Frontmatter – ohne PyYAML-Abhängigkeit, da das Format in der Praxis
    immer flache 'key: value'-Zeilen ist (wie bei Pandoras eigenem Agent-Loader, subagents.parse_agent_file)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _FRONT.match(text)
    if not match:
        return None
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip().strip('"\'')
    name = meta.get("name") or path.parent.name
    description = meta.get("description") or ""
    return name, description


def standalone_skill_dirs(cwd: Path) -> tuple[Path, ...]:
    return (
        home_dir() / "skills", cwd / ".pandora" / "skills",
        Path.home() / ".agents" / "skills", cwd / ".agents" / "skills",
    )


def _plugin_skill_dirs() -> tuple[Path, ...]:
    """Lazy Import, um einen Importzyklus mit extensions/plugins.py zu vermeiden – wie
    subagents._plugin_agent_dirs()."""
    try:
        from .extensions.plugins import skill_dirs
    except ImportError:
        return ()
    return skill_dirs()


def discover_skills(cwd: Path) -> dict[str, SkillInfo]:
    """Liest IMMER frisch von der Platte (kein Cache) – neu installierte Plugins/Skills wirken dadurch
    ohne Neustart, genau wie subagents.load_agents()."""
    skills: dict[str, SkillInfo] = {}
    for folder in (*standalone_skill_dirs(cwd), *_plugin_skill_dirs()):
        if not folder.is_dir():
            continue
        for skill_md in sorted(folder.glob("*/SKILL.md")):
            parsed = parse_skill_file(skill_md)
            if parsed:
                name, description = parsed
                skills[name] = SkillInfo(name, description, skill_md, str(folder))
    return skills


def _score(query_words: set[str], text: str) -> int:
    text_words = set(_WORD.findall(text.lower()))
    return len(query_words & text_words)


def search_skills(cwd: Path, query: str, limit: int = 8) -> list[SkillInfo]:
    skills = discover_skills(cwd)
    query_words = set(_WORD.findall(query.lower()))
    if not query_words:
        return list(skills.values())[:limit]
    scored = [(s, _score(query_words, f"{s.name} {s.description}")) for s in skills.values()]
    scored = [(s, score) for s, score in scored if score > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [s for s, _ in scored[:limit]]


def load_skill(cwd: Path, name: str) -> str | None:
    """Volle Anleitung (Markdown-Körper nach der Frontmatter) für einen Skill – exakter oder
    groß-/kleinschreibungs-unabhängiger Namenstreffer."""
    skills = discover_skills(cwd)
    info = skills.get(name) or next((s for s in skills.values() if s.name.lower() == name.lower()), None)
    if info is None:
        return None
    match = _FRONT.match(info.path.read_text(encoding="utf-8", errors="replace"))
    return match.group(2).strip() if match else None
