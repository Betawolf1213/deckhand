"""Page contract: each module sets PAGE_CLASS; touch widgets only on the Tk thread (ctx.run_bg)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------- commands


class CommandStoreLike(Protocol):
    """Implemented by services.command_store.CommandStore; dicts follow docs/COMMANDS.md."""

    def all(self) -> list[dict]:
        """Effective commands (defaults merged with user edits + custom), file order."""

    def get(self, command_id: str) -> dict | None: ...

    def categories(self) -> list[str]:
        """Distinct categories in display order (custom commands under 'Custom Phrases')."""

    def add_listener(self, fn: Callable[[], None]) -> None:
        """fn() is called (on the caller's thread) after every successful save."""


# theme: use ttk styles Title/Muted.TLabel, Accent.TButton, Card.TFrame; style_text() tk widgets


class ThemeLike(Protocol):
    colors: dict[str, str]  # keys: bg panel fg muted accent accent_fg entry_bg border good warn bad

    def style_text(self, widget: tk.Text) -> None: ...

    def style_listbox(self, widget: tk.Listbox) -> None: ...


# ---------------------------------------------------------------- app context


class AppContext(Protocol):
    root: tk.Tk
    commands: CommandStoreLike
    theme: ThemeLike
    settings: dict[str, Any]  # ui_settings.json dict; call save_settings() after edits

    def send(self, msg: dict) -> None:
        """Send one IPC message to the backend (docs/IPC.md). Silently dropped if disconnected."""

    def speak(self, text: str) -> None:
        """Speak through the backend TTS (speak_text)."""

    def history(self, text: str, kind: str = "info") -> None:
        """Append to the Voice page history. kind: info, heard, command, answer, warn, error."""

    def run_bg(self, fn: Callable[[], Any], on_done: Callable[[Any, Exception | None], None]) -> None: ...

    def show_page(self, name: str, payload: Any = None) -> None:
        """Switch to PAGE_ORDER page `name`; calls show_payload(payload) if payload is not None."""

    def save_settings(self) -> None: ...

    def reload_backend_commands(self) -> None:
        """Send reload_config so the backend picks up commands.json changes."""


# ---------------------------------------------------------------- pages


class Page(ttk.Frame):
    """Base class for pages. Override build(); optional hooks below."""

    title: str = "PAGE"  # shown in the page navigation

    def __init__(self, parent: tk.Misc, ctx: AppContext) -> None:
        super().__init__(parent, padding=10)
        self.ctx = ctx
        self.build()

    def build(self) -> None:  # create widgets here
        raise NotImplementedError

    def on_show(self) -> None:
        """Called each time the page becomes visible."""

    def on_backend_message(self, msg: dict) -> None:
        """Every backend message is offered to every page (cheap filters only)."""

    def show_payload(self, payload: Any) -> None:
        """Display data pushed by ctx.show_page (e.g. a spoken lookup's full result)."""


# ---------------------------------------------------------------- spoken questions


@dataclass
class Answer:
    """Result of services.questions.answer(). Computed on a worker thread."""

    speech: str                 # spoken via ctx.speak(); keep short (<= ~5 items)
    page: str | None = None     # PAGE_ORDER key to show the full result on, or None
    payload: Any = None         # passed to that page's show_payload()
    details: list[str] = field(default_factory=list)  # extra lines for the history panel

# services/questions.answer(text, commands) -> Answer | None; may block ~10 s, must never raise.
