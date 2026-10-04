"""Plan-Modus: nur lesen, Plan vorlegen, nach Freigabe umschalten (wie bei Claude Code)."""
from __future__ import annotations

from ..tools import Tool, ToolError, schema

PLAN_ADDENDUM = """PLAN-MODUS ist aktiv. Du darfst nur lesen (Read, Glob, Grep, LS); Änderungen und Shell-Befehle \
sind gesperrt. Erkunde die Codebasis, entwirf dann einen konkreten Plan (betroffene Dateien, Schritte, Risiken, \
Tests) und lege ihn mit ExitPlanMode zur Genehmigung vor. Beginne erst nach der Genehmigung mit Änderungen."""

BLOCK_MESSAGE = (
    "Plan-Modus aktiv: Änderungen und Shell-Befehle sind gesperrt. "
    "Erkunde nur lesend und lege den Plan mit ExitPlanMode vor."
)


def install(agent, settings) -> None:
    perms = agent.perms

    def exit_plan_mode(ctx, args: dict) -> str:
        if perms.mode != "plan":
            raise ToolError("Nicht im Plan-Modus.")
        plan = str(args.get("plan") or "").strip()
        if not plan:
            raise ToolError("'plan' fehlt.")
        perms.show(f"\n── Vorgeschlagener Plan ──\n{plan}\n──────────────────────────")
        while True:
            try:
                answer = perms.ask("Plan genehmigen? [j]a (Edits automatisch) / [m]anuell bestätigen / [n]ein: ")
            except EOFError:
                answer = "n"
            answer = answer.strip().lower()
            if answer in ("j", "ja", "y", "yes"):
                perms.set_mode("accept-edits")
                return "Plan genehmigt. Setze ihn jetzt um; Datei-Änderungen sind automatisch erlaubt."
            if answer in ("m", "manuell"):
                perms.set_mode("ask")
                return "Plan genehmigt. Setze ihn um; jede Änderung wird einzeln bestätigt."
            if answer in ("", "n", "nein", "no"):
                try:
                    feedback = perms.ask("Was soll geändert werden? (optional): ").strip()
                except EOFError:
                    feedback = ""
                return "Plan abgelehnt." + (f" Rückmeldung: {feedback}" if feedback else "") + " Überarbeite den Plan."

    agent.add_tool(
        Tool(
            "ExitPlanMode",
            "Present your finished plan to the user for approval (only in plan mode). "
            "Call it once the plan is concrete; do not start changing files before it is approved.",
            schema({"plan": {"type": "string", "description": "The complete plan in Markdown"}}, ("plan",)),
            exit_plan_mode,
            modes=("plan",),
        )
    )

    def plan_command(arg: str, agent, ui) -> str | None:
        if arg.lower() in ("off", "aus"):
            target = perms.previous if perms.previous != "plan" else "ask"
            perms.set_mode(target)
            ui.info(f"Plan-Modus beendet (Modus: {perms.mode}).")
        else:
            perms.set_mode("plan")
            ui.info("Plan-Modus aktiv: nur lesen und planen. Mit /plan off beenden.")
        return None

    agent.register_command("plan", plan_command, "/plan [off]  Plan-Modus ein-/ausschalten (nur lesen, Plan vorlegen)")
