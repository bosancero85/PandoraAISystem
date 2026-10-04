"""Rauchtest der Oberflächenlogik mit Stellvertreter-Modulen.

Prüft Ablauf und Verdrahtung (Start/Stopp, Log, Tray-Befehle, Schließen), nicht das Aussehen.
Die echten Module tkinter, customtkinter und pystray werden nur für diesen Test ersetzt.
"""
import os
import socket
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPLACED = ("tkinter", "tkinter.filedialog", "customtkinter", "pystray")
_saved = {}
CHOSEN = {"path": ""}


class W:
    """Universelles Stellvertreter-Widget."""

    def __init__(self, *args, **kw):
        self.calls = []
        self.kw = dict(kw)
        self.text = kw.get("text", "")
        self.value = 0.0

    def pack(self, *a, **k):
        return self

    grid = place = pack

    def configure(self, **k):
        self.kw.update(k)
        if "text" in k:
            self.text = k["text"]

    def cget(self, key):
        return self.kw.get(key, self.text if key == "text" else None)

    def insert(self, index, text):
        self.text += text

    def delete(self, start, end=None):
        if end == "end":
            self.text = ""

    def get(self, *a):
        return self.text

    def set(self, value):
        self.value = value

    def __getattr__(self, name):
        if name in ("calls", "kw") or name.startswith("__"):
            raise AttributeError(name)

        def method(*a, **k):
            self.calls.append(name)
        return method


class FakeCheck(W):
    """Stellvertreter für CTkCheckBox."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.checked = False

    def select(self):
        self.checked = True

    def deselect(self):
        self.checked = False

    def get(self, *a):
        return 1 if self.checked else 0


class FakeCTk(W):
    def __init__(self, *a, **k):
        super().__init__()
        self.pending = []
        self.protocols = {}
        self.destroyed = False

    def after(self, ms, fn=None, *args):
        self.pending.append(fn)
        return len(self.pending)

    def after_cancel(self, ident):
        pass

    def protocol(self, name, fn):
        self.protocols[name] = fn

    def destroy(self):
        self.destroyed = True

    def run_pending(self, rounds=20):
        for _ in range(rounds):
            todo, self.pending = self.pending, []
            for fn in todo:
                if fn:
                    fn()


class FakeIcon:
    instances = []

    def __init__(self, name, image, title, menu):
        self.title, self.menu, self.icon = title, menu, image
        self.updated = 0
        self.notes = []
        self.stopped = False
        FakeIcon.instances.append(self)

    def run_detached(self):
        pass

    def update_menu(self):
        self.updated += 1

    def notify(self, message, title=None):
        self.notes.append(message)

    def stop(self):
        self.stopped = True


def _install_stubs():
    for name in _REPLACED:
        _saved[name] = sys.modules.get(name)
    ctk = types.ModuleType("customtkinter")
    ctk.CTk = FakeCTk
    for name in ("CTkFrame", "CTkLabel", "CTkButton", "CTkEntry", "CTkProgressBar", "CTkTextbox", "CTkFont"):
        setattr(ctk, name, W)
    ctk.CTkCheckBox = FakeCheck
    ctk.set_appearance_mode = ctk.set_default_color_theme = lambda *_: None
    tk = types.ModuleType("tkinter")
    fd = types.ModuleType("tkinter.filedialog")
    fd.askdirectory = lambda **k: CHOSEN["path"]
    tk.filedialog = fd
    ps = types.ModuleType("pystray")
    ps.Icon = FakeIcon
    ps.MenuItem = lambda text, action, default=False: (text, action, default)
    ps.Menu = lambda *items: items
    ps.Menu.SEPARATOR = "-"
    sys.modules.update({"customtkinter": ctk, "tkinter": tk, "tkinter.filedialog": fd, "pystray": ps})
    for mod in [m for m in sys.modules if m.startswith("mini_webserver.ui")]:
        del sys.modules[mod]


def setUpModule():
    _install_stubs()


def tearDownModule():
    for name, mod in _saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    for mod in [m for m in sys.modules if m.startswith("mini_webserver.ui")]:
        del sys.modules[mod]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        from mini_webserver.utils import settings
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = self.tmp.name  # Einstellungen nicht im echten Profil ablegen
        self.assertTrue(settings.settings_path().startswith(self.tmp.name))
        self.site = os.path.join(self.tmp.name, "site")
        os.makedirs(self.site)
        with open(os.path.join(self.site, "seite.html"), "w") as fh:
            fh.write("<p>hi</p>")
        FakeIcon.instances.clear()
        from mini_webserver.ui.app import App
        self.app = App()

    def tearDown(self):
        self.app._ctl.stop()
        self.tmp.cleanup()

    def fill(self, folder, port):
        self.app.folder_entry.text = folder
        self.app.port_entry.text = str(port)

    def test_start_stop_flow(self):
        app = self.app
        self.assertEqual(app.toggle_btn.text, "Server starten")
        self.fill(self.site, free_port())
        app.toggle()
        self.assertTrue(app._ctl.running)
        self.assertEqual(app.toggle_btn.text, "Server stoppen")
        self.assertIn("Läuft", app.status_label.text)
        self.assertTrue(app.url_label.text.endswith("/seite.html"), app.url_label.text)
        self.assertEqual(app.folder_entry.kw.get("state"), "disabled")
        app.run_pending()
        self.assertEqual(app.progress.value, 1.0)
        self.assertEqual(app.toggle_btn.kw.get("state"), "normal")
        app.toggle()
        self.assertFalse(app._ctl.running)
        app.run_pending()
        self.assertEqual(app.progress.value, 0.0)
        self.assertEqual(app.url_label.text, "–")
        self.assertEqual(app.folder_entry.kw.get("state"), "normal")
        log = app.log_box.text
        self.assertIn("Server gestartet", log)
        self.assertIn("Server gestoppt", log)
        self.assertIn("Firewall", log)
        self.assertIn("selben Netzwerk", log)

    def test_errors_do_not_start(self):
        app = self.app
        self.fill(self.site, "abc")
        app.toggle()
        self.assertFalse(app._ctl.running)
        self.assertIn("Port", app.status_label.text)
        self.assertIn("Fehler", app.log_box.text)
        self.fill(os.path.join(self.site, "nix"), 8080)
        app.toggle()
        self.assertFalse(app._ctl.running)

    def test_settings_saved_on_start(self):
        from mini_webserver.utils import settings
        port = free_port()
        self.fill(self.site, port)
        self.app.toggle()
        self.assertEqual(settings.load(), {"folder": self.site, "port": port, "https": True,
                                           "upstream": "http://127.0.0.1:11434"})

    def test_https_is_default_and_shows_https_address(self):
        app = self.app
        self.assertEqual(app.https_box.get(), 1)
        self.fill(self.site, free_port())
        app.toggle()
        self.assertTrue(app._ctl.https)
        self.assertTrue(app.url_label.text.startswith("https://"), app.url_label.text)
        self.assertTrue(app.local_label.text.startswith("Auf diesem PC: https://localhost"), app.local_label.text)
        self.assertIn("mini-webserver-ca.crt", app.ca_label.text)
        self.assertIn("CA-Datei fürs Handy", app.log_box.text)
        self.assertEqual(app.https_box.kw.get("state"), "disabled")   # nicht änderbar, solange er läuft
        app.toggle()
        self.assertEqual(app.ca_label.text, "")

    def test_http_mode_warns_about_microphone(self):
        app = self.app
        app.https_box.deselect()
        self.fill(self.site, free_port())
        app.toggle()
        self.assertFalse(app._ctl.https)
        self.assertTrue(app.url_label.text.startswith("http://"), app.url_label.text)
        self.assertIn("Mikrofon", app.ca_label.text)

    def test_bad_ollama_address_does_not_start(self):
        app = self.app
        self.fill(self.site, free_port())
        app.upstream_entry.text = "https://falsch:11434"
        app.toggle()
        self.assertFalse(app._ctl.running)
        self.assertIn("http://", app.status_label.text)

    def test_hint(self):
        self.fill(self.site, 8080)
        self.app._update_hint()
        self.assertIn("seite.html", self.app.hint_label.text)
        self.fill(self.tmp.name + "/leer_nicht_da", 8080)
        self.app._update_hint()
        self.assertIn("nicht gefunden", self.app.hint_label.text)

    def test_choose_folder(self):
        CHOSEN["path"] = self.site
        self.app._choose_folder()
        self.assertEqual(self.app.folder_entry.text, os.path.normpath(self.site))
        CHOSEN["path"] = ""
        self.app._choose_folder()  # Abbrechen ändert nichts
        self.assertEqual(self.app.folder_entry.text, os.path.normpath(self.site))

    def test_tray_commands_and_close(self):
        app = self.app
        self.assertTrue(app.tray.available)
        icon = FakeIcon.instances[-1]
        self.assertEqual(app.protocols["WM_DELETE_WINDOW"], app._on_close)
        app._on_close()  # Schließen legt in den Tray
        self.assertIn("withdraw", app.calls)
        self.assertEqual(len(icon.notes), 1)
        app._on_close()
        self.assertEqual(len(icon.notes), 1)  # Hinweis nur einmal
        # Tray-Menü: Server starten
        self.fill(self.site, free_port())
        menu = icon.menu
        toggle_label, toggle_action, _ = menu[1]
        self.assertEqual(toggle_label(None), "Server starten")
        toggle_action(icon, None)
        app.run_pending(1)
        self.assertTrue(app._ctl.running)
        self.assertEqual(toggle_label(None), "Server stoppen")
        self.assertGreaterEqual(icon.updated, 1)
        # Tray-Menü: Fenster öffnen
        menu[0][1](icon, None)
        app.run_pending(1)
        self.assertIn("deiconify", app.calls)
        # Tray-Menü: Beenden stoppt Server, Tray und Fenster
        menu[3][1](icon, None)
        app.run_pending(1)
        self.assertFalse(app._ctl.running)
        self.assertTrue(icon.stopped)
        self.assertTrue(app.destroyed)

    def test_close_without_tray_quits(self):
        from mini_webserver.ui import tray as tray_mod
        original = tray_mod.pystray
        tray_mod.pystray = None
        try:
            from mini_webserver.ui.app import App
            app = App()
            self.assertFalse(app.tray.available)
            app._on_close()
            self.assertTrue(app.destroyed)
            self.assertNotIn("withdraw", app.calls)
        finally:
            tray_mod.pystray = original

    def test_log_is_capped(self):
        for i in range(2100):
            self.app._log("Zeile %d" % i)
        self.assertLessEqual(self.app._log_lines, 2000)


if __name__ == "__main__":
    unittest.main()
