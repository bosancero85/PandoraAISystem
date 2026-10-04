# Tests fuer Katalog-Logik und GUI-Logik (ohne echte GUI, mit Stubs)
# Ausfuehren: python -m unittest -v

import os
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import ollama_library as lib
import platform_support as ps


class LibraryDataTests(unittest.TestCase):
    def test_validate_library_has_no_errors(self):
        self.assertEqual(lib.validate_library(), [])

    def test_catalog_is_complete(self):
        models = lib.load_library()
        self.assertGreaterEqual(len(models), 230)
        names = [m.name for m in models]
        self.assertEqual(len(names), len(set(names)))
        for must_have in ("llama3.1", "qwen2.5-coder", "deepseek-r1", "phi4", "mistral",
                          "codegemma", "moondream", "nomic-embed-text", "gemma4"):
            self.assertIn(must_have, names)

    def test_pandora_models_are_in_catalog(self):
        # Alle kuratierten Subagenten-Modelle muessen auch in der Bibliothek stehen
        by_name = {m.name: m for m in lib.load_library()}
        curated = {
            "qwen2.5-coder": "3b", "codegemma": "2b", "deepseek-r1": "8b", "phi4": "14b",
            "phi3.5": "3.8b", "llama3.1": "8b", "mistral": "7b", "moondream": None,
            "nomic-embed-text": None,
        }
        for name, size in curated.items():
            self.assertIn(name, by_name)
            if size:
                self.assertIn(size, by_name[name].sizes)

    def test_parse_size(self):
        self.assertEqual(lib.parse_size_b("8b"), 8.0)
        self.assertEqual(lib.parse_size_b("1.5b"), 1.5)
        self.assertAlmostEqual(lib.parse_size_b("270m"), 0.27)
        self.assertEqual(lib.parse_size_b("8x7b"), 56.0)
        self.assertEqual(lib.parse_size_b("e2b"), 2.0)
        self.assertIsNone(lib.parse_size_b("latest"))

    def test_categories(self):
        by_name = {m.name: m for m in lib.load_library()}
        self.assertEqual(by_name["nomic-embed-text"].category, "Embeddings")
        self.assertEqual(by_name["llava"].category, "Vision")
        self.assertEqual(by_name["qwen2.5-coder"].category, "Code")
        self.assertEqual(by_name["deepseek-r1"].category, "Reasoning")
        self.assertEqual(by_name["llama2"].category, "Allgemein")
        for m in by_name.values():
            self.assertIn(m.category, lib.CATEGORIES)

    def test_tags(self):
        by_name = {m.name: m for m in lib.load_library()}
        self.assertEqual(by_name["llama3.1"].tag_for("8b"), "llama3.1:8b")
        self.assertEqual(by_name["llama3.1"].tag_for(lib.STD_CHOICE), "llama3.1")
        self.assertTrue(by_name["kimi-k3"].cloud_only)
        self.assertEqual(by_name["kimi-k3"].tag_for(lib.CLOUD_TAG), "kimi-k3:cloud")
        self.assertFalse(by_name["gpt-oss"].cloud_only)  # hat lokale Groessen

    def test_filter(self):
        models = lib.load_library()
        hits = lib.filter_models(models, "coder")
        self.assertTrue(hits and all("coder" in m.name for m in hits))
        self.assertFalse(any(m.cloud_only for m in lib.filter_models(models)))
        self.assertTrue(any(m.cloud_only for m in lib.filter_models(models, include_cloud=True)))
        emb = lib.filter_models(models, category="Embeddings")
        self.assertTrue(emb and all(m.category == "Embeddings" for m in emb))
        self.assertEqual(lib.filter_models(models, "zzz-gibt-es-nicht"), [])

    def test_pick_choice(self):
        by_name = {m.name: m for m in lib.load_library()}
        self.assertEqual(lib.pick_choice(by_name["llama3.1"], 8.0), "8b")
        self.assertEqual(lib.pick_choice(by_name["llama3.1"], None), "405b")
        self.assertIsNone(lib.pick_choice(by_name["deepseek-v3"], 8.0))       # nur 671b
        self.assertEqual(lib.pick_choice(by_name["qwen2.5-coder"], 4.0), "3b")
        self.assertIsNone(lib.pick_choice(by_name["glm-4.7-flash"], 8.0))     # Groesse unbekannt
        self.assertEqual(lib.pick_choice(by_name["glm-4.7-flash"], None), lib.STD_CHOICE)
        self.assertEqual(lib.pick_choice(by_name["nomic-embed-text"], 4.0), lib.STD_CHOICE)
        self.assertIsNone(lib.pick_choice(by_name["kimi-k3"], None))
        self.assertEqual(lib.pick_choice(by_name["kimi-k3"], None, include_cloud=True), lib.CLOUD_TAG)

    def test_estimate(self):
        self.assertAlmostEqual(lib.estimate_gb("llama3.1:8b"), 4.8)
        self.assertEqual(lib.estimate_gb("kimi-k3:cloud"), 0.0)
        self.assertIsNone(lib.estimate_gb("glm-4.7-flash"))
        self.assertIsNotNone(lib.estimate_gb("nomic-embed-text"))

    def test_installed_matching(self):
        installed = lib.normalize_installed({"llama3.1:8b", "moondream:latest", "nomic-embed-text"})
        self.assertTrue(lib.is_installed("llama3.1:8b", installed))
        self.assertFalse(lib.is_installed("llama3.1:70b", installed))
        self.assertFalse(lib.is_installed("llama3.1", installed))  # latest != 8b-Tag
        self.assertTrue(lib.is_installed("moondream", installed))
        self.assertTrue(lib.is_installed("nomic-embed-text", installed))

    def test_free_disk(self):
        free = lib.free_disk_gb("/nonexistent/path/xyz")
        self.assertTrue(free is None or free > 0)


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v

    def trace_add(self, *_a, **_k):
        pass


def _load_app_module():
    """Importiert ollama_model_installer mit Stubs fuer customtkinter/tkinter."""
    ctk = MagicMock()
    ctk.CTk = type("CTk", (), {})
    ctk.StringVar = _Var
    ctk.BooleanVar = _Var
    tk = types.ModuleType("tkinter")
    tk.messagebox = MagicMock()
    sys.modules["customtkinter"] = ctk
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.messagebox"] = tk.messagebox
    tk.__dict__["messagebox"] = tk.messagebox
    sys.modules.pop("ollama_model_installer", None)
    import ollama_model_installer as app_mod
    return app_mod


class GuiLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_app_module()

    def _app(self):
        app = object.__new__(self.mod.PandoraModelInstallerApp)
        app.installed_models = set()
        app.download_queue = []
        app.is_downloading = False
        app.cancelled = False
        app.batch_total = 0
        app.batch_done = 0
        app.after = MagicMock(return_value="id")
        app.after_cancel = MagicMock()
        app.log_message = MagicMock()
        app._process_download_queue = MagicMock()
        app._build_library_tab(MagicMock())
        return app

    def test_library_tab_initialises(self):
        app = self._app()
        self.assertGreaterEqual(len(app.lib_models), 230)
        self.assertEqual(len(app.lib_filtered), len([m for m in app.lib_models if not m.cloud_only]))

    def test_select_filtered_respects_limit(self):
        app = self._app()
        app.lib_limit_var.set("≤ 4B (4 GB VRAM)")
        app._lib_select_filtered()
        self.assertTrue(app.lib_selected)
        for tag in app.lib_selected.values():
            gb = self.mod.estimate_gb(tag)
            if gb is not None:
                self.assertLessEqual(gb, 4 * 0.6 + 1e-9, tag)
        self.assertEqual(app.lib_selected["llama3.2"], "llama3.2:3b")

    def test_unlimited_selects_largest(self):
        app = self._app()
        app.lib_limit_var.set("Unbegrenzt")
        app._lib_select_filtered()
        self.assertEqual(app.lib_selected["llama3.1"], "llama3.1:405b")
        self.assertNotIn("kimi-k3", app.lib_selected)  # Cloud ausgeblendet

    def test_clear_selection(self):
        app = self._app()
        app._lib_select_filtered()
        app._lib_clear_selection()
        self.assertEqual(app.lib_selected, {})

    def test_install_queues_only_pending(self):
        app = self._app()
        app.installed_models = self.mod.normalize_installed({"llama3.2:3b"})
        app.lib_selected = {"llama3.2": "llama3.2:3b", "qwen2.5-coder": "qwen2.5-coder:3b"}
        self.mod.messagebox.askyesno = MagicMock(return_value=True)
        self.mod.free_disk_gb = MagicMock(return_value=1000.0)
        app._lib_install_selected()
        self.assertEqual(app.download_queue, ["qwen2.5-coder:3b"])
        self.assertEqual(app.batch_total, 1)
        app._process_download_queue.assert_called_once()

    def test_install_declined(self):
        app = self._app()
        app.lib_selected = {"llama3.2": "llama3.2:3b"}
        self.mod.messagebox.askyesno = MagicMock(return_value=False)
        self.mod.free_disk_gb = MagicMock(return_value=1000.0)
        app._lib_install_selected()
        app._process_download_queue.assert_not_called()

    def test_install_blocked_while_downloading(self):
        app = self._app()
        app.is_downloading = True
        app.lib_selected = {"llama3.2": "llama3.2:3b"}
        self.mod.messagebox.showwarning = MagicMock()
        app._lib_install_selected()
        self.mod.messagebox.showwarning.assert_called_once()
        app._process_download_queue.assert_not_called()

    def test_show_more_pages(self):
        app = self._app()
        before = app.lib_shown
        app._lib_show_more()
        self.assertEqual(app.lib_shown, before + self.mod.LIB_PAGE_SIZE)

    def test_pull_progress_unchanged(self):
        tracker = self.mod.PullProgress()
        kind, _ = tracker.feed("pulling 6a0746a1ec1a: 50% ▕████    ▏ 2.0 GB/4.0 GB  30 MB/s  1m5s")
        self.assertEqual(kind, "progress")
        self.assertAlmostEqual(tracker.snapshot()["fraction"], 0.5, places=2)


class PlatformSupportTests(unittest.TestCase):
    def test_no_window_kwargs_only_on_windows(self):
        with patch.object(ps, "IS_WINDOWS", False):
            self.assertEqual(ps.no_window_kwargs(), {})
        with patch.object(ps, "IS_WINDOWS", True):
            self.assertIn("creationflags", ps.no_window_kwargs())

    def test_default_mono_font_per_platform(self):
        for win, mac, expected in ((True, False, "Consolas"), (False, True, "Menlo"),
                                   (False, False, "DejaVu Sans Mono")):
            with patch.object(ps, "IS_WINDOWS", win), patch.object(ps, "IS_MACOS", mac):
                self.assertEqual(ps.default_mono_font(), expected)

    def test_pick_mono_font_falls_back_without_tk(self):
        self.assertIsInstance(ps.pick_mono_font(None), str)

    def _make_fake_ollama(self, folder):
        path = os.path.join(folder, "ollama")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def test_find_ollama_via_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_ollama(tmp)
            with patch.dict(os.environ, {"PATH": tmp}), patch.object(ps, "IS_WINDOWS", False):
                self.assertEqual(ps.find_ollama(), ps.shutil.which("ollama"))
                self.assertEqual(os.path.realpath(ps.find_ollama()), os.path.realpath(fake))

    def test_find_ollama_via_known_location(self):
        # Simuliert eine macOS-.app ohne Shell-PATH
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_ollama(tmp)
            with patch.dict(os.environ, {"PATH": ""}), \
                    patch.object(ps, "_ollama_candidates", return_value=["/nonexistent/ollama", fake]):
                self.assertEqual(ps.find_ollama(), fake)
                self.assertEqual(ps.ollama_command("list"), [fake, "list"])

    def test_find_ollama_missing(self):
        with patch.dict(os.environ, {"PATH": ""}), \
                patch.object(ps, "_ollama_candidates", return_value=["/nonexistent/ollama"]):
            self.assertIsNone(ps.find_ollama())
            self.assertEqual(ps.ollama_command("pull", "x"), ["ollama", "pull", "x"])

    def test_resource_path_prefers_pyinstaller_bundle(self):
        self.assertTrue(ps.resource_path("a.png").endswith("a.png"))
        with patch.object(sys, "_MEIPASS", "/bundle", create=True):
            self.assertEqual(ps.resource_path("a.png"), os.path.join("/bundle", "a.png"))

    def test_shipped_icons_exist(self):
        for name in (ps.ICON_ICO, ps.ICON_PNG_SMALL):
            self.assertTrue(os.path.exists(ps.resource_path(name)), name)

    def test_models_dir_env_and_linux_service(self):
        with patch.dict(os.environ, {"OLLAMA_MODELS": "/data/models"}):
            self.assertEqual(lib.ollama_models_dir(), "/data/models")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {}, clear=False), \
                patch.object(lib, "LINUX_SERVICE_MODELS_DIR", tmp), \
                patch.object(lib.sys, "platform", "linux"):
            os.environ.pop("OLLAMA_MODELS", None)
            self.assertEqual(lib.ollama_models_dir(), tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
