"""Werkzeuge `SkillSearch`/`SkillLoad` für das Skill-System (siehe pandora_code/skills.py) – progressives
Laden: erst günstig nach passenden Skills suchen (nur Name+Beschreibung), dann gezielt genau eine volle
Anleitung nachladen. Bewusst kein automatisches Einspeisen aller Skills in den System-Prompt – bei
hunderten Skills (ECC: 293, Anthropic-Cybersecurity-Skills: 818) würde das sofort das Kontextfenster lokaler
Modelle sprengen.

`/skills [suchbegriff]` zeigt gefundene Skills (ohne Begriff: alle) mit Herkunft.
"""
from __future__ import annotations

from ..skills import discover_skills, load_skill, search_skills
from ..tools import Tool, ToolContext, ToolError, schema


def install(agent, settings) -> None:
    def skill_search(ctx: ToolContext, args: dict) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolError("'query' fehlt.")
        limit = max(1, min(int(args.get("top_k") or 8), 20))
        hits = search_skills(agent.ctx.cwd, query, limit)
        if not hits:
            return "Keine passenden Skills gefunden. /skills zeigt alle verfügbaren."
        return "\n".join(f"{s.name}: {s.description}  [{s.source}]" for s in hits)

    def skill_load(ctx: ToolContext, args: dict) -> str:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ToolError("'name' fehlt.")
        body = load_skill(agent.ctx.cwd, name)
        if body is None:
            raise ToolError(f"Skill '{name}' nicht gefunden. Erst SkillSearch nutzen, um den genauen Namen zu finden.")
        return body

    agent.add_tool(Tool(
        "SkillSearch",
        "Search available Skills (the agentskills.io SKILL.md format – reusable, versioned how-to guides "
        "with scripts/references, bundled with plugins like ECC or installed standalone via tools such as "
        "'agent-reach install' or 'browser-use skill install'). Searches only name+description (cheap, "
        "works even with hundreds of skills) – use SkillLoad afterwards to read one skill's full guide. "
        "'top_k' caps results (default 8, max 20).",
        schema({"query": {"type": "string", "description": "What you're trying to do"},
                "top_k": {"type": "integer", "description": "Max results (default 8, max 20)"}},
               ("query",)),
        skill_search,
    ))
    agent.add_tool(Tool(
        "SkillLoad",
        "Load the full instructions of one Skill by its exact name (from SkillSearch's results). Returns "
        "the complete SKILL.md body – follow its workflow.",
        schema({"name": {"type": "string", "description": "Exact skill name from SkillSearch"}}, ("name",)),
        skill_load,
    ))

    def skills_command(arg: str, agent, ui) -> str | None:
        query = arg.strip()
        if query:
            hits = search_skills(agent.ctx.cwd, query, limit=20)
            ui.info("\n".join(f"{s.name}: {s.description}  [{s.source}]" for s in hits)
                    or "Keine Treffer.")
            return None
        skills = discover_skills(agent.ctx.cwd)
        if not skills:
            ui.info("Keine Skills gefunden. Durchsucht: ~/.pandora/skills, .pandora/skills, "
                     "~/.agents/skills, .agents/skills, sowie skills/ installierter Plugins (/plugin).")
            return None
        by_source: dict[str, int] = {}
        for s in skills.values():
            by_source[s.source] = by_source.get(s.source, 0) + 1
        lines = [f"{len(skills)} Skill(s) gefunden:"]
        lines.extend(f"  {src}: {n}" for src, n in sorted(by_source.items()))
        ui.info("\n".join(lines))
        return None

    agent.register_command(
        "skills", skills_command,
        "/skills [suchbegriff]  verfügbare Skills anzeigen oder durchsuchen (SKILL.md, Hot Reload)",
    )
