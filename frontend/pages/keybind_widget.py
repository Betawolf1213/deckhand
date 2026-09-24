"""KeybindEditor/ActionEditor widgets for PHRASES/KEYBINDS/CUSTOM WORDS; keys use vk_map names."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

_SIDE_PREFIX = {"Left": "left ", "Right": "right ", "Standard": ""}
_MOD_WORDS = {
    "ctrl": ("ctrl", "Standard"), "control": ("ctrl", "Standard"),
    "left ctrl": ("ctrl", "Left"), "left control": ("ctrl", "Left"),
    "right ctrl": ("ctrl", "Right"), "right control": ("ctrl", "Right"),
    "alt": ("alt", "Standard"), "left alt": ("alt", "Left"), "right alt": ("alt", "Right"),
    "shift": ("shift", "Standard"), "left shift": ("shift", "Left"), "right shift": ("shift", "Right"),
}


def split_modifiers(keys: str) -> tuple[bool, bool, bool, str, str]:
    """-> (ctrl, alt, shift, side, base); side is Standard/Left/Right (first sided one wins)."""
    on = {"ctrl": False, "alt": False, "shift": False}
    side = "Standard"
    base: list[str] = []
    for raw in str(keys or "").lower().split("+"):
        part = " ".join(raw.split())
        if not part:
            continue
        hit = _MOD_WORDS.get(part)
        if hit:
            on[hit[0]] = True
            if side == "Standard" and hit[1] != "Standard":
                side = hit[1]
        else:
            base.append(part)
    return on["ctrl"], on["alt"], on["shift"], side, "+".join(base)


def apply_modifiers(keys: str, ctrl: bool, alt: bool, shift: bool, side: str) -> str:
    """Replace the modifiers of `keys`, keeping its base key."""
    *_, base = split_modifiers(keys)
    prefix = _SIDE_PREFIX.get(side, "")
    mods = [prefix + name for name, on in (("ctrl", ctrl), ("alt", alt), ("shift", shift)) if on]
    return "+".join(mods + ([base] if base else []))


# Windows virtual-key codes (Tk's event.keycode on Windows) -> key names.
_VK_NAMES = {
    0x08: "backspace", 0x09: "tab", 0x0C: "clear", 0x0D: "enter", 0x13: "pause",
    0x14: "capslock", 0x1B: "escape", 0x20: "space", 0x21: "pageup", 0x22: "pagedown",
    0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete", 0x5B: "lwin", 0x5C: "rwin",
    0x6A: "kp_multiply", 0x6B: "kp_add", 0x6D: "kp_subtract", 0x6E: "kp_decimal", 0x6F: "kp_divide",
    0xBA: "semicolon", 0xBB: "plus", 0xBC: "comma", 0xBD: "minus", 0xBE: "period",
    0xBF: "slash", 0xC0: "backtick", 0xDB: "lbracket", 0xDC: "backslash", 0xDD: "rbracket",
    0xDE: "apostrophe",
}
_VK_NAMES.update({0x30 + d: str(d) for d in range(10)})
_VK_NAMES.update({0x41 + i: chr(ord("a") + i) for i in range(26)})
_VK_NAMES.update({0x60 + d: f"numpad{d}" for d in range(10)})
_VK_NAMES.update({0x6F + n: f"f{n}" for n in range(1, 25)})

# Tk keysyms (modifiers need the keysym for their side; others are a fallback).
_KEYSYMS = {
    "shift_l": "left shift", "shift_r": "right shift",
    "control_l": "left ctrl", "control_r": "right ctrl",
    "alt_l": "left alt", "alt_r": "right alt", "meta_l": "left alt", "meta_r": "right alt",
    "return": "enter", "kp_enter": "enter", "escape": "escape", "backspace": "backspace",
    "tab": "tab", "space": "space", "prior": "pageup", "next": "pagedown", "end": "end",
    "home": "home", "left": "left", "up": "up", "right": "right", "down": "down",
    "insert": "insert", "delete": "delete", "print": "print_screen", "pause": "pause",
    "caps_lock": "capslock", "semicolon": "semicolon", "equal": "plus", "comma": "comma",
    "minus": "minus", "period": "period", "slash": "slash", "grave": "backtick",
    "bracketleft": "lbracket", "backslash": "backslash", "bracketright": "rbracket",
    "apostrophe": "apostrophe",
    "kp_multiply": "kp_multiply", "kp_add": "kp_add", "kp_subtract": "kp_subtract",
    "kp_divide": "kp_divide", "kp_decimal": "kp_decimal",
}
_KEYSYMS.update({f"kp_{d}": f"numpad{d}" for d in range(10)})
MODIFIER_NAMES = {"left shift", "right shift", "left ctrl", "right ctrl", "left alt", "right alt"}


def event_key_name(keysym: str, keycode: int) -> str | None:
    """Map a Tk key event to a key name, or None if it is not a key we can bind."""
    ks = str(keysym or "").lower()
    if ks in _KEYSYMS and (ks.startswith(("shift", "control", "alt", "meta"))):
        return _KEYSYMS[ks]
    if keycode in (0x10, 0x11, 0x12):  # generic modifier VK without a sided keysym
        return {0x10: "left shift", 0x11: "left ctrl", 0x12: "left alt"}[keycode]
    if keycode in _VK_NAMES:
        return _VK_NAMES[keycode]
    if ks in _KEYSYMS:
        return _KEYSYMS[ks]
    if len(ks) == 1 and (ks.isalnum()):
        return ks
    if len(ks) in (2, 3) and ks[0] == "f" and ks[1:].isdigit() and 1 <= int(ks[1:]) <= 24:
        return ks
    return None


class KeybindEditor(ttk.Frame):
    """Keybind entry with capture + modifier toggles. get()/set() the key string."""

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None] | None = None,
                 allow_base: bool = True) -> None:
        super().__init__(parent)
        self.on_change = on_change
        self.var = tk.StringVar()
        self.ctrl_var = tk.BooleanVar(value=False)
        self.alt_var = tk.BooleanVar(value=False)
        self.shift_var = tk.BooleanVar(value=False)
        self.side_var = tk.StringVar(value="Standard")
        self.capturing = False
        self._held: list[str] = []
        self._got_base = False

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.entry = ttk.Entry(row, textvariable=self.var, width=24)
        self.entry.pack(side="left", fill="x", expand=True)
        self.capture_btn = ttk.Button(row, text="CAPTURE", command=self.start_capture)
        self.capture_btn.pack(side="left", padx=(6, 0))
        self.var.trace_add("write", lambda *_: self._changed(sync=True))

        mods = ttk.Frame(self)
        mods.pack(fill="x", pady=(4, 0))
        ttk.Label(mods, text="MODIFIERS", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        for text, var in (("CTRL", self.ctrl_var), ("ALT", self.alt_var), ("SHIFT", self.shift_var)):
            ttk.Checkbutton(mods, text=text, variable=var,
                            command=self.apply_modifier_toggles).pack(side="left", padx=(0, 6))
        side = ttk.Combobox(mods, textvariable=self.side_var, values=["Standard", "Left", "Right"],
                            state="readonly", width=9)
        side.pack(side="left")
        side.bind("<<ComboboxSelected>>", lambda _e: self.apply_modifier_toggles())
        self.hint = ttk.Label(self, text="", style="Muted.TLabel")
        self.hint.pack(anchor="w")

        self.entry.bind("<KeyPress>", self._on_press)
        self.entry.bind("<KeyRelease>", self._on_release)
        self.entry.bind("<FocusOut>", lambda _e: self.stop_capture())

    # -------------------------------------------------------------- value

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, keys: str) -> None:
        self.var.set(keys or "")

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for w in self._all_children(self):
            try:
                if isinstance(w, ttk.Combobox):
                    w.configure(state="readonly" if enabled else "disabled")
                else:
                    w.configure(state=state)
            except tk.TclError:
                pass

    @staticmethod
    def _all_children(w: tk.Misc):
        for c in w.winfo_children():
            yield c
            yield from KeybindEditor._all_children(c)

    def apply_modifier_toggles(self) -> None:
        self.var.set(apply_modifiers(self.var.get(), self.ctrl_var.get(), self.alt_var.get(),
                                     self.shift_var.get(), self.side_var.get()))

    def _changed(self, sync: bool = False) -> None:
        if sync:
            ctrl, alt, shift, side, _ = split_modifiers(self.var.get())
            self.ctrl_var.set(ctrl)
            self.alt_var.set(alt)
            self.shift_var.set(shift)
            if ctrl or alt or shift:
                self.side_var.set(side)
        if self.on_change:
            self.on_change()

    # -------------------------------------------------------------- capture

    def start_capture(self) -> None:
        self.capturing = True
        self._held = []
        self._got_base = False
        self.hint.configure(text="Press the key combination now (Esc cancels)…")
        try:
            self.entry.focus_set()
        except tk.TclError:
            pass

    def stop_capture(self) -> None:
        self.capturing = False
        self._held = []
        self.hint.configure(text="")

    def feed_key(self, event, pressed: bool) -> None:
        """Handle one key event while capturing (bound to the entry; public for tests)."""
        if not self.capturing:
            return
        name = event_key_name(getattr(event, "keysym", ""), getattr(event, "keycode", 0))
        if name is None:
            return
        if pressed:
            if name in MODIFIER_NAMES:
                if name not in self._held:
                    self._held.append(name)
                return
            if name == "escape" and not self._held:
                self.stop_capture()
                return
            self.set("+".join(self._ordered(self._held) + [name]))
            self._got_base = True
            self.stop_capture()
        else:
            if name in MODIFIER_NAMES and not self._got_base:
                # modifier pressed and released alone -> bind the modifier(s) themselves
                self.set("+".join(self._ordered(self._held or [name])))
                self.stop_capture()

    @staticmethod
    def _ordered(mods: list[str]) -> list[str]:
        rank = {"ctrl": 0, "alt": 1, "shift": 2}
        return sorted(dict.fromkeys(mods), key=lambda m: rank[m.split()[-1]])

    def _on_press(self, event):
        if self.capturing:
            self.feed_key(event, pressed=True)
            return "break"
        return None

    def _on_release(self, event):
        if self.capturing:
            self.feed_key(event, pressed=False)
            return "break"
        return None


class ActionEditor(ttk.Frame):
    """Edits one action dict (docs/COMMANDS.md). get_action() raises ValueError on bad input."""

    TYPES = ("Tap", "Hold", "Mouse", "Scroll")

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(parent)
        self.on_change = on_change
        self.type_var = tk.StringVar(value="Tap")
        self.hold_var = tk.StringVar(value="1.0")
        self.button_var = tk.StringVar(value="left")
        self.direction_var = tk.StringVar(value="down")
        self._system: dict | None = None
        self._extra: dict = {}

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="ACTION TYPE", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.type_combo = ttk.Combobox(top, textvariable=self.type_var, values=list(self.TYPES),
                                       state="readonly", width=8)
        self.type_combo.pack(side="left")
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_type_changed())

        self.hold_frame = ttk.Frame(top)
        ttk.Label(self.hold_frame, text="HOLD SECONDS", style="Muted.TLabel").pack(side="left", padx=(10, 6))
        ttk.Spinbox(self.hold_frame, textvariable=self.hold_var, from_=0.1, to=60, increment=0.1,
                    width=6).pack(side="left")
        self.button_frame = ttk.Frame(top)
        ttk.Label(self.button_frame, text="BUTTON", style="Muted.TLabel").pack(side="left", padx=(10, 6))
        ttk.Combobox(self.button_frame, textvariable=self.button_var, state="readonly", width=7,
                     values=["left", "right", "middle", "x1", "x2"]).pack(side="left")
        self.dir_frame = ttk.Frame(top)
        ttk.Label(self.dir_frame, text="DIRECTION", style="Muted.TLabel").pack(side="left", padx=(10, 6))
        ttk.Combobox(self.dir_frame, textvariable=self.direction_var, state="readonly", width=6,
                     values=["up", "down"]).pack(side="left")

        self.keys_label = ttk.Label(self, text="KEYBIND", style="Muted.TLabel")
        self.keys_label.pack(anchor="w", pady=(6, 0))
        self.keys = KeybindEditor(self, on_change=self._changed)
        self.keys.pack(fill="x")
        self.system_label = ttk.Label(self, text="", style="Muted.TLabel", wraplength=420)

        for v in (self.hold_var, self.button_var, self.direction_var):
            v.trace_add("write", lambda *_: self._changed())
        self.on_type_changed()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    def on_type_changed(self) -> None:
        t = self.type_var.get()
        for f in (self.hold_frame, self.button_frame, self.dir_frame):
            f.pack_forget()
        self.system_label.pack_forget()
        if self._system is not None:
            self.type_combo.configure(state="disabled")
            self.keys_label.pack_forget()
            self.keys.pack_forget()
            self.system_label.configure(
                text=f"Built-in system action ({self._system.get('op')}); only its phrases can be edited.")
            self.system_label.pack(anchor="w", pady=(6, 0))
            self._changed()
            return
        self.type_combo.configure(state="readonly")
        if not self.keys.winfo_manager():
            self.keys_label.pack(anchor="w", pady=(6, 0))
            self.keys.pack(fill="x")
        if t == "Hold":
            self.hold_frame.pack(side="left")
        elif t == "Mouse":
            self.button_frame.pack(side="left")
        elif t == "Scroll":
            self.dir_frame.pack(side="left")
        self.keys_label.configure(text={"Mouse": "MODIFIERS HELD DURING CLICK (optional)",
                                        "Scroll": "KEYBIND (not used for scroll)"}.get(t, "KEYBIND"))
        self.keys.set_enabled(t != "Scroll")
        self._changed()

    def set_action(self, action: dict) -> None:
        action = dict(action or {})
        t = action.get("type", "tap")
        self._system = action if t == "system" else None
        self._extra = {}
        if t in ("tap", "press", "release"):
            self.type_var.set("Tap")
            if t != "tap":
                self._extra = {"type": t}
            self.keys.set(action.get("keys", ""))
        elif t == "hold":
            self.type_var.set("Hold")
            self.hold_var.set(f"{action.get('duration_ms', 1000) / 1000:g}")
            self.keys.set(action.get("keys", ""))
        elif t == "mouse":
            self.type_var.set("Mouse")
            self.button_var.set(action.get("button", "left"))
            self._extra = {"kind": action.get("kind", "click")}
            self.keys.set(action.get("keys", ""))
        elif t == "scroll":
            self.type_var.set("Scroll")
            self.direction_var.set(action.get("direction", "down"))
            self._extra = {"amount": action.get("amount", 1)}
            self.keys.set("")
        self.on_type_changed()

    def get_action(self) -> dict:
        if self._system is not None:
            return dict(self._system)
        t = self.type_var.get()
        keys = self.keys.get()
        if t == "Tap":
            return {"type": self._extra.get("type", "tap"), "keys": keys}
        if t == "Hold":
            try:
                secs = float(self.hold_var.get().replace(",", "."))
            except ValueError:
                raise ValueError("Hold seconds must be a number.") from None
            if not 0 < secs <= 60:
                raise ValueError("Hold seconds must be between 0 and 60.")
            return {"type": "hold", "keys": keys, "duration_ms": int(round(secs * 1000))}
        if t == "Mouse":
            out = {"type": "mouse", "button": self.button_var.get(), "kind": self._extra.get("kind", "click")}
            if keys:
                out["keys"] = keys
            return out
        if t == "Scroll":
            return {"type": "scroll", "direction": self.direction_var.get(),
                    "amount": int(self._extra.get("amount", 1))}
        raise ValueError(f"Unknown action type '{t}'.")


# ------------------------------------------------------------------ page helpers


def store_is_editable(store) -> bool:
    """True when ctx.commands is a real CommandStore (the pages are read-only otherwise)."""
    return all(hasattr(store, n) for n in ("save", "set_phrases", "set_action", "transaction"))


def report_error(page: tk.Misc, ctx, title: str, err: Exception | str) -> None:
    """Show a validation/save problem to the user and log it to the history panel."""
    from tkinter import messagebox

    msg = str(err)
    ctx.history(f"{title}: {msg}", "warn")
    messagebox.showerror(title, msg, parent=page)
