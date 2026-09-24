"""KEYBINDS page: find commands by text or exact keybind (e.g. 'alt+f4') and rebind them."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pages.base import Page
from pages.keybind_widget import KeybindEditor, report_error, store_is_editable
from services.command_store import CUSTOM_CATEGORY, describe_action, key_display, normalize_keys

KEY_TYPES = ("tap", "hold", "press", "release")


class KeybindsPage(Page):
    title = "KEYBINDS"

    def build(self) -> None:
        self.store = self.ctx.commands
        self.read_only = not store_is_editable(self.store)
        self.filter_mode = False
        self.selected_id: str | None = None

        ttk.Label(self, text="KEYBINDS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, style="Muted.TLabel", wraplength=900, text=(
            "Type anything to search, or type a key such as K, I, F12 or alt+f4 and press FILTER BY KEYBIND "
            "to show only the actions assigned to exactly that key.")).pack(anchor="w", pady=(2, 8))

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(row, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.search_all())
        self.search_entry.bind("<Return>", lambda _e: self.filter_by_keybind())
        ttk.Button(row, text="FILTER BY KEYBIND", style="Accent.TButton",
                   command=self.filter_by_keybind).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="SEARCH ALL", command=self.search_all).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="CLEAR", command=self.clear).pack(side="left", padx=(6, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        cols = ("action", "keys", "category", "phrases")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse", height=20)
        for col, text, width in (("action", "ACTION", 220), ("keys", "KEYS", 150),
                                 ("category", "CATEGORY", 140), ("phrases", "PHRASES", 320)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w", stretch=col == "phrases")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.count_var = tk.StringVar()
        ttk.Label(self, textvariable=self.count_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        right = ttk.LabelFrame(body, text="SELECTED ACTION", style="Card.TLabelframe", padding=8)
        right.pack(side="left", fill="y", padx=(12, 0))
        self.sel_label = ttk.Label(right, text="None", style="Title.TLabel", wraplength=300)
        self.sel_label.pack(anchor="w")
        self.sel_info = ttk.Label(right, text="", style="Muted.TLabel", wraplength=300)
        self.sel_info.pack(anchor="w", pady=(0, 8))
        ttk.Label(right, text="KEYBIND", style="Muted.TLabel").pack(anchor="w")
        self.key_editor = KeybindEditor(right, on_change=self.update_conflicts)
        self.key_editor.pack(fill="x")
        self.conflict_var = tk.StringVar()
        ttk.Label(right, textvariable=self.conflict_var, style="Muted.TLabel",
                  wraplength=300).pack(anchor="w", pady=(6, 0))
        self.phrase_preview = tk.Text(right, height=9, width=38, wrap="word", state="disabled")
        self.ctx.theme.style_text(self.phrase_preview)
        self.phrase_preview.pack(fill="both", expand=True, pady=(6, 8))
        self.save_btn = ttk.Button(right, text="SAVE KEYBIND", style="Accent.TButton", command=self.save)
        self.save_btn.pack(fill="x")
        if self.read_only:
            self.save_btn.state(["disabled"])

        self.store.add_listener(self._on_store_saved)
        self.refresh()

    # ------------------------------------------------------------ hooks

    def on_show(self) -> None:
        self.refresh()

    def _on_store_saved(self) -> None:
        try:
            if self.winfo_exists():
                self.refresh()
        except tk.TclError:
            pass

    def show_payload(self, payload):
        """Show a spoken-answer payload: kind "by_key" (filter by key) or "by_command" (select)."""
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        if kind == "by_key":
            key = str(payload.get("key") or "").strip()
            if not key:
                return
            self.search_var.set(key)
            self.filter_mode = True
            self.refresh()
            try:
                self.search_entry.focus_set()
            except tk.TclError:
                pass
        elif kind == "by_command":
            cid = str(payload.get("command_id") or "").strip()
            if not cid:
                return
            self.filter_mode = False
            self.search_var.set("")
            self.refresh()
            if self.tree.exists(cid):
                self.select(cid)
                try:
                    self.tree.see(cid)
                except tk.TclError:
                    pass

    # ------------------------------------------------------------ search

    def _matches(self) -> list[dict]:
        q = self.search_var.get().strip()
        if self.filter_mode:
            if hasattr(self.store, "filter_by_keybind"):
                return self.store.filter_by_keybind(q)
            k = normalize_keys(q)
            return [c for c in self.store.all() if k and normalize_keys(key_display(c.get("action", {}))) == k]
        if hasattr(self.store, "search_all"):
            return self.store.search_all(q)
        ql = q.lower()
        return [c for c in self.store.all()
                if not ql or ql in " ".join([c.get("label", ""), c.get("category", ""),
                                             key_display(c.get("action", {})), *c.get("phrases", [])]).lower()]

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        cmds = self._matches()
        for c in cmds:
            action = c.get("action", {})
            category = CUSTOM_CATEGORY if c.get("custom") else c.get("category", "")
            phrases = ", ".join(c.get("phrases", []))
            self.tree.insert("", "end", iid=c["id"], values=(
                c.get("label", c["id"]), key_display(action) or describe_action(action), category, phrases))
        mode = "keybind filter" if self.filter_mode else "search"
        self.count_var.set(f"{len(cmds)} command(s) — {mode}")
        if self.selected_id and self.tree.exists(self.selected_id):
            self.tree.selection_set(self.selected_id)
            self.tree.see(self.selected_id)

    def filter_by_keybind(self) -> None:
        self.filter_mode = True
        self.refresh()

    def search_all(self) -> None:
        self.filter_mode = False
        self.refresh()

    def clear(self) -> None:
        self.search_var.set("")
        self.filter_mode = False
        self.refresh()

    # ------------------------------------------------------------ editing

    def _on_tree_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if sel and sel[0] != self.selected_id:
            self.select(sel[0])

    def _editable_keys(self, action: dict) -> str | None:
        """Current key string of an action whose keys this page can edit, else None."""
        t = action.get("type")
        if t in KEY_TYPES:
            return action.get("keys", "")
        if t == "mouse":
            return action.get("keys", "")
        return None

    def select(self, command_id: str) -> None:
        c = self.store.get(command_id)
        if c is None:
            return
        self.selected_id = command_id
        if self.tree.exists(command_id) and self.tree.selection() != (command_id,):
            self.tree.selection_set(command_id)
        action = c.get("action", {})
        self.sel_label.configure(text=c.get("label", command_id))
        keys = self._editable_keys(action)
        if keys is None:
            info = f"{describe_action(action)} — this action has no keybind to edit here (use PHRASES)."
        elif action.get("type") == "mouse":
            info = f"{describe_action(action)} — edit the modifier keys held during the click."
        else:
            info = describe_action(action)
        self.sel_info.configure(text=info)
        self.key_editor.set(keys or "")
        self.key_editor.set_enabled(keys is not None and not self.read_only)
        self.phrase_preview.configure(state="normal")
        self.phrase_preview.delete("1.0", "end")
        lines = list(c.get("phrases", [])) + [f"{p} (off)" for p in c.get("disabled_phrases", [])]
        self.phrase_preview.insert("1.0", "\n".join(lines))
        self.phrase_preview.configure(state="disabled")
        self.update_conflicts()

    def update_conflicts(self) -> None:
        if not hasattr(self, "conflict_var") or self.selected_id is None:
            return
        c = self.store.get(self.selected_id) or {}
        action = dict(c.get("action", {}))
        if self._editable_keys(action) is None or not hasattr(self.store, "commands_for_key"):
            self.conflict_var.set("")
            return
        action["keys"] = self.key_editor.get()
        others = [o["label"] for o in self.store.commands_for_key(key_display(action))
                  if o["id"] != self.selected_id]
        self.conflict_var.set(f"Also bound to this key: {', '.join(others)}" if others else "")

    def save(self) -> None:
        if self.read_only or self.selected_id is None:
            return
        cid = self.selected_id
        c = self.store.get(cid) or {}
        action = dict(c.get("action", {}))
        if self._editable_keys(action) is None:
            report_error(self, self.ctx, "Keybinds",
                         f"'{c.get('label', cid)}' ({describe_action(action)}) has no keybind to edit here.")
            return
        keys = self.key_editor.get()
        if keys:
            action["keys"] = keys
        elif action.get("type") == "mouse":
            action.pop("keys", None)
        else:
            report_error(self, self.ctx, "Keybinds", "Enter a keybind.")
            return
        try:
            with self.store.transaction():
                self.store.set_action(cid, action)
                self.store.save()
        except ValueError as e:
            report_error(self, self.ctx, "Keybinds", e)
            return
        except OSError as e:
            report_error(self, self.ctx, "Keybinds", f"Could not write the commands file: {e}")
            return
        c = self.store.get(cid) or {}
        self.ctx.history(f"Keybind for {c.get('label', cid)} set to '{key_display(c.get('action', {}))}'.", "info")
        self.select(cid)


PAGE_CLASS = KeybindsPage
