"""Tests für Punkt 10: /help – kategorisierte Übersicht plus /help <befehl> für Details zu einem Befehl."""
from __future__ import annotations

import io
import unittest
from unittest import mock

from pandora_code import cli
from pandora_code.ui import UI
from tests.test_extensions import ExtCase


class HelpOverviewTests(ExtCase):
    def test_overview_is_categorized(self) -> None:
        agent, _ = self.make_agent([])
        banner = mock.Mock()
        ui = UI(io.StringIO())
        cli.handle_command("/help", agent, banner, ui)
        text = ui.out.getvalue()
        for heading in ("Allgemein", "Modell & Automatisierung", "Projekt & Sitzung", "Erweiterungen"):
            self.assertIn(heading, text)

    def test_overview_mentions_help_with_argument(self) -> None:
        agent, _ = self.make_agent([])
        ui = UI(io.StringIO())
        cli.handle_command("/help", agent, mock.Mock(), ui)
        self.assertIn("/help <befehl>", ui.out.getvalue())

    def test_overview_still_lists_every_active_extension_command(self) -> None:
        agent, _ = self.make_agent([])
        ui = UI(io.StringIO())
        cli.handle_command("/help", agent, mock.Mock(), ui)
        text = ui.out.getvalue()
        for command in ("/plan", "/autofix", "/image", "/hooks", "/agents", "/graph", "/rag", "/sandbox",
                        "/websearch"):
            self.assertIn(command, text)

    def test_overview_dispatch_returns_none(self) -> None:
        agent, _ = self.make_agent([])
        self.assertIsNone(cli.handle_command("/help", agent, mock.Mock(), UI(io.StringIO())))


class HelpDetailCoreCommandTests(ExtCase):
    def _detail(self, agent, arg: str) -> str:
        ui = UI(io.StringIO())
        cli.handle_command(f"/help {arg}", agent, mock.Mock(), ui)
        return ui.out.getvalue()

    def test_model_detail_has_example_and_is_longer_than_overview_line(self) -> None:
        agent, _ = self.make_agent([])
        text = self._detail(agent, "model")
        self.assertIn("Beispiel: /model", text)
        self.assertGreater(len(text), len("/model [name]         Modell anzeigen oder wechseln"))

    def test_permissions_detail_lists_all_modes(self) -> None:
        agent, _ = self.make_agent([])
        text = self._detail(agent, "permissions")
        for mode in ("ask", "accept-edits", "plan", "yolo"):
            self.assertIn(mode, text)

    def test_leading_slash_in_argument_is_tolerated(self) -> None:
        agent, _ = self.make_agent([])
        with_slash = self._detail(agent, "/router")
        without_slash = self._detail(agent, "router")
        self.assertEqual(with_slash, without_slash)

    def test_case_insensitive(self) -> None:
        agent, _ = self.make_agent([])
        self.assertEqual(self._detail(agent, "Model"), self._detail(agent, "model"))

    def test_every_core_command_in_details_dict_is_reachable(self) -> None:
        agent, _ = self.make_agent([])
        for name in cli.DETAILS:
            text = self._detail(agent, name)
            self.assertIn(f"/{name}", text)
            self.assertNotIn("Unbekannter Befehl", text)


class HelpDetailExtensionCommandTests(ExtCase):
    def _detail(self, agent, arg: str) -> str:
        ui = UI(io.StringIO())
        cli.handle_command(f"/help {arg}", agent, mock.Mock(), ui)
        return ui.out.getvalue()

    def test_extension_command_without_explicit_details_falls_back_to_its_own_help_text(self) -> None:
        agent, _ = self.make_agent([])
        _, registered_text = agent.commands["sandbox"]
        text = self._detail(agent, "sandbox")
        self.assertIn(registered_text, text)

    def test_all_active_extension_commands_are_reachable_via_help(self) -> None:
        agent, _ = self.make_agent([])
        for name in agent.commands:
            text = self._detail(agent, name)
            self.assertNotIn("Unbekannter Befehl", text)


class HelpDetailFallbackTests(ExtCase):
    def _detail(self, agent, arg: str) -> str:
        ui = UI(io.StringIO())
        cli.handle_command(f"/help {arg}", agent, mock.Mock(), ui)
        return ui.out.getvalue()

    def test_unknown_command_reports_clear_error(self) -> None:
        agent, _ = self.make_agent([])
        text = self._detail(agent, "quatsch")
        self.assertIn("Unbekannter Befehl", text)
        self.assertIn("quatsch", text)

    def test_core_command_without_long_details_falls_back_to_overview_line(self) -> None:
        # 'clear' hat eigentlich einen DETAILS-Eintrag; hier wird er geleert, um gezielt den
        # Fallback-Pfad (Zeile aus der Übersicht) isoliert zu prüfen.
        agent, _ = self.make_agent([])
        with mock.patch.dict(cli.DETAILS, {}, clear=True):
            text = cli.help_detail(agent, "clear")
        self.assertIn("/clear", text)
        self.assertIn("Gespräch zurücksetzen", text)


if __name__ == "__main__":
    unittest.main()
