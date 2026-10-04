"""Bildeingabe-Befehl: /image <pfad> [Frage]. (@pfad im Text und Read auf Bilder sind im Kern.)"""
from __future__ import annotations


def install(agent, settings) -> None:
    def image_command(arg: str, agent, ui) -> str | None:
        arg = arg.strip()
        if not arg:
            ui.info("Nutzung: /image <pfad> [Frage]   –   oder @pfad/zum/bild.png mitten im Text")
            return None
        if arg[0] in "\"'":
            end = arg.find(arg[0], 1)
            path, rest = (arg[1:end], arg[end + 1:]) if end > 0 else (arg[1:], "")
        else:
            path, _, rest = arg.partition(" ")
        return f'@"{path}" {rest.strip() or "Beschreibe dieses Bild."}'

    agent.register_command("image", image_command, "/image <pfad> [Frage]  Bild an das Modell senden (oder @bild.png im Text)")
