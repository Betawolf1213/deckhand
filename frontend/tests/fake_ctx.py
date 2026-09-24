"""AppContext test double for page smoke tests; run_bg runs synchronously for determinism."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_COLORS = {
    "bg": "#101418", "panel": "#171d24", "fg": "#e6e6e6", "muted": "#8a939c",
    "accent": "#ff8a1f", "accent_fg": "#101418", "entry_bg": "#0c1014",
    "border": "#2a323b", "good": "#4caf50", "warn": "#ffb300", "bad": "#e53935",
}


class FakeTheme:
    def __init__(self) -> None:
        self.colors = dict(DEFAULT_COLORS)
        self.styled: list[Any] = []

    def style_text(self, widget) -> None:
        self.styled.append(widget)

    def style_listbox(self, widget) -> None:
        self.styled.append(widget)


class FakeCommands:
    """Minimal CommandStoreLike over a plain list of command dicts."""

    def __init__(self, commands: list[dict] | None = None) -> None:
        self._commands = list(commands or [])
        self._listeners: list[Callable[[], None]] = []

    def all(self) -> list[dict]:
        return list(self._commands)

    def get(self, command_id: str) -> dict | None:
        return next((c for c in self._commands if c.get("id") == command_id), None)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for c in self._commands:
            cat = "Custom Phrases" if c.get("custom") else c.get("category", "Other")
            if cat not in seen:
                seen.append(cat)
        return seen

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)


class FakeContext:
    def __init__(self, root, commands: Any = None, settings: dict | None = None) -> None:
        self.root = root
        self.commands = commands if hasattr(commands, "all") else FakeCommands(commands)
        self.theme = FakeTheme()
        self.settings: dict[str, Any] = settings if settings is not None else {}
        self.sent: list[dict] = []
        self.spoken: list[str] = []
        self.hist: list[tuple[str, str]] = []
        self.shown: list[tuple[str, Any]] = []
        self.saves = 0
        self.reloads = 0

    def send(self, msg: dict) -> None:
        self.sent.append(msg)

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def history(self, text: str, kind: str = "info") -> None:
        self.hist.append((kind, text))

    def run_bg(self, fn, on_done) -> None:
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - mirror the real contract
            on_done(None, e)
            return
        on_done(result, None)

    def show_page(self, name: str, payload: Any = None) -> None:
        self.shown.append((name, payload))

    def save_settings(self) -> None:
        self.saves += 1

    def reload_backend_commands(self) -> None:
        self.reloads += 1
