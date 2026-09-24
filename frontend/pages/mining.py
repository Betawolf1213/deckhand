"""MINING MODE page: signatures, reverse signature lookup, live mining locations (wiki/fallback)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Any

from pages.base import Page
from services import mining_data, scwiki


def parse_signature(text: str) -> int | None:
    """'8,540' / '8540' / 'eight thousand five hundred forty' -> int, else None."""
    digits = re.findall(r"\d[\d,]*", text or "")
    if digits:
        try:
            return int(digits[-1].replace(",", ""))
        except ValueError:
            return None
    words = scwiki.spoken_numbers(text or "")
    return words[-1] if words else None


class MiningPage(Page):
    title = "MINING MODE"

    def build(self) -> None:
        self.location_result: scwiki.MiningResult | None = None
        ttk.Label(self, text="MINING MODE", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, style="Muted.TLabel", wraplength=900, justify="left", text=(
            "Signature = rock count x the mineral's 1x value. Voice: \"what resource is four thousand "
            "two hundred seventy\" identifies a scan; \"where can I mine iron\" lists mining bodies."
        )).pack(anchor="w", pady=(2, 8))

        top = ttk.Frame(self)
        top.pack(fill="x")

        # ---- signatures for one mineral
        sig = ttk.LabelFrame(top, text="SIGNATURES", style="Card.TLabelframe", padding=8)
        sig.pack(side="left", fill="both", expand=True, padx=(0, 6))
        row = ttk.Frame(sig)
        row.pack(fill="x")
        self.ore_var = tk.StringVar(value="iron")
        combo = ttk.Combobox(row, textvariable=self.ore_var, values=mining_data.MINING_DISPLAY_ORDER,
                             state="readonly", width=16)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_values())
        ttk.Button(row, text="READ SIGNATURES", style="Accent.TButton",
                   command=self.speak_signatures).pack(side="left", padx=(8, 0))
        self.values_var = tk.StringVar()
        ttk.Label(sig, textvariable=self.values_var, style="Muted.TLabel", wraplength=420,
                  justify="left").pack(anchor="w", pady=(6, 0))
        self._update_values()

        # ---- reverse signature lookup
        rev = ttk.LabelFrame(top, text="REVERSE SIGNATURE LOOKUP", style="Card.TLabelframe", padding=8)
        rev.pack(side="left", fill="both", expand=True, padx=(6, 0))
        row = ttk.Frame(rev)
        row.pack(fill="x")
        self.signature_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.signature_var, width=14)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self.reverse_lookup())
        ttk.Button(row, text="IDENTIFY", style="Accent.TButton",
                   command=self.reverse_lookup).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="SPEAK", command=self.speak_reverse).pack(side="left", padx=(6, 0))
        self.reverse_var = tk.StringVar(value="Enter a scanner signature, e.g. 8,540.")
        ttk.Label(rev, textvariable=self.reverse_var, wraplength=420, justify="left").pack(anchor="w", pady=(6, 2))
        self.reverse_table = tk.Text(rev, height=5, width=48, wrap="none", state="disabled")
        self.ctx.theme.style_text(self.reverse_table)
        self.reverse_table.pack(fill="x")

        # ---- live locations
        loc = ttk.LabelFrame(self, text="WHERE CAN I MINE THIS?", style="Card.TLabelframe", padding=8)
        loc.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(loc)
        row.pack(fill="x")
        self.location_var = tk.StringVar(value="iron")
        entry = ttk.Entry(row, textvariable=self.location_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.find_locations())
        ttk.Button(row, text="FIND LOCATIONS", style="Accent.TButton",
                   command=self.find_locations).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="SPEAK", command=self.speak_locations).pack(side="left", padx=(6, 0))
        self.location_status = tk.StringVar(value="Reads every listed mining body on the Star Citizen Wiki, "
                                                  "including all Stanton results.")
        ttk.Label(loc, textvariable=self.location_status, style="Muted.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(4, 4))
        frame = ttk.Frame(loc)
        frame.pack(fill="x")
        self.locations = tk.Text(frame, height=7, wrap="none", state="disabled")
        self.ctx.theme.style_text(self.locations)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.locations.yview)
        self.locations.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.locations.pack(side="left", fill="both", expand=True)

        # ---- full table
        tbl = ttk.LabelFrame(self, text="SIGNATURE TABLE (1x – 10x rocks)", style="Card.TLabelframe", padding=8)
        tbl.pack(fill="both", expand=True, pady=(8, 0))
        self.table = tk.Text(tbl, height=12, wrap="none")
        self.ctx.theme.style_text(self.table)
        tscroll = ttk.Scrollbar(tbl, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=tscroll.set)
        tscroll.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self._set(self.table, mining_data.table_lines())

    # ---- helpers

    @staticmethod
    def _set(widget: tk.Text, lines: list[str]) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))
        widget.configure(state="disabled")

    def _selected_ore(self) -> str:
        ore = mining_data.normalize_ore(self.ore_var.get()) or "iron"
        return ore

    def _update_values(self) -> None:
        ore = self._selected_ore()
        self.values_var.set("  ".join(f"{i}x {v:,}" for i, v in enumerate(mining_data.signature_values(ore), 1)))

    # ---- signatures

    def speak_signatures(self) -> None:
        ore = self._selected_ore()
        self.ctx.speak(mining_data.signature_speech(ore))
        self.ctx.history(f"Mining signatures requested for {ore.title()}.")

    # ---- reverse lookup

    def reverse_lookup(self) -> None:
        sig = parse_signature(self.signature_var.get())
        if sig is None or sig <= 0:
            self.reverse_var.set("Enter a scanner signature number, e.g. 8,540.")
            self._set(self.reverse_table, [])
            return
        self.show_reverse(mining_data.reverse_lookup(sig))

    def show_reverse(self, result: mining_data.ReverseResult) -> None:
        self.reverse_result = result
        self.signature_var.set(f"{result.signature:,}")
        self.reverse_var.set(result.speech())
        rows = [f"{'MATCH':<22}{'SIGNATURE':>10}{'OFF BY':>9}"]
        rows += [f"{m.label():<22}{m.value:>10,}{m.diff:>9,}" for m in result.candidates(5)]
        self._set(self.reverse_table, rows)

    def speak_reverse(self) -> None:
        if getattr(self, "reverse_result", None) is None:
            self.reverse_lookup()
        if getattr(self, "reverse_result", None) is not None:
            self.ctx.speak(self.reverse_result.speech())

    # ---- live locations

    def find_locations(self) -> None:
        resource = self.location_var.get().strip()
        if not resource:
            self.location_status.set("Enter a mineral name first.")
            return
        self.location_status.set(f"Searching all listed mining locations for {resource}…")
        self.ctx.run_bg(lambda: scwiki.lookup_mining_locations(resource),
                        lambda res, err: self._on_locations(resource, res, err))

    def _on_locations(self, resource: str, result: scwiki.MiningResult | None, err: Exception | None) -> None:
        if err is not None:
            self.location_result = None
            self.location_status.set(f"Lookup failed: {err}")
            self._set(self.locations, [f"I could not find mining locations for {resource}."])
            return
        self.show_locations(result)

    def show_locations(self, result: scwiki.MiningResult) -> None:
        self.location_result = result
        self.location_var.set(result.resource)
        if result.offline:
            self.location_status.set(f"OFFLINE — {result.note or 'Live lookup failed.'} "
                                     f"Showing the saved {result.resource} hotspot list.")
            self._set(self.locations, [f"Known {result.resource} hotspots (saved list):"] + result.lines())
        else:
            self.location_status.set(f"{result.resource}: {len(result.locations)} listed mining location(s) — "
                                     f"{result.url}")
            self._set(self.locations, result.lines())

    def speak_locations(self) -> None:
        if self.location_result is not None:
            self.ctx.speak(scwiki.mining_speech(self.location_result))
        else:
            self.location_status.set("Find locations first.")

    # ---- payloads from spoken questions

    def show_payload(self, payload: Any) -> None:
        if isinstance(payload, mining_data.ReverseResult):
            self.show_reverse(payload)
        elif isinstance(payload, scwiki.MiningResult):
            self.show_locations(payload)
        elif isinstance(payload, int):
            self.show_reverse(mining_data.reverse_lookup(payload))
        elif isinstance(payload, str) and payload.strip():
            self.location_var.set(payload)
            self.find_locations()


PAGE_CLASS = MiningPage
