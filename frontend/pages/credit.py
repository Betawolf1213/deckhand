"""CREDIT page: version, credits, technology and data sources."""
from __future__ import annotations

import webbrowser
from tkinter import ttk

from app_paths import ANNOUNCEMENTS_URL, APP_NAME, APP_VERSION, UPSTREAM_URL
from pages.base import Page

TECH = [
    ("Zig", "voice backend: audio capture, recognition, key presses (SendInput) and the listening hotkey"),
    ("Vosk", "offline speech recognition — nothing you say leaves your PC"),
    ("Windows SAPI", "spoken replies and command confirmations"),
    ("Python + Tkinter", "this window, lookups and settings"),
]

SOURCES = [
    ("UEX", "Commodity prices and trading locations", "https://uexcorp.space/"),
    ("STAR CITIZEN WIKI", "Ship components, ship weapons, ships and mining data", "https://starcitizen.tools/"),
    ("RSI SPECTRUM", "Official Star Citizen announcements", ANNOUNCEMENTS_URL),
]


class CreditPage(Page):
    title = "CREDIT"

    def build(self) -> None:
        ttk.Label(self, text="CREDIT", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text=f"{APP_NAME} · version {APP_VERSION}", style="Muted.TLabel").pack(anchor="w")

        orig = ttk.LabelFrame(self, text="ACKNOWLEDGEMENT", style="Card.TLabelframe", padding=12)
        orig.pack(fill="x", pady=(10, 0))
        ttk.Label(orig, wraplength=760, justify="left",
                  text=("Deckhand is an independent rewrite with its own native voice engine. Its default "
                        "phrases and mining tables come from the original Kabutopz Voice Protocol by "
                        "Kabutopzzz; thanks to its author and contributors.")).pack(anchor="w")
        ttk.Button(orig, text="ORIGINAL PROJECT",
                   command=lambda: self.open(UPSTREAM_URL)).pack(anchor="w", pady=(8, 0))

        tech = ttk.LabelFrame(self, text="BUILT WITH", style="Card.TLabelframe", padding=12)
        tech.pack(fill="x", pady=(10, 0))
        for name, what in TECH:
            row = ttk.Frame(tech)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=name, style="Heading.TLabel", width=18).pack(side="left")
            ttk.Label(row, text=what, style="Muted.TLabel", wraplength=560, justify="left").pack(side="left")

        src = ttk.LabelFrame(self, text="DATA SOURCES", style="Card.TLabelframe", padding=12)
        src.pack(fill="x", pady=(10, 0))
        ttk.Label(src, wraplength=760, justify="left", style="Muted.TLabel",
                  text=("The lookup pages show public community and official data. Credit belongs to the "
                        "people behind these sources:")).pack(anchor="w", pady=(0, 6))
        for name, what, url in SOURCES:
            row = ttk.Frame(src)
            row.pack(fill="x", pady=2)
            ttk.Button(row, text=f"OPEN {name}", width=24, command=lambda u=url: self.open(u)).pack(side="left")
            ttk.Label(row, text=what, style="Muted.TLabel").pack(side="left", padx=8)
        ttk.Label(src, wraplength=760, justify="left", style="Muted.TLabel",
                  text=("Data can change or be incomplete — check important prices at the source. Not affiliated "
                        "with or endorsed by Cloud Imperium Games or the sites listed; their names and content "
                        "belong to their owners.")).pack(anchor="w", pady=(8, 0))

    def open(self, url: str) -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception as e:  # noqa: BLE001
            self.ctx.history(f"Could not open {url}: {e}", "error")


PAGE_CLASS = CreditPage
