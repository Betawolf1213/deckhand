"""VOICE page: status, listen/TTS controls, mic meter; shell owns the history buffer."""
from __future__ import annotations

import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from tkinter import ttk
from typing import Iterable

from pages.base import Page
from services import ui_settings
from services.tts_settings import TtsSettings

KIND_LABELS = {
    "info": "INFO",
    "heard": "HEARD",
    "command": "COMMAND",
    "answer": "ANSWER",
    "warn": "WARN",
    "error": "ERROR",
}
# history kind -> theme colour key
KIND_COLORS = {"info": "muted", "heard": "fg", "command": "accent", "answer": "good",
               "warn": "warn", "error": "bad"}
MAX_HISTORY = 500


@dataclass(frozen=True)
class Entry:
    stamp: float
    kind: str
    text: str


class HistoryBuffer:
    """Bounded history that suppresses immediate duplicates (e.g. transcript_final + question)."""

    def __init__(self, maxlen: int = MAX_HISTORY, dedupe_s: float = 3.0) -> None:
        self.entries: deque[Entry] = deque(maxlen=maxlen)
        self.dedupe_s = dedupe_s
        self.total = 0

    def add(self, kind: str, text: str, now: float | None = None) -> Entry | None:
        kind = kind if kind in KIND_LABELS else "info"
        now = time.time() if now is None else now
        text = str(text)
        if self.entries:
            last = self.entries[-1]
            if last.kind == kind and last.text == text and now - last.stamp < self.dedupe_s:
                return None
        entry = Entry(now, kind, text)
        self.entries.append(entry)
        self.total += 1
        return entry


def format_entry(e: Entry) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(e.stamp))
    return f"[{stamp}]  {KIND_LABELS.get(e.kind, 'INFO'):<8}  {e.text}"


class VoicePage(Page):
    title = "VOICE"

    def build(self) -> None:
        self.connected = False
        self.listening_var = tk.BooleanVar(value=False)
        self.tts_var = tk.BooleanVar(value=self._tts().enabled)
        self.state_var = tk.StringVar(value="OFFLINE")
        self.backend_var = tk.StringVar(value="Backend: waiting for deckhand.exe…")
        self.engine_var = tk.StringVar(value="")
        self.mic_var = tk.StringVar(value="Microphone: waiting for backend")
        self.level_var = tk.DoubleVar(value=0.0)
        self.partial_var = tk.StringVar(value="")
        self.hotkey_var = tk.StringVar()
        self.count_var = tk.StringVar(value="0 events")
        self._mic_id: str | None = None
        self._lines = 0

        ttk.Label(self, text="VOICE", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Start listening, watch what the computer hears, and see every command and answer.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        top = ttk.Frame(self)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        status = ttk.LabelFrame(top, text="STATUS", style="Card.TLabelframe", padding=10)
        status.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.state_label = ttk.Label(status, textvariable=self.state_var, style="Status.TLabel")
        self.state_label.pack(anchor="w")
        ttk.Label(status, textvariable=self.backend_var).pack(anchor="w")
        ttk.Label(status, textvariable=self.engine_var, style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(status)
        row.pack(fill="x", pady=(8, 0))
        self.listen_button = ttk.Button(row, text="START LISTENING", style="Accent.TButton",
                                        command=self.toggle_listening)
        self.listen_button.pack(side="left")
        ttk.Button(row, text="STOP SPEAKING", command=self.stop_speaking).pack(side="left", padx=6)
        ttk.Checkbutton(row, text="Voice feedback (TTS)", variable=self.tts_var,
                        command=self.toggle_tts).pack(side="left", padx=(6, 0))
        ttk.Label(status, textvariable=self.hotkey_var, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        mic = ttk.LabelFrame(top, text="MICROPHONE", style="Card.TLabelframe", padding=10)
        mic.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(mic, textvariable=self.mic_var, wraplength=420, justify="left").pack(anchor="w")
        ttk.Progressbar(mic, variable=self.level_var, maximum=100.0, length=260,
                        mode="determinate").pack(anchor="w", fill="x", pady=(8, 4))
        ttk.Label(mic, text="Change the microphone on CUSTOMIZE.", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(mic, textvariable=self.partial_var, style="Muted.TLabel", wraplength=420).pack(anchor="w")

        hist = ttk.LabelFrame(self, text="HISTORY", style="Card.TLabelframe", padding=10)
        hist.pack(fill="both", expand=True, pady=(10, 0))
        hist_bar = ttk.Frame(hist)
        hist_bar.pack(fill="x")
        ttk.Label(hist_bar, textvariable=self.count_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(hist_bar, text="Clear", command=self.clear_history).pack(side="right")
        ttk.Button(hist_bar, text="Reload commands", command=lambda: self.ctx.send({"type": "reload_config"})
                   ).pack(side="right", padx=6)
        ttk.Button(hist_bar, text="Ping backend", command=lambda: self.ctx.send({"type": "ping"})).pack(side="right")

        body = ttk.Frame(hist)
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.history_text = tk.Text(body, height=14, wrap="word", state="disabled",
                                    font=("Consolas", 10), padx=8, pady=6)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.history_text.yview)
        self.history_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.history_text.pack(side="left", fill="both", expand=True)
        self.ctx.theme.style_text(self.history_text)
        self.history_text.bind("<<DeckhandTheme>>", lambda _e: self._color_tags())
        self._color_tags()

        self._refresh_state()
        self._refresh_hotkey_hint()

    # ---- helpers ----
    def _tts(self) -> TtsSettings:
        return TtsSettings.from_dict(self.ctx.settings.get("tts"))

    def _color_tags(self) -> None:
        colors = self.ctx.theme.colors
        for kind, key in KIND_COLORS.items():
            self.history_text.tag_configure(kind, foreground=colors.get(key, colors.get("fg", "#ffffff")))

    def _refresh_state(self) -> None:
        on = bool(self.listening_var.get())
        if not self.connected:
            self.state_var.set("OFFLINE")
        else:
            self.state_var.set("LISTENING" if on else "PAUSED")
        self.listen_button.configure(text="STOP LISTENING" if on else "START LISTENING",
                                     style="Danger.TButton" if on else "Accent.TButton")

    def _refresh_hotkey_hint(self) -> None:
        chord = ui_settings.hotkey_of(self.ctx.settings)
        if chord:
            self.hotkey_var.set(f"Toggle listening from anywhere with {chord.upper()} (change it on CUSTOMIZE).")
        else:
            self.hotkey_var.set("No listening hotkey set — add one on CUSTOMIZE.")

    # ---- history rendering (called by the shell) ----
    def append_entry(self, entry: Entry) -> None:
        t = self.history_text
        t.configure(state="normal")
        t.insert("end", format_entry(entry) + "\n", entry.kind)
        self._lines += 1
        if self._lines > MAX_HISTORY:
            t.delete("1.0", f"{self._lines - MAX_HISTORY + 1}.0")
            self._lines = MAX_HISTORY
        t.configure(state="disabled")
        t.see("end")
        total = int(self.count_var.get().split()[0]) + 1
        self.count_var.set(f"{total} events")

    def show_entries(self, entries: Iterable[Entry]) -> None:
        for e in entries:
            self.append_entry(e)

    def clear_history(self) -> None:
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.configure(state="disabled")
        self._lines = 0
        self.count_var.set("0 events")

    # ---- actions ----
    def toggle_listening(self) -> None:
        on = not bool(self.listening_var.get())
        self.listening_var.set(on)
        self.ctx.send({"type": "set_listening", "enabled": on})
        self._refresh_state()

    def toggle_tts(self) -> None:
        tts = self._tts()
        tts.enabled = bool(self.tts_var.get())
        self.ctx.settings["tts"] = tts.to_dict()
        self.ctx.save_settings()
        self.ctx.send({"type": "set_tts_enabled", "enabled": tts.enabled})

    def stop_speaking(self) -> None:
        self.ctx.send({"type": "stop_speaking"})

    def on_show(self) -> None:
        self.tts_var.set(self._tts().enabled)
        self._refresh_hotkey_hint()

    # ---- backend messages ----
    def on_backend_message(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "audio_level":
            try:
                peak = float(msg.get("peak", 0.0))
            except (TypeError, ValueError):
                peak = 0.0
            self.level_var.set(max(0.0, min(1.0, peak)) * 100.0)
        elif t == "_connection":
            self.connected = bool(msg.get("connected"))
            if self.connected:
                self.backend_var.set("Backend: connected")
                self.mic_var.set("Microphone: connected, waiting for audio")
            else:
                self.backend_var.set("Backend: offline — waiting for deckhand.exe…")
                self.mic_var.set("Microphone: waiting for backend")
                self.level_var.set(0.0)
                self.listening_var.set(False)
                self._mic_id = None
            self._refresh_state()
        elif t == "status":
            self.connected = True
            self.listening_var.set(bool(msg.get("listening", False)))
            engine = msg.get("engine") or "?"
            elevated = "elevated" if msg.get("elevated") else "NOT elevated (keys may not reach the game)"
            self.engine_var.set(f"Engine: {engine} · {elevated}")
            self._refresh_state()
        elif t == "mic_ready":
            name = msg.get("device_name") or "Windows default microphone"
            self.mic_var.set(f"Microphone: {name} — {msg.get('sample_rate', 0)} Hz, {msg.get('channels', 0)} ch")
            dev = str(msg.get("device_id", ""))
            if dev != self._mic_id:
                self._mic_id = dev
                self.ctx.history(f"Microphone ready: {name}", "info")
        elif t == "transcript_partial":
            text = msg.get("text", "")
            self.partial_var.set(f"hearing: {text}…" if text else "")
        elif t == "transcript_final":
            self.partial_var.set("")
            text = str(msg.get("text", "")).strip()
            if text:
                self.ctx.history(text, "heard")
        elif t == "command_fired":
            cid = str(msg.get("id", ""))
            cmd = None
            try:
                cmd = self.ctx.commands.get(cid)
            except Exception:  # noqa: BLE001 - a store bug must not hide the event
                cmd = None
            label = (cmd or {}).get("label") or cid
            self.ctx.history(f"{label} [{cid}]" if label != cid else cid, "command")
        elif t == "no_match":
            self.ctx.history(f"No command matched: {msg.get('text', '')}", "warn")
        elif t == "log":
            level = msg.get("level", "info")
            self.ctx.history(str(msg.get("msg", "")), level if level in ("warn", "error") else "info")
        elif t == "system_action":
            op = msg.get("op", "")
            if op == "stop_listening":
                self.listening_var.set(False)
                self._refresh_state()
                self.ctx.history("Voice protocol stopped listening (voice command).", "info")
            elif op == "stop_speaking":
                self.ctx.history("Speech stopped.", "info")
            else:
                self.ctx.history(f"System action: {op}", "info")
        elif t == "config_reloaded":
            self.ctx.history(
                f"Commands reloaded: {msg.get('commands', '?')} commands, {msg.get('phrases', '?')} phrases.", "info")
        elif t == "hotkey_status":
            self._refresh_hotkey_hint()


PAGE_CLASS = VoicePage
