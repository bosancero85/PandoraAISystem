"""Hooks: eigene Befehle bei Ereignissen des Agenten (PreToolUse, PostToolUse, UserPromptSubmit, Stop).

Konfiguration (settings.json), gleiche Form wie bei Claude Code:
  {"hooks": {"PreToolUse": [{"matcher": "Bash|Edit", "hooks": [{"type": "command", "command": "...", "timeout": 30}]}]}}
Der Hook bekommt ein JSON-Objekt auf stdin. Exit-Code 0 = ok, 2 = blockieren (stderr geht an das Modell),
alles andere = Warnung ohne Wirkung. Alternativ blockiert auch {"decision": "block", "reason": "..."} auf stdout.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import HOOK_EVENTS
from ..tools import as_int

TOOL_EVENTS = {"PreToolUse", "PostToolUse"}


@dataclass
class HookResult:
    code: int
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def matches(matcher: str, name: str) -> bool:
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, name) is not None
    except re.error:
        return matcher == name


class HookRunner:
    def __init__(self, config: dict | None = None, cwd: Path | None = None, notify: Callable[[str], None] | None = None):
        self.config = config or {}
        self.cwd = cwd or Path.cwd()
        self.notify = notify or (lambda message: None)

    def _hooks_for(self, event: str, tool_name: str = ""):
        for group in self.config.get(event, []):
            if not isinstance(group, dict):
                continue
            if event in TOOL_EVENTS and not matches(str(group.get("matcher") or "*"), tool_name):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and hook.get("type", "command") == "command" and hook.get("command"):
                    yield hook

    def _payload(self, event: str, **extra) -> dict:
        return {"hook_event_name": event, "cwd": str(self.cwd), **extra}

    def _run(self, hook: dict, payload: dict) -> HookResult:
        timeout = as_int(hook.get("timeout"), 60)
        env = dict(os.environ, PANDORA_PROJECT_DIR=str(self.cwd))
        try:
            proc = subprocess.run(
                str(hook["command"]),
                shell=True,
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=self.cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return HookResult(-1, error=f"Zeitlimit ({timeout}s)")
        except OSError as err:
            return HookResult(-1, error=str(err))
        return HookResult(proc.returncode, proc.stdout, proc.stderr)

    def _block_reason(self, hook: dict, result: HookResult) -> str | None:
        """Begründung, wenn der Hook blockiert; sonst None (Fehler werden nur gemeldet)."""
        if result.error or result.code not in (0, 2):
            detail = result.error or f"Exit {result.code}: {result.stderr.strip()[:200]}"
            self.notify(f"Hook '{hook['command']}' fehlgeschlagen ({detail})")
            return None
        if result.code == 2:
            return (result.stderr or result.stdout).strip() or "(ohne Begründung)"
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return None
        if isinstance(data, dict) and data.get("decision") == "block":
            return str(data.get("reason") or "(ohne Begründung)")
        return None

    # -- Ereignisse ---------------------------------------------------------------
    def pre_tool(self, name: str, args: dict) -> str | None:
        payload = self._payload("PreToolUse", tool_name=name, tool_input=args)
        for hook in self._hooks_for("PreToolUse", name):
            reason = self._block_reason(hook, self._run(hook, payload))
            if reason is not None:
                return reason
        return None

    def post_tool(self, name: str, args: dict, response: str) -> str:
        payload = self._payload("PostToolUse", tool_name=name, tool_input=args, tool_response=response)
        feedback = []
        for hook in self._hooks_for("PostToolUse", name):
            reason = self._block_reason(hook, self._run(hook, payload))
            if reason is not None:
                feedback.append(reason)
        return "\n".join(feedback)

    def user_prompt(self, prompt: str) -> tuple[str | None, str]:
        """(Blockier-Grund oder None, zusätzlicher Kontext aus stdout)."""
        payload = self._payload("UserPromptSubmit", prompt=prompt)
        context = []
        for hook in self._hooks_for("UserPromptSubmit"):
            result = self._run(hook, payload)
            reason = self._block_reason(hook, result)
            if reason is not None:
                return reason, ""
            if result.code == 0 and result.stdout.strip() and not result.stdout.lstrip().startswith("{"):
                context.append(result.stdout.strip())
        return None, "\n".join(context)

    def stop(self, active: bool) -> str | None:
        payload = self._payload("Stop", stop_hook_active=active)
        for hook in self._hooks_for("Stop"):
            reason = self._block_reason(hook, self._run(hook, payload))
            if reason is not None:
                return reason
        return None


def install(agent, settings) -> None:
    agent.hooks = HookRunner(settings.hooks, agent.ctx.cwd, notify=agent.ui.info)

    def hooks_command(arg: str, agent, ui) -> str | None:
        lines = []
        for event in HOOK_EVENTS:
            for group in agent.hooks.config.get(event, []):
                for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                    lines.append(f"{event} [{group.get('matcher') or '*'}]: {hook.get('command')}")
        ui.info("\n".join(lines) or "Keine Hooks konfiguriert (~/.pandora/settings.json oder .pandora/settings.json).")
        return None

    agent.register_command("hooks", hooks_command, "/hooks  konfigurierte Hooks anzeigen")
