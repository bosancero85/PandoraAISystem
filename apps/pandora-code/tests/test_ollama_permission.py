import io
import json
import unittest
import urllib.error
from unittest import mock

from pandora_code.doctor import run_doctor, sudo_warning
from pandora_code.ollama_client import OllamaClient, OllamaError, explain_error

SERVER_MSG = "mkdir /usr/share/ollama: permission denied: ensure path elements are traversable"


class PermissionErrorTest(unittest.TestCase):
    def test_explain_adds_fix(self):
        text = explain_error(f"Ollama-Fehler 500: {SERVER_MSG}")
        self.assertIn("chown -R ollama:ollama /usr/share/ollama", text)
        self.assertIn("--doctor", text)

    def test_explain_clarifies_windows_host_means_wsl_or_docker(self):
        text = explain_error(f"Ollama-Fehler 500: {SERVER_MSG}")
        self.assertIn("WSL", text)
        self.assertIn("Docker", text)
        self.assertIn("OLLAMA_MODELS=$HOME/.ollama/models ollama serve", text)

    def test_other_errors_untouched(self):
        self.assertEqual(explain_error("model not found"), "model not found")

    def test_http_500_contains_hint(self):
        body = json.dumps({"error": SERVER_MSG}).encode()
        err = urllib.error.HTTPError("http://x", 500, "err", {}, io.BytesIO(body))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(OllamaError) as ctx:
                OllamaClient("127.0.0.1").list_models()
        self.assertIn("Ollama-Fehler 500", str(ctx.exception))
        self.assertIn("sudo systemctl restart ollama", str(ctx.exception))

    def test_stream_error_chunk_contains_hint(self):
        response = mock.MagicMock()
        response.__enter__.return_value = [json.dumps({"error": SERVER_MSG}).encode()]
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(OllamaError) as ctx:
                list(OllamaClient("127.0.0.1").chat_stream("m", []))
        self.assertIn("chown", str(ctx.exception))

    def test_sudo_warning(self):
        with mock.patch("os.geteuid", return_value=0, create=True), mock.patch.dict("os.environ", {"SUDO_USER": "kali"}):
            self.assertIn("ohne sudo", sudo_warning())
        with mock.patch("os.geteuid", return_value=1000, create=True):
            self.assertIsNone(sudo_warning())

    def test_doctor_reports_failure(self):
        with mock.patch.object(OllamaClient, "list_models", side_effect=OllamaError("nicht erreichbar")):
            report, ok = run_doctor("127.0.0.1")
        self.assertFalse(ok)
        self.assertIn("nicht erreichbar", report)


if __name__ == "__main__":
    unittest.main()
