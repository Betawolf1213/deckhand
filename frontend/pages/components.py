"""COMPONENTS page + shared LookupPage (subclasses: suggest/lookup/render/speech)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from pages.base import Page
from services import scwiki

DEBOUNCE_MS = 300


class LookupPage(Page):
    title = "LOOKUP"
    heading = "LOOKUP"
    description = ""
    hint = ""
    button_text = "SEARCH"
    default_query = ""
    min_suggest_chars = 2
    result_types: tuple[type, ...] = ()

    # ---- subclass hooks (suggest/lookup run on a worker thread)

    def suggest(self, query: str) -> list[str]:
        return []

    def lookup(self, query: str) -> Any:
        raise NotImplementedError

    def render(self, result: Any) -> list[str]:
        return [str(result)]

    def speech(self, result: Any) -> str:
        return ""

    def status_for(self, result: Any) -> str:
        return "Loaded."

    def query_for(self, result: Any) -> str:
        return str(getattr(result, "name", "") or "")

    # ---- layout

    def build(self) -> None:
        self.result: Any = None
        self._suggest_job: str | None = None
        ttk.Label(self, text=self.heading, style="Title.TLabel").pack(anchor="w")
        if self.description:
            ttk.Label(self, text=self.description, style="Muted.TLabel", wraplength=900,
                      justify="left").pack(anchor="w", pady=(2, 8))
        self.build_notice()

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.search_var = tk.StringVar(value=self.default_query)
        self.entry = ttk.Entry(row, textvariable=self.search_var)
        self.entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Return>", lambda _e: self.search())
        self.entry.bind("<Down>", lambda _e: self._focus_suggestions())
        ttk.Button(row, text=self.button_text, style="Accent.TButton",
                   command=self.search).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="SPEAK", command=self.speak_result).pack(side="left", padx=(6, 0))

        self.suggestions = tk.Listbox(self, height=6, activestyle="none", exportselection=False)
        self.ctx.theme.style_listbox(self.suggestions)
        self.suggestions.bind("<<ListboxSelect>>", lambda _e: self._on_suggestion_selected())
        self.suggestions.bind("<Return>", lambda _e: self._on_suggestion_selected())

        self.status_var = tk.StringVar(value=self.hint)
        self.status = ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel",
                                wraplength=900, justify="left")
        self.status.pack(anchor="w", pady=(6, 6))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.results = tk.Text(frame, wrap="none", height=18, state="disabled")
        self.ctx.theme.style_text(self.results)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.results.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.results.xview)
        self.results.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.results.pack(side="left", fill="both", expand=True)

    def build_notice(self) -> None:
        """Optional extra widgets under the description (e.g. an API-key notice)."""

    # ---- suggestions

    def _on_key(self, event: tk.Event) -> None:
        if event.keysym in ("Return", "Down", "Up", "Escape"):
            if event.keysym == "Escape":
                self._hide_suggestions()
            return
        self._on_typed()

    def _on_typed(self) -> None:
        if self._suggest_job is not None:
            self.after_cancel(self._suggest_job)
            self._suggest_job = None
        if len(self.search_var.get().strip()) < self.min_suggest_chars:
            self._hide_suggestions()
            return
        self._suggest_job = self.after(DEBOUNCE_MS, self._suggest_now)

    def _suggest_now(self) -> None:
        if self._suggest_job is not None:
            self.after_cancel(self._suggest_job)
            self._suggest_job = None
        query = self.search_var.get().strip()
        if len(query) < self.min_suggest_chars:
            return
        self.ctx.run_bg(lambda: self.suggest(query),
                        lambda res, err: self._show_suggestions(query, res, err))

    def _show_suggestions(self, query: str, names: list[str] | None, err: Exception | None) -> None:
        if query != self.search_var.get().strip():
            return  # stale: the user kept typing
        self.suggestions.delete(0, "end")
        for name in (names or [])[:10]:
            self.suggestions.insert("end", name)
        if names and not err:
            self.suggestions.pack(fill="x", pady=(4, 0), before=self.status)
        else:
            self._hide_suggestions()

    def _hide_suggestions(self) -> None:
        self.suggestions.pack_forget()

    def _focus_suggestions(self) -> None:
        if self.suggestions.size():
            self.suggestions.focus_set()
            self.suggestions.selection_set(0)

    def _on_suggestion_selected(self) -> None:
        sel = self.suggestions.curselection()
        if not sel:
            return
        self.search_var.set(self.suggestions.get(sel[0]))
        self._hide_suggestions()
        self.search()

    # ---- search / display

    def search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            self.status_var.set("Enter a name first.")
            return
        if self._suggest_job is not None:
            self.after_cancel(self._suggest_job)
            self._suggest_job = None
        self._hide_suggestions()
        self.status_var.set(f"Searching for {query}…")
        self.ctx.run_bg(lambda: self.lookup(query), lambda res, err: self._on_result(query, res, err))

    def _on_result(self, query: str, result: Any, err: Exception | None) -> None:
        if err is not None:
            self.status_var.set(f"Lookup failed: {err}")
            self.set_text([f"Lookup failed for \"{query}\":", str(err)])
            return
        self.show_result(result)

    def show_result(self, result: Any) -> None:
        self.result = result
        self.set_text(self.render(result))
        self.status_var.set(self.status_for(result))
        name = self.query_for(result)
        if name:
            self.search_var.set(name)
        self._hide_suggestions()

    def set_text(self, lines: list[str]) -> None:
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", "\n".join(lines))
        self.results.configure(state="disabled")

    def speak_result(self) -> None:
        if self.result is None:
            self.status_var.set("Search for something first.")
            return
        text = self.speech(self.result)
        if text:
            self.ctx.speak(text)

    def show_payload(self, payload: Any) -> None:
        if isinstance(payload, str):
            self.search_var.set(payload)
            self.search()
        elif self.result_types and isinstance(payload, self.result_types):
            self.show_result(payload)


class ComponentsPage(LookupPage):
    title = "COMPONENTS"
    heading = "COMPONENTS"
    description = ("Search the Star Citizen Wiki for ship components: shop locations, prices and "
                   "specifications. Voice: \"where can I buy an Atlas component\".")
    hint = "Type a component name, for example Atlas, FR-76 or Mantis."
    button_text = "SEARCH WIKI"
    kind_label = "STAR CITIZEN WIKI DATA"
    specs_heading = "SPECIFICATIONS"
    result_types = (scwiki.ItemResult,)

    def suggest(self, query: str) -> list[str]:
        return scwiki.suggest_components(query)

    def lookup(self, query: str) -> scwiki.ItemResult:
        return scwiki.search_component(query)

    def render(self, result: scwiki.ItemResult) -> list[str]:
        lines = [f"{result.name.upper()} — {self.kind_label}", f"Source: {result.url}", "", "BUY LOCATIONS"]
        if result.locations:
            lines += [f"  {l.location:<50} {l.price:>12} aUEC   {l.system}" for l in result.locations]
        else:
            lines.append("  No current Wiki shop locations are listed for this item.")
        lines += ["", self.specs_heading]
        lines += [f"  {k}: {v}" for k, v in result.specs] or ["  No specifications listed."]
        return lines

    def speech(self, result: scwiki.ItemResult) -> str:
        return scwiki.item_speech(result)

    def status_for(self, result: scwiki.ItemResult) -> str:
        return f"Loaded {len(result.locations)} listed location(s) from the Star Citizen Wiki."


PAGE_CLASS = ComponentsPage
