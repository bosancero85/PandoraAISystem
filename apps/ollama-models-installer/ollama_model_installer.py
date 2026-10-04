# Ollama Modell Installer by Aki_SystemDown

import os
import re
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from ollama_library import (
    CATEGORIES, CATEGORY_ALL, LIBRARY_SNAPSHOT_DATE, LIMIT_CHOICES, LIMIT_DEFAULT,
    estimate_gb, filter_models, free_disk_gb, is_installed, load_library,
    normalize_installed, pick_choice,
)
from platform_support import (
    APP_CLASS, IS_LINUX, apply_window_icon, default_mono_font, find_ollama,
    no_window_kwargs, ollama_command, pick_mono_font,
)

# Monospace-Schrift je Plattform (Consolas / Menlo / DejaVu Sans Mono);
# wird beim Start anhand der installierten Schriften verfeinert.
MONO_FONT = default_mono_font()

# CustomTkinter Configuration
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Color Palette (Cyberpunk Neon Accent)
COLOR_BG_DARK = "#121216"
COLOR_CARD_BG = "#1A1A22"
COLOR_ACCENT_PURPLE = "#9D00FF"
COLOR_ACCENT_HOVER = "#B833FF"
COLOR_CYAN = "#00E5FF"
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_MUTED = "#A0A0B0"
COLOR_SUCCESS = "#00FF66"
COLOR_WARNING = "#FFB300"
COLOR_BORDER = "#2A2A38"

LIB_PAGE_SIZE = 40
LIB_FILTER_DELAY_MS = 250

# --- Fortschrittsanzeige: Auswertung der Ausgabe von `ollama pull` ---
_no_window_kwargs = no_window_kwargs  # nur unter Windows gefuellt (siehe platform_support)
UI_UPDATE_INTERVAL = 0.1      # Sekunden zwischen GUI-Updates (verhindert Ueberlastung)
MIN_MAIN_LAYER = 10e6         # Byte: erst ab dieser Layer-Groesse gilt der Fortschritt als aussagekraeftig

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LAYER_RE = re.compile(r"pulling\s+([0-9a-f]{8,})")
PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_SIZE = r"(\d+(?:\.\d+)?)\s?([KMGT]?B)"
PAIR_RE = re.compile(_SIZE + r"\s*/\s*" + _SIZE)
LONE_SIZE_RE = re.compile(_SIZE + r"(?![\w/])")
SPEED_RE = re.compile(_SIZE + r"/s")
ETA_RE = re.compile(r"((?:\d+h)?(?:\d+m)?\d+s)\s*$")
UNIT_FACTORS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def to_bytes(number, unit):
    return float(number) * UNIT_FACTORS.get(unit, 1)


def fmt_bytes(value):
    for unit in ("B", "KB", "MB"):
        if value < 1000:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.2f} GB"


class PullProgress:
    """Wertet die Zeilen von `ollama pull` aus (reine Logik, ohne GUI)."""

    def __init__(self):
        self.layers = {}      # digest -> (Anteil 0..1, Gewicht in Byte)
        self.fraction = 0.0
        self.speed = ""
        self.eta = ""
        self.phase = "Verbinde mit Ollama ..."

    def feed(self, raw_line):
        """Gibt (art, text) zurueck: art = 'progress', 'status' oder None (leere Zeile)."""
        line = ANSI_RE.sub("", raw_line).strip()
        if not line:
            return None, ""

        m_layer = LAYER_RE.search(line)
        m_pct = PERCENT_RE.search(line)
        if m_layer and m_pct:
            digest = m_layer.group(1)
            pct = min(int(m_pct.group(1)), 100)
            pair = PAIR_RE.search(line)
            if pair:
                done = to_bytes(pair.group(1), pair.group(2))
                total = to_bytes(pair.group(3), pair.group(4))
                frac = done / total if total else pct / 100
                weight = total
            else:
                lone = LONE_SIZE_RE.findall(line)
                weight = to_bytes(*lone[-1]) if lone else self.layers.get(digest, (0.0, 0.0))[1]
                frac = pct / 100
            self.layers[digest] = (min(frac, 1.0), weight)

            speed = SPEED_RE.search(line)
            self.speed = f"{speed.group(1)} {speed.group(2)}/s" if speed else ""
            eta = ETA_RE.search(line)
            self.eta = eta.group(1) if eta else ""
            self.phase = "Lade Daten herunter"
            self.fraction = self._overall()
            return "progress", line

        if line.lower().startswith("success"):
            self.fraction = 1.0
            self.speed = ""
            self.eta = ""
        self.phase = line
        return "status", line

    def _overall(self):
        if not self.layers:
            return 0.0
        weights = [w for _, w in self.layers.values()]
        top = max(weights)
        if top == 0:  # keine Groessenangaben -> Mittelwert der Prozentwerte
            return sum(f for f, _ in self.layers.values()) / len(self.layers)
        if top < MIN_MAIN_LAYER:  # nur winzige Layer bekannt -> noch kein Fortschritt melden
            return 0.0
        return sum(f * w for f, w in self.layers.values()) / sum(weights)

    def snapshot(self):
        total = sum(w for _, w in self.layers.values())
        done = sum(f * w for f, w in self.layers.values())
        return {
            "fraction": min(self.fraction, 1.0),
            "done": done,
            "total": total,
            "speed": self.speed,
            "eta": self.eta,
            "phase": self.phase,
        }


class PandoraModelInstallerApp(ctk.CTk):
    def __init__(self):
        # Linux: WM_CLASS setzen, damit Taskleiste/Dock das Icon der .desktop-Datei zuordnen
        init_kwargs = {"className": APP_CLASS} if IS_LINUX else {}
        try:
            super().__init__(**init_kwargs)
        except TypeError:
            super().__init__()

        global MONO_FONT
        MONO_FONT = pick_mono_font(self)
        apply_window_icon(self)

        self.title("Pandora Code - Ollama Subagent Model Installer")
        self.geometry("1100x900")
        self.minsize(950, 700)
        self.configure(fg_color=COLOR_BG_DARK)

        self.installed_models = set()
        self.download_queue = []
        self.is_downloading = False
        self.current_process = None
        self.current_model = None
        self.cancelled = False
        self.batch_total = 0
        self.batch_done = 0
        self._bar_indeterminate = False

        self._build_ui()
        self.refresh_installed_models()

    def _build_ui(self):
        # Top Header Banner
        header_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD_BG, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        header_frame.pack(fill="x", padx=20, pady=(15, 10))

        title_label = ctk.CTkLabel(
            header_frame,
            text="⚡ PANDORA CODE — OLLAMA MODEL MANAGER",
            font=ctk.CTkFont(family=MONO_FONT, size=20, weight="bold"),
            text_color=COLOR_ACCENT_PURPLE
        )
        title_label.pack(anchor="w", padx=20, pady=(12, 2))

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Optimiert für Subagenten-Workflows",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED
        )
        subtitle_label.pack(anchor="w", padx=20, pady=(0, 12))

        # Control Action Bar
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=20, pady=(0, 10))

        self.btn_refresh = ctk.CTkButton(
            action_frame,
            text="🔄 Status prüfen (ollama list)",
            command=self.refresh_installed_models,
            fg_color=COLOR_BORDER,
            hover_color=COLOR_ACCENT_PURPLE,
            text_color=COLOR_TEXT_WHITE,
            width=200,
            height=36,
            corner_radius=8
        )
        self.btn_refresh.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            action_frame,
            text="⏹️ Download Abbrechen",
            command=self.cancel_download,
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            text_color=COLOR_TEXT_WHITE,
            state="disabled",
            width=180,
            height=36,
            corner_radius=8
        )
        self.btn_stop.pack(side="right")

        # Komplette Ollama-Bibliothek
        lib_frame = ctk.CTkFrame(self, fg_color="transparent")
        lib_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self._build_library_tab(lib_frame)

        # Download Progress Panel (Ladebalken)
        progress_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD_BG, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        progress_frame.pack(fill="x", padx=20, pady=(10, 0))

        progress_top = ctk.CTkFrame(progress_frame, fg_color="transparent")
        progress_top.pack(fill="x", padx=15, pady=(10, 4))

        self.lbl_progress_title = ctk.CTkLabel(
            progress_top,
            text="Kein aktiver Download",
            font=ctk.CTkFont(family=MONO_FONT, size=12, weight="bold"),
            text_color=COLOR_TEXT_WHITE
        )
        self.lbl_progress_title.pack(side="left")

        self.lbl_progress_percent = ctk.CTkLabel(
            progress_top,
            text="",
            font=ctk.CTkFont(family=MONO_FONT, size=14, weight="bold"),
            text_color=COLOR_CYAN
        )
        self.lbl_progress_percent.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=16,
            corner_radius=8,
            fg_color=COLOR_BORDER,
            progress_color=COLOR_ACCENT_PURPLE
        )
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 4))
        self.progress_bar.set(0)

        self.lbl_progress_details = ctk.CTkLabel(
            progress_frame,
            text="Bereit für Downloads.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w"
        )
        self.lbl_progress_details.pack(fill="x", padx=15)

        self.lbl_batch = ctk.CTkLabel(
            progress_frame,
            text="Gesamtfortschritt: -",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w"
        )
        self.lbl_batch.pack(fill="x", padx=15, pady=(6, 2))

        self.batch_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            corner_radius=4,
            fg_color=COLOR_BORDER,
            progress_color=COLOR_CYAN
        )
        self.batch_bar.pack(fill="x", padx=15, pady=(0, 12))
        self.batch_bar.set(0)

        # Bottom Live Terminal / Console Output
        console_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD_BG, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        console_frame.pack(fill="x", padx=20, pady=(10, 15))

        console_title_frame = ctk.CTkFrame(console_frame, fg_color="transparent")
        console_title_frame.pack(fill="x", padx=15, pady=(8, 4))

        ctk.CTkLabel(
            console_title_frame,
            text="🖥️ OLLAMA CMD LOGS & DOWNLOAD CONSOLE",
            font=ctk.CTkFont(family=MONO_FONT, size=12, weight="bold"),
            text_color=COLOR_CYAN
        ).pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            console_title_frame,
            text="Bereit",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_SUCCESS
        )
        self.lbl_status.pack(side="right")

        self.console_text = ctk.CTkTextbox(
            console_frame,
            height=130,
            font=ctk.CTkFont(family=MONO_FONT, size=11),
            fg_color="#0A0A0D",
            text_color="#00FFCC",
            border_width=1,
            border_color=COLOR_BORDER
        )
        self.console_text.pack(fill="x", padx=15, pady=(0, 12))
        self.log_message("Willkommen im Pandora Code Ollama Model Installer.\nKlicke auf 'Status prüfen' oder starte direkt den Download eines Modells.\n" + "-"*80)

    # ------------------------------------------------------------------
    # Komplette Ollama-Bibliothek
    # ------------------------------------------------------------------
    def _build_library_tab(self, parent):
        self.lib_models = load_library()
        self.lib_selected = {}   # Modellname -> vollstaendiger Tag
        self.lib_choice = {}     # Modellname -> gewaehlte Groesse (Menue-Text)
        self.lib_rows = {}       # Modellname -> Widgets der sichtbaren Zeilen
        self.lib_filtered = []
        self.lib_shown = LIB_PAGE_SIZE
        self.lib_more_btn = None
        self._lib_after_id = None

        self.lib_search_var = ctk.StringVar()
        self.lib_category_var = ctk.StringVar(value=CATEGORY_ALL)
        self.lib_cloud_var = ctk.BooleanVar(value=False)
        self.lib_limit_var = ctk.StringVar(value=LIMIT_DEFAULT)

        ctk.CTkLabel(
            parent,
            text=(f"{len(self.lib_models)} Modelle der Ollama-Bibliothek (Stand {LIBRARY_SNAPSHOT_DATE}). "
                  "Häkchen setzen und unten installieren. „Gefilterte auswählen“ nimmt je Modell die größte "
                  "Variante innerhalb des Limits; Modelle ohne Größenangabe nur bei „Unbegrenzt“. "
                  "Cloud-Modelle benötigen ein Ollama-Konto (ollama signin)."),
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
            wraplength=980
        ).pack(fill="x", anchor="w", pady=(0, 6))

        filter_bar = ctk.CTkFrame(parent, fg_color="transparent")
        filter_bar.pack(fill="x", pady=(0, 6))

        self.lib_search_entry = ctk.CTkEntry(
            filter_bar,
            textvariable=self.lib_search_var,
            placeholder_text="🔍 Suche (Name, Größe, Kategorie)",
            width=300,
            height=32
        )
        self.lib_search_entry.pack(side="left", padx=(0, 8))

        ctk.CTkOptionMenu(
            filter_bar,
            values=CATEGORIES,
            variable=self.lib_category_var,
            command=lambda _v: self._lib_apply_filter(),
            fg_color=COLOR_BORDER,
            button_color=COLOR_ACCENT_PURPLE,
            button_hover_color=COLOR_ACCENT_HOVER,
            width=160,
            height=32
        ).pack(side="left", padx=(0, 8))

        ctk.CTkCheckBox(
            filter_bar,
            text="☁ Cloud-Modelle anzeigen",
            variable=self.lib_cloud_var,
            command=self._lib_apply_filter,
            fg_color=COLOR_ACCENT_PURPLE,
            hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=(4, 8))

        self.lib_count_label = ctk.CTkLabel(
            filter_bar, text="", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED
        )
        self.lib_count_label.pack(side="right")

        select_bar = ctk.CTkFrame(parent, fg_color="transparent")
        select_bar.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            select_bar, text="Größenlimit:", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=(0, 6))

        ctk.CTkOptionMenu(
            select_bar,
            values=list(LIMIT_CHOICES.keys()),
            variable=self.lib_limit_var,
            fg_color=COLOR_BORDER,
            button_color=COLOR_ACCENT_PURPLE,
            button_hover_color=COLOR_ACCENT_HOVER,
            width=160,
            height=32
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            select_bar,
            text="☑ Gefilterte auswählen",
            command=self._lib_select_filtered,
            fg_color=COLOR_BORDER,
            hover_color=COLOR_ACCENT_PURPLE,
            width=170,
            height=32
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            select_bar,
            text="☐ Auswahl leeren",
            command=self._lib_clear_selection,
            fg_color=COLOR_BORDER,
            hover_color=COLOR_ACCENT_PURPLE,
            width=140,
            height=32
        ).pack(side="left")

        self.btn_lib_install = ctk.CTkButton(
            select_bar,
            text="🚀 Auswahl installieren (0)",
            command=self._lib_install_selected,
            fg_color=COLOR_ACCENT_PURPLE,
            hover_color=COLOR_ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
            state="disabled",
            width=220,
            height=32
        )
        self.btn_lib_install.pack(side="right")

        self.lib_list = ctk.CTkScrollableFrame(parent, fg_color="transparent", border_width=0)
        self.lib_list.pack(fill="both", expand=True)

        self.lib_summary = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=11), text_color=COLOR_CYAN, anchor="w"
        )
        self.lib_summary.pack(fill="x", pady=(6, 0))

        self.lib_search_var.trace_add("write", lambda *_: self._lib_schedule_filter())
        self._lib_apply_filter()

    def _lib_schedule_filter(self):
        """Entprellt die Suche, damit nicht bei jedem Tastendruck neu gezeichnet wird."""
        if self._lib_after_id is not None:
            self.after_cancel(self._lib_after_id)
        self._lib_after_id = self.after(LIB_FILTER_DELAY_MS, self._lib_apply_filter)

    def _lib_apply_filter(self):
        self._lib_after_id = None
        self.lib_filtered = filter_models(
            self.lib_models,
            self.lib_search_var.get(),
            self.lib_category_var.get(),
            self.lib_cloud_var.get(),
        )
        self.lib_shown = LIB_PAGE_SIZE
        self._lib_render()

    def _lib_render(self):
        for child in self.lib_list.winfo_children():
            child.destroy()
        self.lib_rows = {}
        self.lib_more_btn = None

        if not self.lib_filtered:
            ctk.CTkLabel(
                self.lib_list, text="Keine Treffer.", text_color=COLOR_TEXT_MUTED
            ).pack(pady=20)
        for model in self.lib_filtered[:self.lib_shown]:
            self._lib_add_row(model)
        self._lib_update_more_button()

        self.lib_count_label.configure(text=f"{len(self.lib_filtered)} Treffer")
        self._lib_refresh_installed_badges()

    def _lib_update_more_button(self):
        if self.lib_more_btn is not None:
            self.lib_more_btn.destroy()
            self.lib_more_btn = None
        rest = len(self.lib_filtered) - self.lib_shown
        if rest > 0:
            self.lib_more_btn = ctk.CTkButton(
                self.lib_list,
                text=f"⬇ Mehr anzeigen ({rest} weitere)",
                command=self._lib_show_more,
                fg_color=COLOR_BORDER,
                hover_color=COLOR_ACCENT_PURPLE,
                height=34
            )
            self.lib_more_btn.pack(fill="x", pady=8, padx=2)

    def _lib_show_more(self):
        start = self.lib_shown
        self.lib_shown += LIB_PAGE_SIZE
        if self.lib_more_btn is not None:
            self.lib_more_btn.destroy()
            self.lib_more_btn = None
        for model in self.lib_filtered[start:self.lib_shown]:
            self._lib_add_row(model)
        self._lib_update_more_button()
        self._lib_refresh_installed_badges()

    def _lib_add_row(self, model):
        row = ctk.CTkFrame(
            self.lib_list, fg_color=COLOR_CARD_BG, corner_radius=8,
            border_width=1, border_color=COLOR_BORDER
        )
        row.pack(fill="x", pady=3, padx=2)

        var = ctk.BooleanVar(value=model.name in self.lib_selected)
        size_var = ctk.StringVar(value=self.lib_choice.get(model.name, model.choices()[0]))

        ctk.CTkCheckBox(
            row, text="", variable=var, width=24, checkbox_width=20, checkbox_height=20,
            fg_color=COLOR_ACCENT_PURPLE, hover_color=COLOR_ACCENT_HOVER,
            command=lambda m=model, v=var, sv=size_var: self._lib_toggle(m, v, sv)
        ).pack(side="left", padx=(12, 4), pady=8)

        ctk.CTkLabel(
            row, text=model.name, width=200, anchor="w",
            font=ctk.CTkFont(family=MONO_FONT, size=13, weight="bold"),
            text_color=COLOR_TEXT_WHITE
        ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            row, text=f" {model.category} ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#2D1A4D", text_color=COLOR_ACCENT_HOVER, corner_radius=6
        ).pack(side="left", padx=4)

        if model.cap_text:
            ctk.CTkLabel(
                row, text=model.cap_text, font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
            ).pack(side="left", padx=6)

        ctk.CTkButton(
            row, text="📥 Pull", width=80, height=30, corner_radius=8,
            fg_color=COLOR_ACCENT_PURPLE, hover_color=COLOR_ACCENT_HOVER,
            command=lambda m=model, sv=size_var: self.start_single_download(m.tag_for(sv.get()))
        ).pack(side="right", padx=(6, 12), pady=8)

        ctk.CTkOptionMenu(
            row, values=model.choices(), variable=size_var, width=150, height=30,
            fg_color=COLOR_BORDER, button_color=COLOR_ACCENT_PURPLE,
            button_hover_color=COLOR_ACCENT_HOVER,
            command=lambda choice, m=model: self._lib_choice_changed(m, choice)
        ).pack(side="right", padx=6)

        status = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="transparent", text_color=COLOR_SUCCESS, corner_radius=6
        )
        status.pack(side="right", padx=6)

        self.lib_rows[model.name] = {"model": model, "size_var": size_var, "status": status}

    def _lib_toggle(self, model, var, size_var):
        if var.get():
            self.lib_selected[model.name] = model.tag_for(size_var.get())
        else:
            self.lib_selected.pop(model.name, None)
        self._lib_update_summary()

    def _lib_choice_changed(self, model, choice):
        self.lib_choice[model.name] = choice
        if model.name in self.lib_selected:
            self.lib_selected[model.name] = model.tag_for(choice)
        self._lib_refresh_installed_badges()

    def _lib_select_filtered(self):
        limit = LIMIT_CHOICES[self.lib_limit_var.get()]
        include_cloud = self.lib_cloud_var.get()
        picked = skipped = 0
        for model in self.lib_filtered:
            choice = pick_choice(model, limit, include_cloud)
            if choice is None:
                self.lib_selected.pop(model.name, None)
                skipped += 1
                continue
            self.lib_choice[model.name] = choice
            self.lib_selected[model.name] = model.tag_for(choice)
            picked += 1
        self.log_message(
            f"[INFO] Bibliothek: {picked} Modelle ausgewählt, {skipped} übersprungen "
            f"(Größe außerhalb des Limits oder unbekannt)."
        )
        self._lib_render()

    def _lib_clear_selection(self):
        self.lib_selected.clear()
        self._lib_render()

    def _lib_pending_tags(self):
        return [t for t in self.lib_selected.values() if not is_installed(t, self.installed_models)]

    @staticmethod
    def _sum_estimates(tags):
        known = [estimate_gb(t) for t in tags]
        total = sum(g for g in known if g is not None)
        unknown = sum(1 for g in known if g is None)
        return total, unknown

    def _lib_update_summary(self):
        pending = self._lib_pending_tags()
        total, unknown = self._sum_estimates(pending)
        text = (f"Ausgewählt: {len(self.lib_selected)} Modelle "
                f"({len(pending)} noch nicht installiert) · geschätzt ≈ {total:.0f} GB")
        if unknown:
            text += f" + {unknown} Modell(e) mit unbekannter Größe"
        self.lib_summary.configure(text=text)
        self.btn_lib_install.configure(
            text=f"🚀 Auswahl installieren ({len(pending)})",
            state="normal" if pending else "disabled"
        )

    def _lib_refresh_installed_badges(self):
        for entry in self.lib_rows.values():
            tag = entry["model"].tag_for(entry["size_var"].get())
            if is_installed(tag, self.installed_models):
                entry["status"].configure(text="✓ installiert")
            else:
                entry["status"].configure(text="")
        self._lib_update_summary()

    def _lib_install_selected(self):
        if self.is_downloading:
            messagebox.showwarning("Download läuft", "Es läuft bereits ein Download-Prozess. Bitte warten oder abbrechen.")
            return
        pending = self._lib_pending_tags()
        if not pending:
            messagebox.showinfo("Nichts zu tun", "Alle ausgewählten Modelle sind bereits installiert.")
            return

        total, unknown = self._sum_estimates(pending)
        lines = [
            f"{len(pending)} Modelle nacheinander per `ollama pull` herunterladen?",
            "",
            f"Geschätzte Größe: ≈ {total:.0f} GB (grobe Q4-Schätzung, Abweichungen möglich)",
        ]
        if unknown:
            lines.append(f"Dazu {unknown} Modell(e) mit unbekannter Größe.")
        free = free_disk_gb()
        if free is not None:
            lines.append(f"Freier Speicher: {free:.0f} GB")
            if total > free:
                lines += ["", "ACHTUNG: Die geschätzte Größe übersteigt den freien Speicher!"]
        if not messagebox.askyesno("Bibliothek installieren", "\n".join(lines)):
            return

        self.cancelled = False
        self.batch_total = len(pending)
        self.batch_done = 0
        self.download_queue = list(pending)
        self._process_download_queue()

    def log_message(self, msg):
        self.console_text.insert("end", msg + "\n")
        self.console_text.see("end")

    def refresh_installed_models(self):
        def worker():
            self.after(0, lambda: self.lbl_status.configure(text="Prüfe ollama list...", text_color=COLOR_WARNING))
            try:
                res = subprocess.run(
                    ollama_command("list"), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", check=True, **_no_window_kwargs()
                )
                lines = res.stdout.strip().split("\n")
                installed = set()
                for line in lines[1:]: # skip header
                    parts = line.split()
                    if parts:
                        installed.add(parts[0]) # e.g. qwen2.5-coder:3b or qwen2.5-coder:latest

                self.installed_models = normalize_installed(installed)
                self.after(0, self._update_ui_installed_status)
            except Exception as e:
                err = str(e)
                if find_ollama() is None:
                    err += " - Ollama nicht gefunden. Installation: https://ollama.com/download"
                self.after(0, lambda m=err: self.log_message(f"[FEHLER] Ollama list konnte nicht ausgeführt werden: {m}"))
                self.after(0, lambda: self.lbl_status.configure(text="Ollama nicht erreichbar", text_color="#FF4444"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_ui_installed_status(self):
        self._lib_refresh_installed_badges()
        self.lbl_status.configure(text="Bereit", text_color=COLOR_SUCCESS)
        self.log_message(f"[INFO] Installierte Modelle aktualisiert ({len(self.installed_models)} Modelle gefunden).")

    def start_single_download(self, model_tag):
        if self.is_downloading:
            messagebox.showwarning("Download läuft", "Es läuft bereits ein Download-Prozess. Bitte warten oder abbrechen.")
            return

        self.cancelled = False
        self.batch_total = 1
        self.batch_done = 0
        self.download_queue = [model_tag]
        self._process_download_queue()

    # ------------------------------------------------------------------
    # Fortschrittsanzeige
    # ------------------------------------------------------------------
    def _show_determinate(self):
        """Beendet den Lauf-Modus (unbestimmter Fortschritt), falls aktiv."""
        if self._bar_indeterminate:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self._bar_indeterminate = False

    def _reset_progress(self, model_tag):
        index = max(1, self.batch_total - len(self.download_queue))  # Nummer des gerade gestarteten Modells
        self.lbl_progress_title.configure(text=f"Lade {model_tag}")
        self.lbl_progress_percent.configure(text="")
        self.lbl_progress_details.configure(text="Verbinde mit Ollama ...")
        self.progress_bar.configure(progress_color=COLOR_ACCENT_PURPLE, mode="indeterminate")
        self.progress_bar.start()
        self._bar_indeterminate = True
        self.lbl_batch.configure(text=f"Gesamtfortschritt: Modell {index} von {self.batch_total}")
        self.batch_bar.set(self.batch_done / max(self.batch_total, 1))

    def _update_progress(self, model_tag, snap):
        if model_tag != self.current_model:
            return
        self._show_determinate()
        fraction = max(0.0, min(1.0, snap["fraction"]))
        percent_text = f"{fraction * 100:.0f} %"
        self.progress_bar.set(fraction)
        self.lbl_progress_percent.configure(text=percent_text)

        parts = []
        if snap["total"] > 0:
            parts.append(f"{fmt_bytes(snap['done'])} / {fmt_bytes(snap['total'])}")
        if snap["speed"]:
            parts.append(snap["speed"])
        if snap["eta"]:
            parts.append(f"Restzeit {snap['eta']}")
        self.lbl_progress_details.configure(text="   |   ".join(parts) if parts else snap["phase"])

    def _on_pull_status(self, model_tag, text, snap):
        if model_tag != self.current_model:
            return
        self.log_message(f"[{model_tag}] {text}")
        self.lbl_progress_details.configure(text=text)
        if snap["fraction"] >= 1.0:  # 'success'
            self._show_determinate()
            self.progress_bar.set(1.0)
            self.lbl_progress_percent.configure(text="100 %")

    def _on_pull_done(self, model_tag, ok):
        if model_tag != self.current_model:
            return
        self._show_determinate()
        if ok:
            self.batch_done += 1
            self.progress_bar.configure(progress_color=COLOR_SUCCESS)
            self.progress_bar.set(1.0)
            self.lbl_progress_percent.configure(text="100 %")
            self.lbl_progress_details.configure(text="Fertig - Modell installiert.")
        else:
            self.progress_bar.configure(progress_color="#FF4444")
            self.lbl_progress_details.configure(text="Fehlgeschlagen oder abgebrochen.")
        self.batch_bar.set(self.batch_done / max(self.batch_total, 1))

    # ------------------------------------------------------------------
    # Download-Queue
    # ------------------------------------------------------------------
    def _process_download_queue(self):
        if not self.download_queue:
            self.is_downloading = False
            self.btn_stop.configure(state="disabled")
            self._show_determinate()
            if self.cancelled:
                self.cancelled = False
                self.progress_bar.configure(progress_color="#FF4444")
                self.lbl_progress_title.configure(text="Download abgebrochen")
                self.lbl_progress_details.configure(text="Vom Nutzer abgebrochen.")
                self.lbl_status.configure(text="Download abgebrochen", text_color="#FF4444")
            else:
                all_ok = self.batch_done >= self.batch_total
                if all_ok:
                    self.lbl_progress_title.configure(text="Alle Downloads abgeschlossen")
                    self.lbl_status.configure(text="Alle Downloads abgeschlossen", text_color=COLOR_SUCCESS)
                    self.log_message("🎉 [FERTIG] Alle angeforderten Modell-Downloads wurden abgeschlossen!")
                else:
                    self.lbl_progress_title.configure(
                        text=f"Fertig: {self.batch_done} von {self.batch_total} Modellen installiert")
                    self.lbl_status.configure(text="Downloads mit Fehlern beendet", text_color=COLOR_WARNING)
                    self.log_message(
                        f"[FERTIG] {self.batch_done} von {self.batch_total} Modellen installiert - siehe Fehlermeldungen oben.")
            self.lbl_batch.configure(text=f"Gesamtfortschritt: {self.batch_done} von {self.batch_total} Modellen")
            self.batch_bar.set(self.batch_done / max(self.batch_total, 1))
            self.refresh_installed_models()
            return

        self.is_downloading = True
        self.btn_stop.configure(state="normal")
        next_model = self.download_queue.pop(0)
        self.current_model = next_model
        self._reset_progress(next_model)

        self.lbl_status.configure(text=f"Download: {next_model}", text_color=COLOR_CYAN)
        self.log_message(f"\n[START] Starte Command: ollama pull {next_model}...")

        threading.Thread(target=self._run_ollama_pull, args=(next_model,), daemon=True).start()

    def _run_ollama_pull(self, model_tag):
        tracker = PullProgress()
        last_ui_update = 0.0
        last_status = None
        try:
            cmd = ollama_command("pull", model_tag)
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_no_window_kwargs()
            )
            process = self.current_process

            for raw_line in iter(process.stdout.readline, ''):
                kind, text = tracker.feed(raw_line)
                if kind == "progress":
                    now = time.monotonic()
                    if now - last_ui_update >= UI_UPDATE_INTERVAL:
                        last_ui_update = now
                        self.after(0, lambda s=tracker.snapshot(): self._update_progress(model_tag, s))
                elif kind == "status" and text != last_status:
                    last_status = text
                    self.after(0, lambda t=text, s=tracker.snapshot(): self._on_pull_status(model_tag, t, s))

            process.stdout.close()
            return_code = process.wait()

            if return_code == 0:
                self.after(0, lambda: self.log_message(f"[ERFOLG] {model_tag} erfolgreich heruntergeladen."))
                self.after(0, lambda: self._on_pull_done(model_tag, True))
            else:
                self.after(0, lambda: self.log_message(f"[ABBRUCH/FEHLER] {model_tag} abgebrochen mit Code {return_code}."))
                self.after(0, lambda: self._on_pull_done(model_tag, False))

        except Exception as e:
            err = str(e)
            self.after(0, lambda m=err: self.log_message(f"[FEHLER] Exception während ollama pull {model_tag}: {m}"))
            self.after(0, lambda: self._on_pull_done(model_tag, False))
        finally:
            self.current_process = None
            self.after(0, self._process_download_queue)

    def cancel_download(self):
        self.cancelled = True
        self.download_queue.clear()
        if self.current_process and self.current_process.poll() is None:
            self.log_message("[ABBRUCH] Beende aktiven ollama pull Prozess...")
            self.current_process.terminate()
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(text="Breche ab ...", text_color=COLOR_WARNING)


if __name__ == "__main__":
    app = PandoraModelInstallerApp()
    app.mainloop()
