"""Tests: Modell und Host aus ~/.pandora/settings.json (Vorrang, Projektdateien wirkungslos)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from pandora_code import cli
from pandora_code.config import load_settings
from tests.test_extensions import ExtCase
from tests.test_pandora_code import FakeOllama, text_chunks


class ConnectionSettingsTests(ExtCase):
    def write_user(self, **data) -> None:
        self.home.mkdir(exist_ok=True)
        (self.home / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    def run_main(self, *argv: str, env: dict | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["-p", "--cwd", str(self.cwd), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_user_settings_are_read(self) -> None:
        self.write_user(model=" qwen2.5-coder:14b ", host="http://192.168.178.40:11434")
        settings = load_settings(self.cwd, lambda *_: True)
        self.assertEqual((settings.model, settings.host), ("qwen2.5-coder:14b", "http://192.168.178.40:11434"))

    def test_project_files_cannot_redirect_host_or_model(self) -> None:
        (self.cwd / ".pandora").mkdir()
        (self.cwd / ".pandora" / "settings.json").write_text(json.dumps({"model": "boese:1b", "host": "evil.example:11434"}))
        settings = load_settings(self.cwd, lambda *_: self.fail("keine Rückfrage nötig"))
        self.assertEqual((settings.model, settings.host), (None, None))

    def test_settings_used_without_flags(self) -> None:
        fake = FakeOllama([text_chunks("ok")])
        self.addCleanup(fake.close)
        self.write_user(model="qwen2.5-coder:7b", host=fake.host)
        code, _, err = self.run_main("hallo")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(fake.requests[0]["model"], "qwen2.5-coder:7b")

    def test_flags_and_env_beat_settings(self) -> None:
        fake = FakeOllama([text_chunks("a"), text_chunks("b")])
        self.addCleanup(fake.close)
        self.write_user(model="llama3.2", host="127.0.0.1:1")  # Host in settings wäre unerreichbar
        self.assertEqual(self.run_main("--host", fake.host, "-m", "qwen2.5-coder:7b", "hi")[0], 0)
        code, _, _ = self.run_main("--host", fake.host, "hi", env={"PANDORA_MODEL": "qwen2.5-coder:7b"})
        self.assertEqual(code, 0)
        self.assertEqual({r["model"] for r in fake.requests}, {"qwen2.5-coder:7b"})

    def test_model_not_installed_message_names_the_model(self) -> None:
        fake = FakeOllama([])
        self.addCleanup(fake.close)
        self.write_user(model="qwen2.5-coder:14b", host=fake.host)
        code, _, err = self.run_main("hallo")
        self.assertEqual(code, 1)
        self.assertIn("ollama pull qwen2.5-coder:14b", err)

    def test_unreachable_host_from_settings_is_reported(self) -> None:
        self.write_user(host="127.0.0.1:1")
        code, _, err = self.run_main("hallo")
        self.assertEqual(code, 1)
        self.assertIn("127.0.0.1:1", err)


if __name__ == "__main__":
    unittest.main()
