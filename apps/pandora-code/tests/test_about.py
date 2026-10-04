"""Tests für Punkt 11: /about – erklärt Pandora Code (Version, Kernfähigkeiten, aktuelle Sitzungsdaten)."""
from __future__ import annotations

import io
import unittest
from unittest import mock

from pandora_code import __version__, cli
from pandora_code.ui import UI
from tests.test_extensions import ExtCase


class AboutCommandTests(ExtCase):
    def _about(self, agent) -> str:
        ui = UI(io.StringIO())
        cli.handle_command("/about", agent, mock.Mock(), ui)
        return ui.out.getvalue()

    def test_shows_current_version(self) -> None:
        agent, _ = self.make_agent([])
        self.assertIn(__version__, self._about(agent))

    def test_mentions_brand(self) -> None:
        agent, _ = self.make_agent([])
        text = self._about(agent)
        self.assertIn("Pandora", text)
        self.assertIn("AKI_SystemDown", text)

    def test_mentions_key_capabilities(self) -> None:
        agent, _ = self.make_agent([])
        text = self._about(agent)
        for keyword in ("Smart Model Router", "Code-Graph", "Vektor-RAG", "Auto-Fix", "Sandbox",
                        "WebSearch", "Sub-Agenten", "Textual"):
            self.assertIn(keyword, text)

    def test_reflects_current_session_state(self) -> None:
        agent, _ = self.make_agent([])
        agent.model = "qwen2.5-coder:14b"
        agent.perms.set_mode("yolo")
        text = self._about(agent)
        self.assertIn("qwen2.5-coder:14b", text)
        self.assertIn("yolo", text)
        self.assertIn(agent.client.host, text)

    def test_points_to_help(self) -> None:
        agent, _ = self.make_agent([])
        self.assertIn("/help", self._about(agent))

    def test_dispatch_returns_none(self) -> None:
        agent, _ = self.make_agent([])
        self.assertIsNone(cli.handle_command("/about", agent, mock.Mock(), UI(io.StringIO())))

    def test_listed_in_overview_and_reachable_via_help_about(self) -> None:
        agent, _ = self.make_agent([])
        ui = UI(io.StringIO())
        cli.handle_command("/help", agent, mock.Mock(), ui)
        self.assertIn("/about", ui.out.getvalue())
        detail_ui = UI(io.StringIO())
        cli.handle_command("/help about", agent, mock.Mock(), detail_ui)
        self.assertIn("/about", detail_ui.out.getvalue())
        self.assertNotIn("Unbekannter Befehl", detail_ui.out.getvalue())


if __name__ == "__main__":
    unittest.main()
