"""CUSTOMIZE page: theme, microphone, listening hotkey and voice feedback (TTS)."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from pages.base import Page
from services import themes, tts_settings, ui_settings
from services.tts_settings import TEST_PHRASE, TtsSettings


class CustomizePage(Page):
    title = "CUSTOMIZE"

    def build(self) -> None:
        ttk.Label(self, text="CUSTOMIZE", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Colours, microphone, listening hotkey and the computer's voice.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        cols = ttk.Frame(self)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1, uniform="c")
        cols.columnconfigure(1, weight=1, uniform="c")
        left = ttk.Frame(cols)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = ttk.Frame(cols)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_theme(left)
        self._build_microphone(right)
        self._build_hotkey(right)
        self._build_tts(right)

    # ================================================================ theme
    def _build_theme(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="THEME", style="Card.TLabelframe", padding=10)
        box.pack(fill="both", expand=True)

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Preset:").pack(side="left")
        self.preset_var = tk.StringVar(value=themes.display_name(self.ctx.settings.get("theme")))
        combo = ttk.Combobox(row, textvariable=self.preset_var, state="readonly", width=22,
                             values=list(themes.PRESETS) + [themes.CUSTOM_NAME])
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.select_preset(self.preset_var.get()))

        grid = ttk.Frame(box)
        grid.pack(fill="x", pady=(10, 0))
        grid.columnconfigure(1, weight=1)
        self._swatches: dict[str, tk.Label] = {}
        self._hex_vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(themes.EDITABLE):
            sw = tk.Label(grid, width=4, relief="solid", borderwidth=1)
            sw.grid(row=i, column=0, padx=(0, 8), pady=3, sticky="w")
            ttk.Label(grid, text=label).grid(row=i, column=1, sticky="w")
            hv = tk.StringVar()
            ttk.Label(grid, textvariable=hv, style="Muted.TLabel", width=9).grid(row=i, column=2, sticky="w")
            ttk.Button(grid, text="CHOOSE", command=lambda k=key, lb=label: self._choose_color(k, lb)
                       ).grid(row=i, column=3, padx=(8, 0), pady=2)
            self._swatches[key] = sw
            self._hex_vars[key] = hv

        ttk.Button(box, text=f"RESET TO {themes.DEFAULT_PRESET.upper()}", command=self.reset_theme
                   ).pack(anchor="w", pady=(12, 0))
        ttk.Label(box, text="Picking a colour switches the preset to Custom. Settings are saved automatically.",
                  style="Muted.TLabel", wraplength=380, justify="left").pack(anchor="w", pady=(6, 0))
        self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        colors = self.ctx.theme.colors
        for key, sw in self._swatches.items():
            c = colors.get(key, "#000000")
            try:
                sw.configure(background=c)
            except tk.TclError:
                pass
            self._hex_vars[key].set(c)
        self.preset_var.set(themes.display_name(self.ctx.settings.get("theme")))

    def _apply_theme(self, theme_settings: dict) -> None:
        self.ctx.settings["theme"] = theme_settings
        load = getattr(self.ctx.theme, "load", None)
        if callable(load):
            load(theme_settings)
        else:  # ThemeLike without load() (e.g. the test double)
            self.ctx.theme.colors.clear()
            self.ctx.theme.colors.update(themes.resolve(theme_settings))
        self.ctx.save_settings()
        self._refresh_swatches()

    def select_preset(self, name: str) -> None:
        if name not in themes.PRESETS:  # "Custom" is a state, not a choice
            self._refresh_swatches()
            return
        self._apply_theme(themes.with_preset(name))

    def set_color(self, key: str, color: str) -> None:
        try:
            new = themes.with_color(self.ctx.settings.get("theme"), key, color)
        except ValueError as e:
            self.ctx.history(str(e), "warn")
            return
        self._apply_theme(new)

    def reset_theme(self) -> None:
        self._apply_theme(themes.with_preset(themes.DEFAULT_PRESET))

    def _choose_color(self, key: str, label: str) -> None:
        chosen = colorchooser.askcolor(color=self.ctx.theme.colors.get(key), parent=self,
                                       title=f"Choose {label.title()} colour")[1]
        if chosen:
            self.set_color(key, chosen)

    # ================================================================ microphone
    def _build_microphone(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="MICROPHONE", style="Card.TLabelframe", padding=10)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.device_combo = ttk.Combobox(row, state="readonly", width=40)
        self.device_combo.pack(side="left", fill="x", expand=True)
        self.device_combo.bind("<<ComboboxSelected>>", lambda _e: self.select_device(self.device_combo.current()))
        ttk.Button(row, text="Refresh", command=lambda: self.ctx.send({"type": "list_audio_devices"})
                   ).pack(side="left", padx=(6, 0))
        self.current_device_var = tk.StringVar(value="Current: waiting for backend")
        ttk.Label(box, textvariable=self.current_device_var, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self._devices: list[tuple[str, str]] = []
        self._set_device_choices([])

    def _saved_device(self) -> str:
        v = self.ctx.settings.get("audio_device_id", "")
        return v if isinstance(v, str) else ""

    def _set_device_choices(self, devices: list) -> None:
        choices = ui_settings.device_choices(devices)
        saved = self._saved_device()
        if saved and saved not in [c[0] for c in choices]:
            choices.append((saved, "Saved microphone (not found)"))
        self._devices = choices
        self.device_combo["values"] = [label for _, label in choices]
        idx = next((i for i, (dev_id, _) in enumerate(choices) if dev_id == saved), 0)
        self.device_combo.current(idx)

    def select_device(self, index: int) -> None:
        if index < 0 or index >= len(self._devices):
            return
        dev_id, label = self._devices[index]
        self.device_combo.current(index)
        self.ctx.settings["audio_device_id"] = dev_id
        self.ctx.save_settings()
        self.ctx.send({"type": "set_audio_device", "id": dev_id})
        self.current_device_var.set(f"Switching to {label}…")

    # ================================================================ hotkey
    def _build_hotkey(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="VOICE ACTIVATION TOGGLE KEYBIND", style="Card.TLabelframe", padding=10)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(box, text="Press this key combination anywhere (even in game) to start/stop listening.",
                  style="Muted.TLabel", wraplength=380, justify="left").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        self.hotkey_var = tk.StringVar(value=ui_settings.hotkey_of(self.ctx.settings))
        entry = ttk.Entry(row, textvariable=self.hotkey_var, width=24)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self.save_hotkey())
        ttk.Button(row, text="SAVE", style="Accent.TButton", command=self.save_hotkey).pack(side="left", padx=6)
        ttk.Button(row, text="CLEAR", command=self.clear_hotkey).pack(side="left")
        ttk.Label(box, text="Examples: ctrl+shift+f12, f8, alt+f10. Clear disables the hotkey.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self.hotkey_status_var = tk.StringVar(value="")
        self.hotkey_status = ttk.Label(box, textvariable=self.hotkey_status_var, style="Muted.TLabel",
                                       wraplength=380, justify="left")
        self.hotkey_status.pack(anchor="w", pady=(4, 0))

    def _set_hotkey_status(self, text: str, style: str) -> None:
        self.hotkey_status_var.set(text)
        self.hotkey_status.configure(style=style)

    def save_hotkey(self) -> None:
        try:
            chord = ui_settings.normalize_chord(self.hotkey_var.get())
        except ValueError as e:
            self._set_hotkey_status(f"Invalid keybind: {e}", "Bad.TLabel")
            return
        self._apply_hotkey(chord)

    def clear_hotkey(self) -> None:
        self._apply_hotkey("")

    def _apply_hotkey(self, chord: str) -> None:
        self.hotkey_var.set(chord)
        self.ctx.settings["hotkey"] = chord
        self.ctx.save_settings()
        self.ctx.send({"type": "set_hotkey", "chord": chord})
        self._set_hotkey_status("Registering…" if chord else "Disabling…", "Muted.TLabel")

    # ================================================================ TTS
    def _build_tts(self, parent: ttk.Frame) -> None:
        self.tts = TtsSettings.from_dict(self.ctx.settings.get("tts"))
        self._voices: list[tts_settings.Voice] = []
        self._tts_job: str | None = None

        box = ttk.LabelFrame(parent, text="VOICE FEEDBACK (TTS)", style="Card.TLabelframe", padding=10)
        box.pack(fill="x", pady=(10, 0))
        r1 = ttk.Frame(box)
        r1.pack(fill="x")
        ttk.Label(r1, text="Voice:").pack(side="left")
        self.voice_var = tk.StringVar()
        self.voice_combo = ttk.Combobox(r1, textvariable=self.voice_var, state="readonly", width=34)
        self.voice_combo.pack(side="left", fill="x", expand=True, padx=(4, 6))
        self.voice_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_voice_selected())
        ttk.Button(r1, text="Refresh", command=self.refresh_voices).pack(side="left")

        r2 = ttk.Frame(box)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="Volume:", width=7).pack(side="left")
        self.tts_volume = tk.IntVar(value=self.tts.volume)
        ttk.Scale(r2, from_=0, to=tts_settings.MAX_VOLUME, variable=self.tts_volume,
                  command=lambda _v: self._on_slider()).pack(side="left", fill="x", expand=True, padx=4)
        self.volume_label = ttk.Label(r2, width=11)
        self.volume_label.pack(side="left")

        r3 = ttk.Frame(box)
        r3.pack(fill="x", pady=(4, 0))
        ttk.Label(r3, text="Speed:", width=7).pack(side="left")
        self.tts_rate = tk.IntVar(value=self.tts.rate)
        ttk.Scale(r3, from_=-10, to=10, variable=self.tts_rate,
                  command=lambda _v: self._on_slider()).pack(side="left", fill="x", expand=True, padx=4)
        self.rate_label = ttk.Label(r3, width=11)
        self.rate_label.pack(side="left")

        r4 = ttk.Frame(box)
        r4.pack(fill="x", pady=(8, 0))
        ttk.Button(r4, text="TEST VOICE", style="Accent.TButton", command=self.test_voice).pack(side="left")
        ttk.Button(r4, text="Add voices…", command=self._open_add_voices).pack(side="left", padx=6)
        ttk.Label(box, style="Muted.TLabel", wraplength=380, justify="left",
                  text=("100% = full level; above 100% boosts loudness (soft-limited). Add voices opens "
                        "Windows Settings → Speech; click Refresh after installing. 64-bit SAPI5 voices also "
                        "appear. Windows 'Natural' Narrator voices are not available to apps.")
                  ).pack(anchor="w", pady=(6, 0))
        self._update_tts_labels()
        self.refresh_voices(initial=True)

    def _save_tts(self) -> None:
        self.ctx.settings["tts"] = self.tts.to_dict()
        self.ctx.save_settings()

    def refresh_voices(self, initial: bool = False) -> None:
        try:
            self._voices = tts_settings.list_voices()
        except Exception as e:  # noqa: BLE001 - registry trouble must not break the page
            self._voices = [tts_settings.Voice("", "Windows default voice")]
            self.ctx.history(f"Could not list voices: {e}", "warn")
        self.voice_combo["values"] = [v.label for v in self._voices]
        idx = next((i for i, v in enumerate(self._voices) if v.token_id == self.tts.voice_id), None)
        if idx is None:
            if self.tts.voice_id and not initial:
                self.ctx.history("Saved voice is no longer installed; using Windows default.", "warn")
            idx = 0
            self.tts.voice_id = ""
        self.voice_combo.current(idx)
        if not initial:
            self.ctx.history(f"{len(self._voices) - 1} voices installed.", "info")

    def _on_voice_selected(self) -> None:
        i = self.voice_combo.current()
        if i < 0 or i >= len(self._voices):
            return
        self.tts.voice_id = self._voices[i].token_id
        self._save_tts()
        self.ctx.send({"type": "set_tts_voice", "id": self.tts.voice_id})
        self.test_voice()

    def _update_tts_labels(self) -> None:
        vol = int(round(float(self.tts_volume.get())))
        rate = int(round(float(self.tts_rate.get())))
        self.volume_label.configure(text=f"{vol}%" + (" boost" if vol > 100 else ""))
        self.rate_label.configure(text=f"{rate:+d}" if rate else "0")

    def _on_slider(self) -> None:
        self._update_tts_labels()
        if self._tts_job is not None:  # debounce: apply once the slider settles
            self.after_cancel(self._tts_job)
        self._tts_job = self.after(200, self._apply_sliders)

    def _apply_sliders(self) -> None:
        self._tts_job = None
        self.tts.volume = int(round(float(self.tts_volume.get())))
        self.tts.rate = int(round(float(self.tts_rate.get())))
        self._save_tts()
        self.ctx.send({"type": "set_tts_volume", "volume": self.tts.volume})
        self.ctx.send({"type": "set_tts_rate", "rate": self.tts.rate})

    def test_voice(self) -> None:
        if self._tts_job is not None:  # flush a pending slider change first
            self.after_cancel(self._tts_job)
            self._apply_sliders()
        self.ctx.send({"type": "speak_text", "text": TEST_PHRASE})

    def _open_add_voices(self) -> None:
        try:
            os.startfile(tts_settings.ADD_VOICES_URI)  # type: ignore[attr-defined]  # Windows only
        except (OSError, AttributeError) as e:
            messagebox.showerror("Add voices", f"Could not open Windows Speech settings:\n{e}", parent=self)
            return
        self.ctx.history("In Settings > Speech use 'Add voices', then click Refresh on CUSTOMIZE.", "info")

    # ================================================================ lifecycle
    def on_show(self) -> None:
        # The TTS on/off toggle lives on VOICE too; keep our copy in sync.
        self.tts.enabled = TtsSettings.from_dict(self.ctx.settings.get("tts")).enabled
        self._refresh_swatches()

    def on_backend_message(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "audio_devices":
            self._set_device_choices(msg.get("devices") or [])
        elif t == "mic_ready":
            name = msg.get("device_name") or "Windows default microphone"
            self.current_device_var.set(f"Current: {name}")
        elif t == "hotkey_status":
            chord = str(msg.get("chord", ""))
            if msg.get("ok"):
                if chord:
                    self._set_hotkey_status(f"Active: {chord} toggles listening.", "Good.TLabel")
                else:
                    self._set_hotkey_status("Disabled — no listening hotkey.", "Muted.TLabel")
            else:
                err = msg.get("error") or "unknown error"
                self._set_hotkey_status(f"Could not register {chord}: {err}. Choose another combination.",
                                        "Bad.TLabel")
                self.ctx.history(f"Listening hotkey {chord} could not be registered: {err}", "warn")
        elif t == "_connection" and not msg.get("connected"):
            self.current_device_var.set("Current: waiting for backend")


PAGE_CLASS = CustomizePage
