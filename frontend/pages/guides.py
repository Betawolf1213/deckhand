"""GUIDES page (and LinkPage, the shared 'text + open in browser' layout)."""
from __future__ import annotations

import webbrowser
from tkinter import ttk

from app_paths import GUIDES_URL
from pages.base import Page


class LinkPage(Page):
    """Heading, a short description and one button that opens `url` in the browser."""

    title = "LINK"
    heading = "LINK"
    description = ""
    button_text = "OPEN"
    url = ""

    def build(self) -> None:
        ttk.Label(self, text=self.heading, style="Title.TLabel").pack(anchor="w")
        card = ttk.LabelFrame(self, text=self.title, style="Card.TLabelframe", padding=18)
        card.pack(fill="x", pady=(10, 0))
        self.desc = ttk.Label(card, text=self.description, wraplength=640, justify="left")
        self.desc.pack(anchor="w", pady=(0, 14))
        ttk.Button(card, text=self.button_text, style="Accent.TButton", command=self.open_link).pack(anchor="w")
        ttk.Label(card, text=self.url, style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(10, 0))

    def open_link(self) -> None:
        try:
            webbrowser.open_new_tab(self.url)
        except Exception as e:  # noqa: BLE001 - browser launch failures are user-visible, not fatal
            self.ctx.history(f"Could not open {self.url}: {e}", "error")


class GuidesPage(LinkPage):
    title = "GUIDES"
    heading = "GUIDES"
    description = ("Community guides for Star Citizen on the Star Citizen Wiki — getting started, ship systems, "
                   "mining, trading and more. Opens in your web browser.")
    button_text = "OPEN STAR CITIZEN GUIDES"
    url = GUIDES_URL


PAGE_CLASS = GuidesPage
