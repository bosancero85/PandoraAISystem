"""Hauptfenster (CustomTkinter)."""
from __future__ import annotations

import os
import queue
import socket
import webbrowser
from datetime import datetime
from tkinter import filedialog
from urllib.parse import quote

import customtkinter as ctk

from ..core import certs
from ..core.server import (CA_URL, ServerController, ServerError, list_html, suggest_page,
                           validate_port, validate_upstream)
from ..utils import net, paths, settings
from .tray import Tray

GREEN, GREEN_HOVER, GREEN_TEXT = "#1f9d55", "#187a43", "#3ecf7a"
RED, RED_HOVER, RED_TEXT = "#d64545", "#b03636", "#ff7b72"
MUTED = "#8b95a5"
MAX_LOG_LINES = 2000


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Mini Webserver")
        self.geometry("660x840")
        self.minsize(560, 760)

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._ctl = ServerController(log=lambda message: self._queue.put(("log", message)))
        self._prog = 0.0
        self._anim = None
        self._log_lines = 0
        self._firewall_tip_shown = False
        self._tray_tip_shown = False
        self.tray = Tray(on_show=lambda: self._queue.put(("cmd", "show")),
                         on_toggle=lambda: self._queue.put(("cmd", "toggle")),
                         on_quit=lambda: self._queue.put(("cmd", "quit")),
                         is_running=lambda: self._ctl.running)

        self._build()
        cfg = settings.load()
        self.folder_entry.insert(0, paths.initial_folder(cfg["folder"], paths.app_dir()))
        self.port_entry.insert(0, str(cfg["port"]))
        self.upstream_entry.insert(0, cfg["upstream"])
        (self.https_box.select if cfg["https"] else self.https_box.deselect)()
        self._update_hint()
        self._refresh()

        self.tray.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("Bereit. Prüfe den Ordner und starte den Server.")
        self.after(100, self._poll)

    # ---------- Aufbau ----------
    def _card(self):
        card = ctk.CTkFrame(self, corner_radius=14)
        card.pack(fill="x", padx=20, pady=(0, 12))
        return card

    def _build(self):
        ctk.CTkLabel(self, text="Mini Webserver", font=ctk.CTkFont(size=24, weight="bold"),
                     anchor="w").pack(fill="x", padx=22, pady=(18, 0))
        ctk.CTkLabel(self, text="Liefert einen Ordner im Netzwerk aus, zum Beispiel ein HTML-Projekt fürs Handy.",
                     text_color=MUTED, anchor="w", justify="left", wraplength=600).pack(fill="x", padx=22, pady=(0, 14))

        # Ordner und Port
        card = self._card()
        ctk.CTkLabel(card, text="Ordner mit dem HTML-Projekt", anchor="w").pack(fill="x", padx=16, pady=(14, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16)
        self.folder_entry = ctk.CTkEntry(row, height=38, placeholder_text="Ordnerpfad")
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.folder_entry.bind("<KeyRelease>", lambda event: self._update_hint())
        self.choose_btn = ctk.CTkButton(row, text="Ordner wählen …", width=140, height=38,
                                        command=self._choose_folder)
        self.choose_btn.pack(side="left", padx=(10, 0))
        self.hint_label = ctk.CTkLabel(card, text="", text_color=MUTED, anchor="w", justify="left", wraplength=600)
        self.hint_label.pack(fill="x", padx=16, pady=(6, 6))
        port_row = ctk.CTkFrame(card, fg_color="transparent")
        port_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(port_row, text="Port").pack(side="left")
        self.port_entry = ctk.CTkEntry(port_row, width=90, height=34, justify="center")
        self.port_entry.pack(side="left", padx=(10, 0))
        self.https_box = ctk.CTkCheckBox(card, text="HTTPS verwenden (nötig fürs Diktieren am Handy)")
        self.https_box.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(card, text="Ollama-Adresse (Weiterleitung von /api, leer = aus)", anchor="w").pack(fill="x", padx=16, pady=(0, 4))
        self.upstream_entry = ctk.CTkEntry(card, height=34, placeholder_text="http://127.0.0.1:11434")
        self.upstream_entry.pack(fill="x", padx=16, pady=(0, 14))

        # Start/Stopp
        self.toggle_btn = ctk.CTkButton(self, text="Server starten", height=54, corner_radius=14,
                                        font=ctk.CTkFont(size=17, weight="bold"), command=self.toggle)
        self.toggle_btn.pack(fill="x", padx=20, pady=(0, 8))
        self.status_label = ctk.CTkLabel(self, text="", anchor="w")
        self.status_label.pack(fill="x", padx=24)
        self.progress = ctk.CTkProgressBar(self, height=10)
        self.progress.pack(fill="x", padx=22, pady=(6, 14))
        self.progress.set(0)

        # Adresse
        card = self._card()
        ctk.CTkLabel(card, text="Adresse fürs Handy (gleiches WLAN)", anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        self.url_label = ctk.CTkLabel(card, text="–", anchor="w", font=ctk.CTkFont(size=18, weight="bold"))
        self.url_label.pack(fill="x", padx=16)
        self.local_label = ctk.CTkLabel(card, text="", anchor="w", text_color=MUTED)
        self.local_label.pack(fill="x", padx=16)
        self.ca_label = ctk.CTkLabel(card, text="", anchor="w", justify="left", text_color=MUTED, wraplength=600)
        self.ca_label.pack(fill="x", padx=16)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(8, 14))
        self.copy_btn = ctk.CTkButton(row, text="Adresse kopieren", width=150, command=self._copy)
        self.copy_btn.pack(side="left")
        self.open_btn = ctk.CTkButton(row, text="Im Browser öffnen", width=150, command=self._open_browser)
        self.open_btn.pack(side="left", padx=(10, 0))

        # Log
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22)
        ctk.CTkLabel(head, text="Log", anchor="w").pack(side="left")
        ctk.CTkButton(head, text="Leeren", width=80, height=28, fg_color="transparent", border_width=1,
                      command=self._clear_log).pack(side="right")
        self.log_box = ctk.CTkTextbox(self, height=180, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(6, 18))

    # ---------- Zustand ----------
    def _current_page(self) -> str:
        return quote(suggest_page(self._ctl.folder))

    def _refresh(self):
        running = self._ctl.running
        if running:
            self.toggle_btn.configure(text="Server stoppen", fg_color=RED, hover_color=RED_HOVER)
            self.status_label.configure(text="● Läuft auf Port %d" % self._ctl.port, text_color=GREEN_TEXT)
            self.progress.configure(progress_color=GREEN)
        else:
            self.toggle_btn.configure(text="Server starten", fg_color=GREEN, hover_color=GREEN_HOVER)
            self.status_label.configure(text="● Gestoppt", text_color=MUTED)
        state = "disabled" if running else "normal"
        for widget in (self.folder_entry, self.port_entry, self.choose_btn, self.https_box, self.upstream_entry):
            widget.configure(state=state)
        for widget in (self.copy_btn, self.open_btn):
            widget.configure(state="normal" if running else "disabled")
        if running:
            page = self._current_page()
            scheme = "https" if self._ctl.https else "http"
            self.url_label.configure(text="%s://%s:%d/%s" % (scheme, net.local_ip(), self._ctl.port, page))
            self.local_label.configure(text="Auf diesem PC: %s://localhost:%d/%s" % (scheme, self._ctl.port, page))
            if self._ctl.https:
                self.ca_label.configure(text="Beim ersten Öffnen warnt der Browser vor dem Zertifikat: „Erweitert“, dann „Weiter“. "
                                             "Ohne Warnung: %s://%s:%d%s auf dem Handy öffnen und das Zertifikat installieren."
                                             % (scheme, net.local_ip(), self._ctl.port, CA_URL))
            else:
                self.ca_label.configure(text="Ohne HTTPS sperrt der Browser am Handy das Mikrofon (Diktieren).")
        else:
            self.url_label.configure(text="–")
            self.local_label.configure(text="")
            self.ca_label.configure(text="")
        self.tray.update(running)

    def _update_hint(self):
        folder = self.folder_entry.get().strip()
        if not folder or not os.path.isdir(os.path.expanduser(folder)):
            self.hint_label.configure(text="Ordner nicht gefunden.", text_color=RED_TEXT)
            return
        files = list_html(os.path.expanduser(folder))
        if not files:
            self.hint_label.configure(text="Keine HTML-Datei in diesem Ordner gefunden.", text_color=RED_TEXT)
        else:
            shown = ", ".join(files[:4]) + (" …" if len(files) > 4 else "")
            self.hint_label.configure(text="Gefunden: " + shown, text_color=MUTED)

    # ---------- Aktionen ----------
    def toggle(self):
        if self._ctl.running:
            self._stop()
        else:
            self._start()

    def _tls_paths(self):
        """Zertifikate für diesen Rechner anlegen oder erneuern. None, wenn HTTPS aus ist."""
        if not self.https_box.get():
            return None
        hosts = [net.local_ip(), "localhost"]
        try:
            hosts.append(socket.gethostname())
        except OSError:
            pass
        paths_, renewed = certs.ensure_certificates(settings.cert_dir(), hosts)
        if renewed:
            self._log("Zertifikat für %s ausgestellt." % ", ".join(h for h in hosts if h))
        self._log("CA-Datei fürs Handy: %s" % paths_.ca_cert)
        return paths_

    def _start(self):
        try:
            upstream = validate_upstream(self.upstream_entry.get())
            self._ctl.start(self.folder_entry.get(), self.port_entry.get(), tls=self._tls_paths(), upstream=upstream)
        except (ServerError, certs.CertError) as exc:
            self._log("Fehler: %s" % exc)
            self.status_label.configure(text="● %s" % exc, text_color=RED_TEXT)
            return
        self._save()
        if not self._firewall_tip_shown:
            self._log("Tipp: Fragt Windows nach der Firewall, wähle „Zulassen“ (Privates Netzwerk).")
            self._log("Hinweis: Jedes Gerät im selben Netzwerk kann diesen Ordner sehen. "
                      "Nutze das nicht in fremden WLANs.")
            self._firewall_tip_shown = True
        self._refresh()
        self._set_busy(True)
        self._animate(1.0, lambda: self._set_busy(False))

    def _stop(self):
        self._set_busy(True)
        self._ctl.stop()
        self._refresh()
        self._animate(0.0, lambda: self._set_busy(False))

    def _set_busy(self, busy: bool):
        self.toggle_btn.configure(state="disabled" if busy else "normal")

    def _animate(self, target: float, done=None):
        if self._anim is not None:
            self.after_cancel(self._anim)
            self._anim = None

        def tick():
            if abs(target - self._prog) < 0.06:
                self._prog = target
                self.progress.set(target)
                self._anim = None
                if done:
                    done()
                return
            self._prog += 0.1 if target > self._prog else -0.1
            self.progress.set(max(0.0, min(1.0, self._prog)))
            self._anim = self.after(25, tick)

        tick()

    def _choose_folder(self):
        start = self.folder_entry.get().strip() or paths.app_dir()
        chosen = filedialog.askdirectory(initialdir=start, title="Ordner mit dem HTML-Projekt wählen")
        if chosen:
            chosen = os.path.normpath(chosen)
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)
            self._update_hint()

    def _copy(self):
        if not self._ctl.running:
            return
        url = self.url_label.cget("text")
        self.clipboard_clear()
        self.clipboard_append(url)
        self._log("Adresse kopiert: %s" % url)

    def _open_browser(self):
        if self._ctl.running:
            scheme = "https" if self._ctl.https else "http"
            webbrowser.open("%s://localhost:%d/%s" % (scheme, self._ctl.port, self._current_page()))

    def _save(self):
        try:
            port = validate_port(self.port_entry.get())
        except ServerError:
            port = settings.DEFAULTS["port"]
        settings.save({"folder": self.folder_entry.get().strip(), "port": port,
                       "https": bool(self.https_box.get()), "upstream": self.upstream_entry.get().strip()})

    # ---------- Log ----------
    def _log(self, message: str):
        line = "%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self._log_lines += 1
        if self._log_lines > MAX_LOG_LINES:
            self.log_box.delete("1.0", "501.0")
            self._log_lines -= 500
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log_lines = 0

    # ---------- Ereignisse ----------
    def _poll(self):
        """Holt Meldungen aus den Server- und Tray-Threads in den UI-Thread."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif payload == "show":
                    self._show()
                elif payload == "toggle":
                    self.toggle()
                elif payload == "quit":
                    self._quit()
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self):
        if self.tray.available:
            self.withdraw()
            if not self._tray_tip_shown:
                self.tray.notify("Läuft im Tray weiter. Zum Beenden: Rechtsklick auf das Symbol, dann „Beenden“.")
                self._tray_tip_shown = True
        else:
            self._quit()  # ohne Tray gäbe es sonst keinen Weg, das Programm zu beenden

    def _quit(self):
        self._save()
        self._ctl.stop()
        self.tray.stop()
        self.destroy()


def run():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()
