"""Colour themes: 6 presets plus persisted per-colour custom overrides, applied to ttk and tk."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

STATUS = {"good": "#4caf50", "warn": "#ffb300", "bad": "#e53935"}

_UPSTREAM = {
    # name: (bg, panel, panel2, border, text, muted, accent)
    "Midnight Blue": ("#0b0f14", "#111821", "#151f2b", "#263341", "#edf3f8", "#8493a3", "#4da3ff"),
    "Blackout": ("#050505", "#0d0d0d", "#151515", "#303030", "#f4f4f4", "#8e8e8e", "#ffffff"),
    "Purple Nebula": ("#0d0913", "#171021", "#21172f", "#3a2851", "#f4edff", "#9d8caf", "#a970ff"),
    "Cyan": ("#061014", "#0b1b22", "#102831", "#204452", "#ebfbff", "#82a7b0", "#34d7ff"),
    "Industrial Orange": ("#120d08", "#1c150e", "#291e13", "#4b3824", "#fff4e8", "#ad9984", "#ffad42"),
    "Danger Red": ("#110809", "#1d0f11", "#2a1518", "#512b30", "#fff1f2", "#b08d91", "#ff5d6c"),
}

DEFAULT_PRESET = "Industrial Orange"
CUSTOM_NAME = "Custom"

# Colours the CUSTOMIZE page lets the user pick (key, label).
EDITABLE: list[tuple[str, str]] = [
    ("bg", "BACKGROUND"),
    ("panel", "PANEL"),
    ("entry_bg", "SECONDARY PANEL"),
    ("border", "BORDER"),
    ("fg", "TEXT"),
    ("muted", "MUTED TEXT"),
    ("accent", "ACCENT"),
    ("good", "GOOD / OK"),
    ("warn", "WARNING"),
    ("bad", "ERROR"),
]

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def accent_text_color(color: str) -> str:
    """Readable text colour for a button filled with `color`."""
    c = normalize_hex(color) or "#ffffff"
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    return "#130d08" if brightness >= 145 else "#ffffff"


def normalize_hex(value: Any) -> str | None:
    """'#ABC' / 'abcdef' -> '#aabbcc'; anything else -> None."""
    if not isinstance(value, str):
        return None
    m = _HEX.match(value.strip())
    if not m:
        return None
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h


def _preset(values: tuple[str, ...]) -> dict[str, str]:
    bg, panel, panel2, border, text, muted, accent = values
    return {
        "bg": bg, "panel": panel, "fg": text, "muted": muted,
        "accent": accent, "accent_fg": accent_text_color(accent),
        "entry_bg": panel2, "border": border, **STATUS,
    }


PRESETS: dict[str, dict[str, str]] = {name: _preset(v) for name, v in _UPSTREAM.items()}


def _parts(settings: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(settings, dict):
        return DEFAULT_PRESET, {}
    preset = settings.get("preset")
    if preset not in PRESETS:
        preset = DEFAULT_PRESET
    custom: dict[str, str] = {}
    raw = settings.get("custom")
    if isinstance(raw, dict):
        for k, v in raw.items():
            h = normalize_hex(v)
            if k in PRESETS[DEFAULT_PRESET] and h:
                custom[k] = h
    return preset, custom


def resolve(settings: Any) -> dict[str, str]:
    """Effective colour dict for persisted theme settings (never raises)."""
    preset, custom = _parts(settings)
    colors = dict(PRESETS[preset])
    colors.update(custom)
    if "accent" in custom and "accent_fg" not in custom:
        colors["accent_fg"] = accent_text_color(colors["accent"])
    return colors


def display_name(settings: Any) -> str:
    preset, custom = _parts(settings)
    return CUSTOM_NAME if custom else preset


def with_preset(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(f"unknown theme preset: {name}")
    return {"preset": name, "custom": {}}


def with_color(settings: Any, key: str, color: str) -> dict:
    h = normalize_hex(color)
    if h is None or key not in PRESETS[DEFAULT_PRESET]:
        raise ValueError(f"invalid colour {key}={color!r}")
    preset, custom = _parts(settings)
    return {"preset": preset, "custom": {**custom, key: h}}


class Theme:
    """ThemeLike implementation: owns the colours and restyles ttk + registered tk widgets."""

    FONT = ("Segoe UI", 10)

    def __init__(self, root: tk.Misc, settings: Any = None) -> None:
        self.root = root
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")  # the only built-in theme that honours colours
        except tk.TclError:
            pass
        self._texts: list[tk.Misc] = []
        self._listboxes: list[tk.Misc] = []
        self._listeners: list[Callable[[], None]] = []
        self.settings: dict = {}
        self.colors: dict[str, str] = {}
        self.load(settings)

    # ---- public API ----
    @property
    def name(self) -> str:
        return display_name(self.settings)

    def load(self, settings: Any) -> None:
        preset, custom = _parts(settings)
        self.settings = {"preset": preset, "custom": dict(custom)}
        self.colors = resolve(self.settings)
        self.apply()

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def style_text(self, widget: tk.Misc) -> None:
        if widget not in self._texts:
            self._texts.append(widget)
        self._style_text(widget)

    def style_listbox(self, widget: tk.Misc) -> None:
        if widget not in self._listboxes:
            self._listboxes.append(widget)
        self._style_listbox(widget)

    # ---- application ----
    def apply(self) -> None:
        self._configure_ttk()
        self._texts = [w for w in self._texts if self._alive(w)]
        self._listboxes = [w for w in self._listboxes if self._alive(w)]
        for w in self._texts:
            self._style_text(w)
            try:
                w.event_generate("<<DeckhandTheme>>")
            except tk.TclError:
                pass
        for w in self._listboxes:
            self._style_listbox(w)
        try:
            self.root.configure(background=self.colors["bg"])
        except tk.TclError:
            pass
        for fn in list(self._listeners):
            fn()

    @staticmethod
    def _alive(w: tk.Misc) -> bool:
        try:
            return bool(w.winfo_exists())
        except tk.TclError:
            return False

    def _style_text(self, w: tk.Misc) -> None:
        c = self.colors
        try:
            w.configure(background=c["entry_bg"], foreground=c["fg"], insertbackground=c["fg"],
                        selectbackground=c["border"], selectforeground=c["fg"],
                        highlightbackground=c["border"], highlightcolor=c["accent"],
                        highlightthickness=1, relief="flat", borderwidth=0)
        except tk.TclError:
            pass  # a Canvas/Label registered as "text": best effort

    def _style_listbox(self, w: tk.Misc) -> None:
        c = self.colors
        try:
            w.configure(background=c["entry_bg"], foreground=c["fg"],
                        selectbackground=c["accent"], selectforeground=c["accent_fg"],
                        highlightbackground=c["border"], highlightcolor=c["accent"],
                        highlightthickness=1, relief="flat", borderwidth=0,
                        activestyle="none")
        except tk.TclError:
            pass

    def _configure_ttk(self) -> None:
        c = self.colors
        s = self.style
        bg, panel, fg, muted = c["bg"], c["panel"], c["fg"], c["muted"]
        accent, accent_fg, entry, border = c["accent"], c["accent_fg"], c["entry_bg"], c["border"]
        font = self.FONT

        s.configure(".", background=bg, foreground=fg, fieldbackground=entry, bordercolor=border,
                    lightcolor=panel, darkcolor=panel, troughcolor=panel, selectbackground=accent,
                    selectforeground=accent_fg, insertcolor=fg, font=font)
        s.map(".", foreground=[("disabled", muted)])
        s.configure("TFrame", background=bg)
        s.configure("TLabel", background=bg, foreground=fg)
        s.configure("Title.TLabel", background=bg, foreground=accent, font=("Segoe UI", 16, "bold"))
        s.configure("Heading.TLabel", background=bg, foreground=fg, font=("Segoe UI", 11, "bold"))
        s.configure("Muted.TLabel", background=bg, foreground=muted)
        s.configure("Good.TLabel", background=bg, foreground=c["good"])
        s.configure("Warn.TLabel", background=bg, foreground=c["warn"])
        s.configure("Bad.TLabel", background=bg, foreground=c["bad"])
        s.configure("Status.TLabel", background=bg, foreground=accent, font=("Segoe UI", 14, "bold"))

        s.configure("Card.TFrame", background=bg, bordercolor=border, relief="solid", borderwidth=1)
        s.configure("Card.TLabelframe", background=bg, bordercolor=border, lightcolor=border,
                    darkcolor=border, relief="solid", borderwidth=1)
        s.configure("Card.TLabelframe.Label", background=bg, foreground=accent,
                    font=("Segoe UI", 9, "bold"))
        s.configure("TLabelframe", background=bg, bordercolor=border)
        s.configure("TLabelframe.Label", background=bg, foreground=accent)

        s.configure("TButton", background=entry, foreground=fg, bordercolor=border,
                    lightcolor=entry, darkcolor=entry, focuscolor=accent, padding=(10, 4))
        s.map("TButton", background=[("pressed", border), ("active", border)],
              foreground=[("disabled", muted)])
        s.configure("Accent.TButton", background=accent, foreground=accent_fg, bordercolor=accent,
                    lightcolor=accent, darkcolor=accent, font=("Segoe UI", 10, "bold"))
        s.map("Accent.TButton", background=[("pressed", border), ("active", accent)],
              foreground=[("pressed", fg), ("active", accent_fg)])
        s.configure("Danger.TButton", background=c["bad"], foreground="#ffffff",
                    bordercolor=c["bad"], lightcolor=c["bad"], darkcolor=c["bad"],
                    font=("Segoe UI", 10, "bold"))
        s.map("Danger.TButton", background=[("active", c["bad"])])

        # Page navigation (sidebar) buttons.
        s.configure("Nav.TButton", background=panel, foreground=fg, bordercolor=bg,
                    lightcolor=panel, darkcolor=panel, anchor="w", padding=(12, 5),
                    font=("Segoe UI", 9, "bold"))
        s.map("Nav.TButton", background=[("active", border)])
        s.configure("NavActive.TButton", background=accent, foreground=accent_fg, bordercolor=accent,
                    lightcolor=accent, darkcolor=accent, anchor="w", padding=(12, 5),
                    font=("Segoe UI", 9, "bold"))
        s.map("NavActive.TButton", background=[("active", accent)])
        s.configure("Sidebar.TFrame", background=panel)
        s.configure("Header.TFrame", background=panel)
        s.configure("Header.TLabel", background=panel, foreground=fg)
        s.configure("HeaderTitle.TLabel", background=panel, foreground=accent,
                    font=("Segoe UI", 13, "bold"))
        s.configure("HeaderMuted.TLabel", background=panel, foreground=muted)
        s.configure("HeaderGood.TLabel", background=panel, foreground=c["good"], font=("Segoe UI", 9, "bold"))
        s.configure("HeaderBad.TLabel", background=panel, foreground=c["bad"], font=("Segoe UI", 9, "bold"))
        s.configure("HeaderAccent.TLabel", background=panel, foreground=accent, font=("Segoe UI", 9, "bold"))

        for w in ("TCheckbutton", "TRadiobutton"):
            s.configure(w, background=bg, foreground=fg, indicatorbackground=entry,
                        indicatorforeground=accent, focuscolor=bg)
            s.map(w, background=[("active", bg)],
                  indicatorbackground=[("selected", entry), ("active", entry)])
        s.configure("TEntry", fieldbackground=entry, foreground=fg, bordercolor=border,
                    lightcolor=border, darkcolor=border, insertcolor=fg)
        s.map("TEntry", bordercolor=[("focus", accent)], lightcolor=[("focus", accent)])
        s.configure("TCombobox", fieldbackground=entry, background=entry, foreground=fg,
                    arrowcolor=fg, bordercolor=border, lightcolor=border, darkcolor=border)
        s.map("TCombobox", fieldbackground=[("readonly", entry)], foreground=[("readonly", fg)],
              selectbackground=[("readonly", entry)], selectforeground=[("readonly", fg)],
              background=[("active", border)])
        s.configure("TSpinbox", fieldbackground=entry, background=entry, foreground=fg,
                    arrowcolor=fg, bordercolor=border)
        s.configure("Treeview", background=entry, fieldbackground=entry, foreground=fg,
                    bordercolor=border, rowheight=22)
        s.map("Treeview", background=[("selected", accent)], foreground=[("selected", accent_fg)])
        s.configure("Treeview.Heading", background=panel, foreground=fg, bordercolor=border,
                    lightcolor=panel, darkcolor=panel, font=("Segoe UI", 9, "bold"))
        s.map("Treeview.Heading", background=[("active", border)])
        s.configure("TNotebook", background=bg, bordercolor=border)
        s.configure("TNotebook.Tab", background=panel, foreground=fg, bordercolor=border,
                    lightcolor=panel, padding=(10, 4))
        s.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", accent_fg)])
        s.configure("Horizontal.TProgressbar", background=accent, troughcolor=entry,
                    bordercolor=border, lightcolor=accent, darkcolor=accent)
        s.configure("TScale", background=accent, troughcolor=entry, bordercolor=border,
                    lightcolor=accent, darkcolor=accent)
        s.configure("TScrollbar", background=panel, troughcolor=bg, bordercolor=border,
                    arrowcolor=fg, lightcolor=panel, darkcolor=panel)
        s.map("TScrollbar", background=[("active", border)])
        s.configure("TPanedwindow", background=bg)
        s.configure("TSeparator", background=border)

        # Combobox drop-down lists are plain tk Listboxes.
        opt = self.root.option_add
        opt("*TCombobox*Listbox.background", entry)
        opt("*TCombobox*Listbox.foreground", fg)
        opt("*TCombobox*Listbox.selectBackground", accent)
        opt("*TCombobox*Listbox.selectForeground", accent_fg)
